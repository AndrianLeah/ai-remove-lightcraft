"""AI Remove as a small panel next to LightCraft's (or Chromaforge's) window — a prototype (airemove --panel).

LightCraft has no plug-in panels, so, as OpenFill does next to PhotoCraft (beckettharriman/openfill, Apache-2.0:
photocraft/openfill_photocraft/tether.py), the panel is a window of its own that Windows makes an "owned" window of
the app's: it stays above the app (and only above it), hides when the app is minimized, and follows it when it moves.
It starts docked at the app's right edge; dragged by its header it stays where it was let go, from the app window's
top-left (it moves with the app and opens there next time), and a double-click on the header docks it again.
Elsewhere it is an ordinary window beside it.

Everything else goes through the app's control channel, as AI Remove's window does:
- the app's active photo and its masks are watched; the mask selected in the app (or chosen here) is the selection
  (a SAM 3 Object or Describe mask is read from the develop settings, a brush or gradient one rendered:
  airemove.extract);
- Remove (LaMa, RORem, FLUX Fill, Qwen-Image: the window's model menu), Fill (Generative fill: what the prompt
  describes) or Reflections (DAI, the mask optional) runs in this process, with AI Remove's own Session: its area, its
  tiles, its blend, and the window's progress bar; the text field only for a model that reads text;
- the variants show here and the chosen one on the photo in the app, as its Layout Image (a PNG it draws over the
  photo, fitted to it: only while the photo is shown whole, at Fit); each selection (photo, mask, tab) keeps its
  variants until the panel is closed; Save writes the selection's chosen one into the DNG, stacks it on the original in
  the app and shows it there — without the mask that was the selection;
- "Full window" opens AI Remove's window on the same photo, for what the panel does not do (describe, split, the
  shadow, the brush).
The panel stays open from one photo to the next, and the models stay loaded: only the first variant pays their load.

Tests: AIREMOVE_PANEL_TEST runs steps separated by ";": wait:ms · mode:remove|fill|reflect · model:key ·
mask:<name> · prompt:<text> · variants:n · generate · waitvars:n · pick:i · save · waitidle · drag:dx,dy · dock ·
menu[:close] · shot:n · quit."""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from argparse import Namespace
from pathlib import Path
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk

import airemove as A
import engines
import system
import ui
from i18n import N_, _
from ui import (ACCENT, BG, BTN, BTN_HI, CARD, CARD_HI, DIM, FG, FILL_MENU, LINE, PROMPT_MODE, WARN, HintEntry,
                ModelPicker, model_meta)

# the text field's label and grey hint for each kind of text (PROMPT_MODE): the window's own texts
PROMPT_TEXTS = {"fill": (N_("What to put there (optional)"), N_("in English, e.g. dark doorway, old plaster wall")),
                "name": (N_("What to remove (optional: Qwen-Image names it by itself)"),
                         N_("in English, e.g. the lamp post")),
                "draw": (N_("What to draw (required)"),
                         N_("in English, e.g. a wooden bench, a lemon tree in a terracotta pot"))}

WIDTH = 330  # the panel's width, at 96 dpi
MODES = ("remove", "fill", "reflect")


def mode_title(mode):
    return {"remove": _("Remove"), "fill": _("Fill"), "reflect": _("Reflections")}[mode]


# ------------------------------------------------------------------------------------------------ the tether (Windows)
class Tether:
    """The app's main window (the largest visible one of its process) and the panel made an owned window of it."""

    def __init__(self, exe):
        self.exe, self.hwnd = exe.lower(), 0
        self.ok = sys.platform == "win32"
        if self.ok:
            import ctypes
            from ctypes import wintypes
            self.ct, self.wt = ctypes, wintypes
            self.u32, self.k32 = ctypes.windll.user32, ctypes.windll.kernel32
            self.u32.SetWindowLongPtrW.restype = ctypes.c_void_p
            self.u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

    def _exe(self, hwnd):
        pid = self.wt.DWORD()
        self.u32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        h = self.k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf, n = self.ct.create_unicode_buffer(1024), self.wt.DWORD(1024)
            return Path(buf.value).name.lower() if self.k32.QueryFullProcessImageNameW(h, 0, buf, self.ct.byref(n)) \
                else ""
        finally:
            self.k32.CloseHandle(h)

    def find(self):
        """The app's main window, or 0."""
        if not self.ok:
            return 0
        found = []

        def each(hwnd, __):
            if self.u32.IsWindowVisible(hwnd) and self.u32.GetWindowTextLengthW(hwnd) and self._exe(hwnd) == self.exe:
                r = self.rect(hwnd)
                found.append(((r[2] - r[0]) * (r[3] - r[1]), hwnd))
            return True
        proc = self.ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)(each)
        self.u32.EnumWindows(proc, 0)
        self.hwnd = max(found)[1] if found else 0
        return self.hwnd

    def rect(self, hwnd=None):
        r = self.wt.RECT()
        self.u32.GetWindowRect(hwnd or self.hwnd, self.ct.byref(r))
        return r.left, r.top, r.right, r.bottom

    def own(self, panel_hwnd):
        """The panel becomes an owned window of the app's (GWLP_HWNDPARENT): above it, minimized with it."""
        if self.hwnd:
            self.u32.SetWindowLongPtrW(panel_hwnd, -8, self.hwnd)

    def minimized(self):
        return bool(self.hwnd and self.u32.IsIconic(self.hwnd))

    def front(self):
        """The app's window brought to the front (tests' screenshots): an Alt press first, which Windows wants before
        it lets a background process change the foreground window."""
        if self.hwnd:
            if self.u32.IsIconic(self.hwnd):
                self.u32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            self.u32.keybd_event(0x12, 0, 0, 0)
            self.u32.keybd_event(0x12, 0, 2, 0)
            self.u32.SetForegroundWindow(self.hwnd)

    def alive(self):
        return bool(self.hwnd and self.u32.IsWindow(self.hwnd))


# ------------------------------------------------------------------------------------------------ the panel
class Panel:
    # the window's own: what each model is best for and not for (its model menu, ModelPicker), the progress shown
    # from a plan of expected seconds (job_start/part/exact/total events; self.job, self.task, self.bar, self.status)
    model_best, model_caveat = ui.App.model_best, ui.App.model_caveat
    update_progress, fmt_s = ui.App.update_progress, staticmethod(ui.App.fmt_s)
    on_job_total, on_job_part, on_job_exact = ui.App.on_job_total, ui.App.on_job_part, ui.App.on_job_exact

    def __init__(self, args):
        self.args = args
        self.host = A.host_for(args)
        self.lc = A.LC(host=self.host)
        self.events, self.jobs = queue.Queue(), queue.Queue()
        self.photo = None  # (pid, file name, masks) of the app's active photo
        # each selection's variants, (photo, mask, tab) -> (Session, Removal), kept until the panel is closed; the ones
        # shown are the selection's now (sync_cur), and Save writes those into the photo's new version
        self.gens = {}
        self.cur = None  # (key, Session, Removal) of the selection now, if it has variants
        self.engines = {}  # Session attribute -> engine, kept loaded from one photo's Session to the next
        self.busy = False
        self.job, self.task = None, ""  # the generation's progress plan (the window's update_progress)
        self.msg = ("", DIM)  # what the status line says once nothing is running
        self.thumbs = []
        # the chosen variant drawn on the photo in the app, as its Layout Image (a PNG over the photo, fitted to it):
        # what the app's own setting was before (put back when it is taken away), its files
        self.overlays = queue.Queue()
        self.layout_before, self.overlay_files, self.overlay_n = None, [], 0
        self.overlay_shown = None  # (removal, variant) on the photo now
        self.closing = False
        self.mode, self.mask_id = "remove", None
        # where it was dragged to: its top-left from the app window's top-left (it moves with the app); None: docked at
        # the app's right edge (a double-click on its header docks it again)
        self.offset = A.setting("panel_offset")
        self._drag = None
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)  # as the window: pixels as the app's rectangle
            except Exception:
                pass
        r = self.root = tk.Tk(className="airemove")
        r.title("AI Remove")
        r.configure(bg=BG)
        self.k = k = max(1.0, r.winfo_fpixels("1i") / 96.0)
        self.f_txt = ("Segoe UI", 9) if sys.platform == "win32" else ("Helvetica", 11)
        self.f_bold = (self.f_txt[0], self.f_txt[1], "bold")
        self.f_small = (self.f_txt[0], self.f_txt[1] - 1)
        self.f_head = (self.f_txt[0], self.f_txt[1] - 1, "bold")
        self.width = int(WIDTH * k)
        self.side_w = self.width + int(30 * k)  # ModelPicker's caveat wraps at side_w - 90 (the window's side panel)
        self.on_photo = tk.BooleanVar(value=bool(A.setting("panel_on_photo", True)))
        self.tether = Tether(self.host.exe + ".exe")
        if self.tether.find():
            r.overrideredirect(True)  # docked: its own header, no frame
        self.build()
        r.update_idletasks()
        if self.tether.hwnd:
            self.tether.own(self.root_hwnd())
        self.follow()
        threading.Thread(target=self.watcher, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.overlay_worker, daemon=True).start()
        r.after(100, self.pump)
        steps = os.environ.get("AIREMOVE_PANEL_TEST")
        if steps:
            r.after(1500, lambda: self.test(steps.split(";")))

    def root_hwnd(self):
        import ctypes
        return ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT

    # -------------------------------------------------------------- layout
    def button(self, master, text, cmd, accent=False, small=False):
        b = tk.Button(master, text=text, command=cmd, relief="flat", bd=0, cursor="hand2",
                      font=self.f_bold if accent else (self.f_small if small else self.f_txt),
                      bg=ACCENT if accent else BTN, fg="#1b1b1b" if accent else FG,
                      activebackground=ACCENT if accent else BTN_HI, activeforeground="#1b1b1b" if accent else FG,
                      disabledforeground="#6b6b6b", padx=int(8 * self.k), pady=int(5 * self.k))
        return b

    def build(self):
        k, r = self.k, self.root
        pad = int(10 * k)
        outer = tk.Frame(r, bg=LINE)
        outer.pack(fill="both", expand=True)
        box = self.box = tk.Frame(outer, bg=CARD)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(box, bg=CARD, cursor="fleur")
        head.pack(fill="x", padx=pad, pady=(pad, 4))
        title = tk.Label(head, text="AI Remove", font=self.f_bold, fg=ACCENT, bg=CARD, cursor="fleur")
        title.pack(side="left")
        self.status_dot = tk.Label(head, text="●", font=self.f_small, fg=DIM, bg=CARD, cursor="fleur")
        self.status_dot.pack(side="left", padx=(6, 0))
        for w in (head, title, self.status_dot):  # the header moves the panel; a double-click docks it again
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_move)
            w.bind("<ButtonRelease-1>", self.drag_end)
            w.bind("<Double-Button-1>", self.dock)
        self.button(head, "×", self.close, small=True).pack(side="right")
        self.fold_btn = self.button(head, "–", self.fold, small=True)
        self.fold_btn.pack(side="right", padx=(0, 4))
        body = self.body = tk.Frame(box, bg=CARD)
        body.pack(fill="both", expand=True, padx=pad, pady=(0, pad))
        self.photo_lbl = tk.Label(body, text=_("Waiting for {app}…", app=self.host.name), font=self.f_small, fg=DIM,
                                  bg=CARD, anchor="w", justify="left", wraplength=self.width - 2 * pad)
        self.photo_lbl.pack(fill="x", pady=(0, 8))
        tabs = tk.Frame(body, bg=BTN)
        tabs.pack(fill="x")
        self.tab_btns = {}
        for mode in MODES:
            b = self.button(tabs, mode_title(mode), lambda m=mode: self.set_mode(m))
            b.pack(side="left", fill="x", expand=True)
            self.tab_btns[mode] = b
        # the selection: one of the photo's masks in the app
        self.label(body, _("Selection: a mask of the photo in {app}", app=self.host.name))
        self.mask_var = tk.StringVar(value="")
        self.mask_menu = tk.OptionMenu(body, self.mask_var, "")
        self.style_menu(self.mask_menu)
        self.mask_menu.pack(fill="x")
        self.mask_note = tk.Label(body, text="", font=self.f_small, fg=WARN, bg=CARD, anchor="w", justify="left",
                                  wraplength=self.width - 2 * pad)
        # between the selection and the button, the parts that make sense for the mode and model (layout_boxes): the
        # model, the text, the number of variants, the reflection's strength
        self.model_box = tk.Frame(body, bg=CARD)
        # the window's model menu (what each is for, its time on this PC, what it is best and not for) where there is
        # a choice (Remove); Fill and Reflections have one model each: a line says which, and its time
        self.model_lbl = self.label(self.model_box, _("Model"))
        self.model_var = tk.StringVar(value="")
        self.model_labels = {}
        self.picker = ModelPicker(self.model_box, self, self.model_var)
        self.model_note = tk.Label(self.model_box, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w")
        # the text field, only for a model that reads text (PROMPT_MODE); each kind of text kept apart, as in the
        # window: a name typed for Qwen-Image never reaches Fill as what to draw
        self.prompt_box = tk.Frame(body, bg=CARD)
        self.prompt_lbl = self.label(self.prompt_box, "")
        self.prompt = HintEntry(self.prompt_box, "", font=self.f_txt, bg=BTN, fg=FG, insertbackground=FG,
                                relief="flat", highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        self.prompt.pack(fill="x", ipady=int(4 * k))
        self.prompt_mode, self.prompt_text = None, {}
        self.n_box = tk.Frame(body, bg=CARD)  # not for LaMa or DAI: one result each
        self.label(self.n_box, _("Variants"))
        row = tk.Frame(self.n_box, bg=CARD)
        row.pack(fill="x")
        self.n_var = tk.IntVar(value=2)
        self.n_btns = []
        for n in (1, 2, 3, 4):
            b = self.button(row, str(n), lambda n=n: self.set_n(n), small=True)
            b.pack(side="left", fill="x", expand=True, padx=(0 if n == 1 else 2, 0))
            self.n_btns.append(b)
        self.strength_box = tk.Frame(body, bg=CARD)
        self.label(self.strength_box, _("Strength (how much of the reflection goes)"))
        self.strength = tk.Scale(self.strength_box, from_=0, to=150, orient="horizontal", bg=CARD, fg=FG,
                                 troughcolor=BTN, highlightthickness=0, bd=0, font=self.f_small)
        self.strength.pack(fill="x")
        self.strength.set(75)
        self.gen_btn = self.button(body, "", self.generate, accent=True)
        self.gen_btn.pack(fill="x", pady=(10, 0))
        # while it works, as in the window: a bar, then what it is doing, how far it is and the time still to go
        st = ttk.Style(r)
        st.theme_use("clam")
        st.configure("AI.Horizontal.TProgressbar", troughcolor=BTN, background=ACCENT, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT, thickness=max(3, int(4 * k)))
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=1000, value=0,
                                   style="AI.Horizontal.TProgressbar")
        self.status = tk.Label(body, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                               wraplength=self.width - 2 * pad)
        self.status.pack(fill="x", pady=(6, 0))
        self.grid = tk.Frame(body, bg=CARD)
        self.grid.pack(fill="x", pady=(6, 0))
        # the chosen variant on the photo in the app (its Layout Image); off: only the thumbnails here
        self.on_photo_chk = tk.Checkbutton(body, text=_("Show the chosen variant on the photo in {app}",
                                                        app=self.host.name),
                                           variable=self.on_photo, command=self.on_photo_toggled, font=self.f_small,
                                           bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                                           selectcolor=BTN, highlightthickness=0, bd=0, anchor="w", cursor="hand2")
        self.on_photo_note = tk.Label(body, text=_("It shows when {app} fits the whole photo in the view (not zoomed "
                                                   "in, not cropping).", app=self.host.name),
                                      font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                      wraplength=self.width - 2 * pad)
        bottom = self.bottom = tk.Frame(body, bg=CARD)
        bottom.pack(fill="x", pady=(8, 0))
        self.save_btn = self.button(bottom, _("Save to {app}", app=self.host.name), self.save)
        self.save_btn.pack(side="left", fill="x", expand=True)
        self.full_btn = self.button(bottom, _("Full window"), self.full_window, small=True)
        self.full_btn.pack(side="left", padx=(4, 0))
        self.model_var.trace_add("write", lambda *a: self.on_model_change())  # also when set by code
        self.mask_var.trace_add("write", lambda *a: self.sync_cur())  # another selection: its own variants
        self.set_mode("remove")
        self.set_n(2)

    def label(self, master, text):
        lbl = tk.Label(master, text=text, font=self.f_small, fg=DIM, bg=CARD, anchor="w")
        lbl.pack(fill="x", pady=(8, 2))
        return lbl

    def style_menu(self, m):
        m.configure(bg=BTN, fg=FG, activebackground=BTN_HI, activeforeground=FG, relief="flat", bd=0,
                    highlightthickness=0, font=self.f_txt, anchor="w")
        m["menu"].configure(bg=CARD_HI, fg=FG, activebackground=ACCENT, activeforeground="#1b1b1b", font=self.f_txt)

    @staticmethod
    def set_options(menu, var, options, keep=True):
        """An OptionMenu's entries: options is [(label, value)]; var holds the label."""
        m = menu["menu"]
        m.delete(0, "end")
        for label, __ in options:
            m.add_command(label=label, command=lambda v=label: var.set(v))
        labels = [lb for lb, __ in options]
        if not (keep and var.get() in labels):
            var.set(labels[0] if labels else "")

    # -------------------------------------------------------------- modes and choices
    def models_for(self, mode):
        if mode == "remove":
            return [m for m in FILL_MENU if m == "lama" or engines.usable(m)]
        if mode == "fill":
            return ["fill"] if engines.usable("fill") else []
        return ["dai"] if engines.usable("dai") else []

    def set_mode(self, mode):
        self.mode = mode
        for m, b in self.tab_btns.items():
            b.configure(bg=ACCENT if m == mode else BTN, fg="#1b1b1b" if m == mode else FG,
                        activebackground=ACCENT if m == mode else BTN_HI)
        models = self.models_for(mode)
        meta = model_meta()  # its times from this PC's last runs: read again at each change of mode
        self.model_labels = {m: f"{n} · {u} · {t}" for m, (n, u, t) in meta.items()}
        for w in (self.model_lbl, self.picker, self.model_note):
            w.pack_forget()
        if len(models) > 1:  # Remove: the menu, on the model chosen last time (RORem at first)
            last = A.setting("panel_model", "rorem")
            cur = last if last in models else ("rorem" if "rorem" in models else models[0])
            self.picker.set_models(meta, models)
            self.model_lbl.pack(fill="x", pady=(8, 2))
            self.picker.pack(fill="x")
        else:
            cur = models[0] if models else None
            name, __, t = meta.get(cur, ("", "", ""))
            self.model_note.configure(text=f"{name} · {t}" if cur else "")
            self.model_note.pack(fill="x", pady=(8, 0))
        self.gen_btn.configure(text={"remove": _("Remove the selection"), "fill": _("Draw in the selection"),
                                     "reflect": _("Remove reflections")}[mode])
        self.refresh_masks()
        self.model_var.set(self.model_labels[cur] if cur else "")  # on_model_change: the text, the boxes
        self.sync_cur()  # each tab has its own variants

    def on_model_change(self):
        m = self.model_key()
        if self.picker.winfo_manager():
            self.picker.show()
            if m:
                A.remember("panel_model", m)
        self.apply_prompt_mode()
        self.layout_boxes()
        self.update_buttons()

    def model_key(self):
        return next((m for m, label in self.model_labels.items() if label == self.model_var.get()), None)

    def apply_prompt_mode(self):
        """The text field for the chosen model (PROMPT_MODE): its label and grey hint, and the text typed for that kind
        of text (the window's apply_prompt_mode)."""
        mode = PROMPT_MODE.get(self.model_key())
        if mode != self.prompt_mode:
            if self.prompt_mode is not None:
                self.prompt_text[self.prompt_mode] = self.prompt.get()
            self.prompt_mode = mode
            self.prompt.set_text(self.prompt_text.get(mode, "") if mode else "")
        if mode:
            label, hint = PROMPT_TEXTS[mode]
            self.prompt_lbl.configure(text=_(label))
            self.prompt.set_hint(_(hint))

    def layout_boxes(self):
        """Between the selection and the button, in their order, the parts that make sense now: the model, the text
        (a model that reads one), the number of variants (not LaMa, not DAI: one result each), the strength
        (Reflections)."""
        boxes = ((self.model_box, True), (self.prompt_box, self.prompt_mode is not None),
                 (self.n_box, self.model_key() not in ("lama", "dai")), (self.strength_box, self.mode == "reflect"))
        for w, __ in boxes:
            w.pack_forget()
        for w, on in boxes:
            if on:
                w.pack(fill="x", before=self.gen_btn)

    def set_n(self, n):
        self.n_var.set(n)
        for i, b in enumerate(self.n_btns):
            on = i + 1 == n
            b.configure(bg=CARD_HI if on else BTN, fg=ACCENT if on else FG)

    def mask_options(self):
        masks = self.photo[2] if self.photo else []
        opts = [(f"{m.get('name') or _('Mask {id}', id=m['id'])}  ·  {kind_of(m)}", m["id"]) for m in masks]
        if self.mode == "reflect":
            opts.insert(0, (_("The whole photo"), None))
        return opts

    def refresh_masks(self):
        opts = self.mask_options()
        self.set_options(self.mask_menu, self.mask_var, opts or [(_("(no mask: make one in {app})",
                                                                    app=self.host.name), None)])
        if not opts and self.photo:
            self.mask_note.configure(text=_("Make a mask on the photo in {app} (an Object mask selects with one "
                                            "click), then choose it here.", app=self.host.name))
            self.mask_note.pack(fill="x", pady=(4, 0), after=self.mask_menu)
        else:
            self.mask_note.pack_forget()

    def chosen_mask(self):
        return dict(self.mask_options()).get(self.mask_var.get())

    def update_buttons(self):
        ready = self.photo is not None and not self.busy
        has_mask = bool(self.mask_options())
        self.gen_btn.configure(state="normal" if ready and has_mask and self.model_key() else "disabled")
        live = self.cur is not None and self.cur[2].candidates and self.cur[2].chosen is not None
        self.save_btn.configure(state="normal" if live and not self.busy else "disabled")
        self.full_btn.configure(state="normal" if self.photo else "disabled")
        self.status_dot.configure(fg=ACCENT if self.busy else ("#4a9c63" if self.photo else DIM))

    # -------------------------------------------------------------- following the app
    def follow(self):
        """With the app's window: where it was dragged to (self.offset, from the window's top-left), else docked at its
        right edge under its title bar; hidden while the app is minimized."""
        t = self.tether
        if t.hwnd and not t.alive():
            t.find()
            if t.hwnd:
                t.own(self.root_hwnd())
        if t.hwnd and self._drag is None:
            if t.minimized():
                self.root.withdraw()
            else:
                left, top, right, bottom = t.rect()
                h = self.root.winfo_reqheight()
                if self.offset:
                    # never lost: at least its header stays over the app's window
                    x = min(max(left + self.offset[0], left - self.width + int(80 * self.k)), right - int(80 * self.k))
                    y = min(max(top + self.offset[1], top), bottom - int(40 * self.k))
                    geo = f"{self.width}x{h}+{x}+{y}"
                else:
                    x, y = right - self.width - int(24 * self.k), top + int(96 * self.k)
                    geo = f"{self.width}x{min(h, bottom - y - int(40 * self.k))}+{x}+{y}"
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                if self.root.geometry() != geo:
                    self.root.geometry(geo)
        elif not getattr(self, "_placed", False):
            self.root.geometry(f"{self.width}x{max(self.root.winfo_reqheight(), 500)}")
            self._placed = True
        self.root.after(400, self.follow)

    def watcher(self):
        """The app's active photo, its masks and how it is shown, every second and a half (the app has no events to
        listen to)."""
        last = None
        while True:
            try:
                st = self.lc.state()
                pid = (st.get("selection") or {}).get("active")
                info = self.lc.one("photo.inspect", {"id": pid}) if pid else None
                now = None if info is None else (pid, info.get("file_name"),
                                                 [m for m in info["develop"]["masks"] if m.get("visible", True)],
                                                 st.get("activeMask"),  # the mask being edited in the app
                                                 self.whole_view())
                key = None if now is None else (pid, tuple((m["id"], m.get("name")) for m in now[2]), now[3], now[4])
                if key != last:
                    last = key
                    self.events.put(("photo", now))
            except A.Fail as e:
                if last != "down":
                    last = "down"
                    self.events.put(("down", str(e).splitlines()[0]))
            except Exception as e:
                A.log("panel watcher:", repr(e))
            time.sleep(1.5)

    def whole_view(self):
        """Whether the app shows the photo whole, as cropped, fitted in the view (Detail, Fit, not the crop tool, no
        before/after): its Layout Image then lies on the photo. Zoomed in, it stays fitted to the view instead."""
        try:
            u = self.lc.call("ui.inspect").get("ui") or {}
        except A.Fail:
            return True  # an app without ui.inspect: as at Fit
        return (u.get("view", "detail") == "detail" and u.get("zoom", "fit") == "fit" and u.get("right") != "crop"
                and u.get("beforeAfter", "off") == "off")

    def pump(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "photo":
                self.photo = data
                self.photo_lbl.configure(text=(_("Photo: {name}", name=data[1]) if data else
                                               _("No active photo in {app}", app=self.host.name)))
                self.refresh_masks()
                if data and data[3] is not None:  # the mask selected in the app becomes the selection here
                    label = next((lb for lb, mid in self.mask_options() if mid == data[3]), None)
                    if label:
                        self.mask_var.set(label)
                self.sync_cur()  # another photo or mask: its own variants, on the photo too
            elif kind == "down":
                self.photo = None
                self.photo_lbl.configure(text=data)
            elif kind in ("progress", "error"):
                self.msg = (data, WARN if kind == "error" else DIM)
                if self.job is None:
                    self.status.configure(text=data, fg=self.msg[1])
            elif kind == "job_start":
                label, total = data
                now = time.time()
                self.job = {"label": label, "total": total, "t0": now, "mode": "timed", "base": 0.0, "secs": 1.0,
                            "t_part": now, "exact": 0.0}
                self.bar.pack(fill="x", pady=(8, 0), before=self.status)
            elif kind == "job_total":
                self.on_job_total(data)
            elif kind == "job_part":
                self.on_job_part(data)
            elif kind == "job_exact":
                self.on_job_exact(data)
            elif kind == "thumbs":  # new variants for a selection: shown if it is the one now
                if data == self.current_key():
                    self.sync_cur()
            elif kind == "done":
                self.busy, self.job = False, None
                self.bar.pack_forget()
                self.bar.configure(value=0)
                self.status.configure(text=self.msg[0], fg=self.msg[1])
            self.update_buttons()
        if self.job is not None:
            self.update_progress()  # the window's: the bar and "what · 42% · ~12 s"
        self.root.after(100, self.pump)

    # -------------------------------------------------------------- generating
    def generate(self):
        if self.busy or not self.photo:
            return
        model = self.model_key()
        prompt = self.prompt.get().strip() if self.prompt_mode else ""  # a model that reads no text gets none
        if self.prompt_mode == "draw" and not prompt:
            self.status.configure(text=_("Write what to draw first, in English (e.g. a wooden bench)."), fg=WARN)
            self.prompt.focus_set()
            return
        self.busy = True
        self.jobs.put(("generate", self.photo[0], self.chosen_mask(), self.mode, model, prompt, self.n_var.get(),
                       self.strength.get() / 100))
        self.update_buttons()

    def save(self):
        if self.busy or self.cur is None:
            return
        self.busy = True
        self.overlays.put(None)  # the DNG shows the result itself
        self.jobs.put(("save", self.cur[1]))  # this selection's variant only: its Session has no other removal
        self.update_buttons()

    def worker(self):
        while True:
            job = self.jobs.get()
            try:
                if job[0] == "generate":
                    self.run_generate(*job[1:])
                elif job[0] == "save":
                    s = job[1]
                    self.events.put(("job_start", (_("Saving the DNG and stacking it in {app}…", app=self.host.name),
                                                   A.expected("save"))))
                    s.save_project()
                    out, nid, __ = s.write_all()
                    self.events.put(("progress", _("Saved: {file}, stacked on the original in {app}.",
                                                   file=Path(out).name, app=self.host.name)))
            except A.Fail as e:
                self.events.put(("error", str(e)))
            except Exception as e:
                A.log("panel ERROR:", repr(e))
                import traceback
                A.log(traceback.format_exc())
                self.events.put(("error", f"{type(e).__name__}: {e}"))
            finally:
                self.events.put(("done", None))

    def run_generate(self, pid, mask_id, mode, model, prompt, n, strength):
        """Variants of `model` for the selection (a new removal, or more for the last one), with the window's progress
        plan: each part's expected seconds on this PC, the model's steps as they go (ui.App.run_job)."""
        key = (pid, mask_id, mode)
        reflect, draw = mode == "reflect", mode == "fill"
        s, r = self.gens.get(key, (None, None))  # more variants for a selection that has some
        if r is not None and r.deleted:
            s = r = None

        def variant_secs():  # a long removal's variants are filled in squares: known once its area is
            if r is not None:
                return s.variant_seconds(r, model)
            return A.expected("lama" if model == "lama" else f"{model}_variant")
        parts = []
        if r is None:
            parts += [("read", _("Reading the photo and its mask from {app}…", app=self.host.name),
                       A.expected("panel_read")),
                      ("area", _("Preparing the area"), A.expected("reflection_area" if reflect else "area"))]
        if model == "lama":  # one result
            if r is None or not any(c[0] == "LaMa" for c in r.candidates):
                parts.append(("lama", "LaMa", variant_secs()))
        else:
            if not (s.engine_loaded(model) if s is not None else self.loaded(model)):
                parts.append(("load", _("Loading {model}", model=A.MODELS[model]), A.expected(f"{model}_load")))
            n = 1 if reflect else n  # DAI: one result, at the strength set
            parts += [("variant", f"{A.MODELS[model]} {i + 1}/{n}", variant_secs()) for i in range(n)]
        self.events.put(("job_start", (parts[0][1] if parts else "", sum(p[2] for p in parts))))
        done, i = 0.0, -1
        while i + 1 < len(parts):
            i += 1
            kind, label, secs = parts[i]
            self.events.put(("job_part", (label, done, secs)))
            if kind == "read":
                t0 = time.time()
                s = self.read(pid, mask_id)
                A.measured("panel_read", time.time() - t0)
            elif kind == "area":
                sel = s.init_mask
                if sel is None:
                    if not reflect:
                        raise A.Fail(_("The mask selects nothing AI Remove can read: choose another, or make an "
                                       "Object mask."))
                    sel = np.ones(s.base_arr.shape[:2], bool)
                r = s.new_removal(sel, reflection=reflect, draw=draw)
                self.gens[key] = (s, r)
                A.log(f"panel: #{r.id} on {s.info.get('file_name')}")
                self.events.put(("thumbs", key))
                parts[i + 1:] = [(k, lb, variant_secs() if k in ("lama", "variant") else sec)
                                 for k, lb, sec in parts[i + 1:]]
                self.events.put(("job_total", done + secs + sum(p[2] for p in parts[i + 1:])))
            elif kind == "lama":
                s.run_lama(r)
                self.events.put(("thumbs", key))
            elif kind == "load":
                s.get_engine(model)
            else:
                def prog(step, total, base=done, secs=secs, label=label):
                    self.events.put(("job_exact", (_("{task} · step {i}/{total}", task=label, i=step, total=total),
                                                   base + secs * step / max(1, total))))
                s.run_model(r, model, prompt, progress=prog)
                self.events.put(("thumbs", key))
            done += secs
        if reflect:
            s.set_strength(r, strength)
        self.engines = {a: getattr(s, a) for a in A.ENGINE_ATTRS.values() if getattr(s, a, None) is not None}
        self.events.put(("progress", _("Choose a variant, then save it to {app}.", app=self.host.name)))
        self.events.put(("thumbs", key))

    def read(self, pid, mask_id):
        """A Session on the photo, the mask as its selection, with the engines an earlier photo's Session loaded."""
        args = Namespace(id=pid, raw=None, variants=None, auto=None, shadow=False, check=False, app=self.host.key)
        s = A.Session(self.lc, args)
        s.find()
        chosen = [m for m in s.info["develop"]["masks"] if m["id"] == mask_id]
        s.targets, s.prompt = chosen, ""
        s.used_masks = [m["name"] for m in chosen if m.get("name")]
        s.prepare()
        for attr, eng in self.engines.items():
            setattr(s, attr, eng)
        return s

    def loaded(self, model):
        """Whether an earlier photo's Session left `model`'s engine loaded (Session.engine_loaded, before a Session)."""
        spec = A.ENGINES.get(model)
        return bool(spec and spec.engine and A.ENGINE_ATTRS.get(spec.engine) in self.engines)

    # -------------------------------------------------------------- variants
    def current_key(self):
        """The selection now: the app's active photo, the mask chosen, the tab."""
        return (self.photo[0], self.chosen_mask(), self.mode) if self.photo else None

    def sync_cur(self):
        """The variants shown are the selection's now (photo, mask, tab), on the photo in the app too: another
        selection's stay in memory until the panel is closed, and come back with it."""
        key = self.current_key()
        s, r = self.gens.get(key, (None, None))
        cur = (key, s, r) if r is not None and not r.deleted else None
        choose = _("Choose a variant, then save it to {app}.", app=self.host.name)
        if (cur and cur[0]) != (self.cur and self.cur[0]) and self.job is None:
            if cur is not None:
                self.msg = (choose, DIM)
            elif self.msg[0] == choose:  # nothing to choose for this selection ("Saved: …" stays)
                self.msg = ("", DIM)
            self.status.configure(text=self.msg[0], fg=self.msg[1])
        self.cur = cur
        self.show_thumbs()
        self.show_on_photo()
        self.update_buttons()

    def show_thumbs(self):
        for w in self.grid.winfo_children():
            w.destroy()
        self.thumbs = []
        if self.cur is None:
            self.on_photo_chk.pack_forget()
            return
        __, s, r = self.cur
        side = (self.width - int(20 * self.k) - 2 - 2 * 8) // 2  # the body's padding, the border, two cells' margins
        for i, (label, __) in enumerate(r.candidates):
            try:
                patch, __ = s.preview(r, i)
            except Exception as e:
                A.log("panel preview:", repr(e))
                continue
            im = Image.fromarray(np.ascontiguousarray(patch))
            im.thumbnail((side, side))
            ph = ImageTk.PhotoImage(im)
            self.thumbs.append(ph)
            on = r.chosen == i
            cell = tk.Frame(self.grid, bg=ACCENT if on else CARD, padx=2, pady=2)
            cell.grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="n")
            img = tk.Label(cell, image=ph, bg=CARD, cursor="hand2")
            img.pack()
            cap = tk.Label(cell, text=("✓ " if on else "") + A.variant_text(r, label), font=self.f_small,
                           fg=ACCENT if on else FG, bg=CARD)
            cap.pack(fill="x")
            for w in (cell, img, cap):
                w.bind("<Button-1>", lambda e, i=i: self.pick(i))
        if r.candidates and not self.on_photo_chk.winfo_manager():
            self.on_photo_chk.pack(fill="x", pady=(6, 0), before=self.bottom)
        elif not r.candidates:
            self.on_photo_chk.pack_forget()

    def pick(self, i):
        if self.cur is None or self.busy:
            return
        r = self.cur[2]
        if 0 <= i < len(r.candidates):
            r.chosen, r.user_picked = i, True
            self.show_thumbs()
            self.show_on_photo()
            self.update_buttons()

    # -------------------------------------------------------------- the variant on the photo in the app
    def show_on_photo(self):
        """The chosen variant onto the photo in the app, while it is the app's active photo (overlay_worker), else
        away from it."""
        cur = self.cur
        wanted = (cur is not None and self.on_photo.get() and cur[2].chosen is not None and self.photo is not None
                  and self.photo[0] == cur[1].pid)
        on = wanted and self.photo[4]  # the photo whole in the view (whole_view)
        self.overlays.put((cur[1], cur[2], cur[2].chosen) if on else None)
        if wanted and not on and self.on_photo_chk.winfo_manager():
            self.on_photo_note.pack(fill="x", after=self.on_photo_chk)
        else:
            self.on_photo_note.pack_forget()

    def on_photo_toggled(self):
        A.remember("panel_on_photo", self.on_photo.get())
        self.show_on_photo()

    def overlay_worker(self):
        """The app's Layout Image (a PNG it draws over the photo, fitted to it): the chosen variant, or the app's own
        setting back. Only the latest request counts."""
        while True:
            want = self.overlays.get()
            while not self.overlays.empty():
                want = self.overlays.get()
            shown = (id(want[1]), want[2]) if want else None
            if shown is not None and shown == self.overlay_shown and self.layout_before is not None:
                continue  # already on the photo (another mask clicked in the app, the same variant)
            try:
                path = self.overlay_png(*want) if want else None
                if path and not self.closing:
                    self.put_layout(path)
                    self.overlay_shown = shown
                else:
                    self.take_layout()
                    self.overlay_shown = None
            except Exception as e:
                A.log("panel on the photo:", repr(e))

    def overlay_png(self, s, r, idx):
        """The variant as the app shows the photo: transparent but where it changes it (its blend, as composite),
        cut to the app's crop, as a PNG in the Session's folder. None where the app's view cannot be matched: a
        rotated or flipped crop, Upright or a transform (base.png is without them). A lens profile is not undone in
        base.png either: near the edges of a wide lens the variant may sit a pixel or two off."""
        dev = self.lc.one("photo.inspect", {"id": s.pid})["develop"]
        crop, geo = dev["crop"], dev.get("geometry") or {}
        g = crop["geometry"]
        if (g.get("angle") or crop.get("flip_h") or crop.get("flip_v")
                or any(geo.get(k, v) != v for k, v in A.NEUTRAL_GEOMETRY.items())):
            A.log("panel: not shown on the photo (a rotated or flipped crop, or a geometry transform)")
            return None
        patch, al = s.preview(r, idx)
        h, w = s.base_arr.shape[:2]
        y0, y1, x0, x1 = r.base_rect
        rgba = np.zeros((h, w, 4), np.uint8)
        sub = rgba[y0:y1, x0:x1]
        ph, pw = sub.shape[:2]
        sub[..., :3] = patch[:ph, :pw]
        sub[..., 3] = np.clip(np.asarray(al)[:ph, :pw] * 255, 0, 255).astype(np.uint8)
        c = g["rect"]
        im = Image.fromarray(rgba, "RGBA").crop((round(c["x0"] * w), round(c["y0"] * h), round(c["x1"] * w),
                                                 round(c["y1"] * h)))
        self.overlay_n += 1
        path = s.work / f"on-photo-{self.overlay_n}.png"  # a new name each time: the app reads it again
        im.save(path)
        self.overlay_files.append(path)
        return path

    def put_layout(self, path):
        if self.layout_before is None:  # the app's own setting, put back by take_layout
            self.layout_before = ((self.lc.call("ui.inspect").get("ui") or {}).get("layoutImage")
                                  or {"path": "", "show": False, "opacity": 1, "matte": 0})
        self.lc.call("ui.set", {"layoutImage": {"path": str(path), "show": True, "opacity": 1, "matte": 0}})
        self.drop_overlay_files(keep=1)

    def take_layout(self):
        if self.layout_before is not None:
            self.lc.call("ui.set", {"layoutImage": self.layout_before})
            self.layout_before = None
        self.drop_overlay_files()

    def drop_overlay_files(self, keep=0):
        while len(self.overlay_files) > keep:
            try:
                self.overlay_files.pop(0).unlink()
            except OSError:
                pass

    # -------------------------------------------------------------- the rest
    def full_window(self):
        """AI Remove's own window on the same photo (describe, split, the shadow, the brush)."""
        if not self.photo:
            return
        main = Path(A.__file__).resolve()
        subprocess.Popen([sys.executable, str(main), "--id", str(self.photo[0]), "--app", self.host.key],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

    # -------------------------------------------------------------- moving it
    def drag_start(self, e):
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self._drag = {"grab": (e.x_root - x, e.y_root - y), "from": (x, y), "to": (x, y)}

    def drag_move(self, e):
        if self._drag is not None:
            gx, gy = self._drag["grab"]
            self._drag["to"] = (e.x_root - gx, e.y_root - gy)
            self.root.geometry("+%d+%d" % self._drag["to"])

    def drag_end(self, e=None):
        """Where it was let go, kept from the app window's top-left: it moves with the app, and opens there next
        time. A click that did not move it leaves it where it was (docked stays docked)."""
        if self._drag is None:
            return
        d, self._drag = self._drag, None
        if d["to"] != d["from"] and self.tether.hwnd:
            left, top, __, __ = self.tether.rect()
            self.offset = [d["to"][0] - left, d["to"][1] - top]
            A.remember("panel_offset", self.offset)

    def dock(self, e=None):
        """Back at the app's right edge (a double-click on the header)."""
        self._drag, self.offset = None, None
        A.remember("panel_offset", None)

    def fold(self):
        if self.body.winfo_manager():
            self.body.pack_forget()
            self.fold_btn.configure(text="+")
        else:
            self.body.pack(fill="both", expand=True, padx=int(10 * self.k), pady=(0, int(10 * self.k)))
            self.fold_btn.configure(text="–")

    def close(self):
        self.closing = True
        try:
            self.take_layout()  # the app's own Layout Image setting back
        except Exception as e:
            A.log("panel on the photo:", repr(e))
        A.log("panel closed")
        self.root.destroy()

    def shot(self, n):
        """The app's window with the panel on it, from the screen."""
        from PIL import ImageGrab
        self.tether.front()
        self.root.lift()
        if self.picker.pop is not None:  # the model menu's list, open
            self.picker.pop.lift()
        self.root.update()
        time.sleep(0.6)
        if self.tether.hwnd:
            box = self.tether.rect()
        else:
            box = (self.root.winfo_rootx(), self.root.winfo_rooty(),
                   self.root.winfo_rootx() + self.root.winfo_width(), self.root.winfo_rooty() + self.root.winfo_height())
        ImageGrab.grab(bbox=box, all_screens=True).save(system.ROOT / "work" / f"panel-shot-{n}.png")

    def test(self, steps):
        """AIREMOVE_PANEL_TEST: see the module's docstring."""
        if not steps:
            return
        kind, __, arg = steps[0].partition(":")
        delay = 300
        if kind == "wait":
            delay = int(arg)
        elif kind == "mode":
            self.set_mode(arg)
        elif kind == "model":
            self.model_var.set(self.model_labels[arg])
        elif kind == "mask":
            label = next((lb for lb, __ in self.mask_options() if lb.startswith(arg + "  ·")), None)
            if label is None:
                self.root.after(500, lambda: self.test(steps))
                return
            self.mask_var.set(label)
        elif kind == "prompt":
            self.prompt.delete(0, "end")
            self.prompt.insert(0, arg)
        elif kind == "variants":
            self.set_n(int(arg))
        elif kind == "generate":
            self.update_buttons()
            self.generate()
        elif kind in ("waitvars", "waitidle"):
            want = int(arg or 0)
            if self.busy or (kind == "waitvars" and (self.cur is None or len(self.cur[2].candidates) < want)):
                self.root.after(500, lambda: self.test(steps))
                return
        elif kind == "pick":
            self.pick(int(arg))
        elif kind == "save":
            self.save()
        elif kind == "drag":  # as dragging the header by dx,dy pixels and letting go
            dx, dy = (int(v) for v in arg.split(","))
            x0, y0 = self.root.winfo_x(), self.root.winfo_y()
            e = type("E", (), {"x_root": x0 + 10, "y_root": y0 + 10})()
            self.drag_start(e)
            e.x_root, e.y_root = x0 + 10 + dx, y0 + 10 + dy
            self.drag_move(e)
            self.drag_end()
            delay = 800
        elif kind == "dock":
            self.dock()
            delay = 800
        elif kind == "menu":  # the model menu's list, open or closed
            self.picker.open() if arg != "close" else self.picker.close()
            delay = 800
        elif kind == "shot":
            self.shot(int(arg or 0))
        elif kind == "quit":
            A.log("panel TEST end")
            self.close()
            return
        self.root.after(delay, lambda: self.test(steps[1:]))


def kind_of(mask):
    """What a mask of the app is made of, in a word (its first component)."""
    comps = mask.get("components") or []
    kind = ((comps[0].get("shape") or {}).get("kind") if comps else "") or "?"
    return {"object": _("Object"), "prompt": _("Describe"), "brush": _("Brush"), "linear": _("Linear"),
            "radial": _("Radial")}.get(kind, kind)


def run(args):
    p = Panel(args)
    A.log(f"panel open next to {p.host.name}" + (" (attached to its window)" if p.tether.hwnd else ""))
    p.root.mainloop()
    return 0
