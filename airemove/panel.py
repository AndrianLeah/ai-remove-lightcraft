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
  airemove.extract, airemove.mask_selection);
- the window's tabs (ui.TABS): Remove (LaMa, RORem, FLUX Fill, Qwen-Image: the window's model menu), Fill (Generative
  fill: what the prompt describes) or Reflections (DAI on the whole photo, as Lightroom's Remove Reflections; its
  strength is Lightroom's Amount, also afterwards) run in this process, with AI Remove's own Session: its area, its
  tiles, its blend, and the window's progress bar; the text field only for a model that reads text;
- one Session per photo, as in the window, with one removal per selection (mask, tab), kept until the panel is
  closed (and found again in the photo's project, by its mask's name, once saved). The selection's variants show
  here; every removal with a chosen variant shows on the photo in the app, as its Layout Image (a PNG it draws over the
  photo, fitted to it: only while the photo is shown whole, at Fit), and that is what Save writes into the DNG,
  stacked on the original — without the masks that were the selections. After a save the app shows the DNG: it is the
  same photo here, and the next save updates it;
- "Full window" opens AI Remove's window in this process on the same Session (ui.App with master / on_close /
  start): the removals and variants, the selection, the tab, the model, the texts; "Back to the panel" brings them
  back. For what the panel does not do: describe, split, the shadow, the brush.
The panel stays open from one photo to the next, and the models stay loaded: only the first variant pays their load.

Tests: AIREMOVE_PANEL_TEST runs steps separated by ";": wait:ms · mode:remove|fill|reflect · model:key ·
mask:<name> · prompt:<text> · variants:n · generate · waitvars:n · pick:i · save · waitidle · drag:dx,dy · dock ·
menu[:close] · discard · full · window[:closed] · wshot:n · wtab:<tab> · wback · shot:n · quit."""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from argparse import Namespace
from pathlib import Path
from tkinter import ttk

import numpy as np
from PIL import Image, ImageOps, ImageTk

import airemove as A
import engines
import system
import ui
from i18n import N_, _, _n
from ui import (ACCENT, BG, BTN, BTN_HI, CARD, CARD_HI, DIM, FG, LINE, PROMPT_MODE, TABS, WARN, HintEntry, ModelPicker,
                model_meta, tab_of)

# the text field's label and grey hint for each kind of text (PROMPT_MODE): the window's own texts
PROMPT_TEXTS = {"fill": (N_("What to put there (optional)"), N_("in English, e.g. dark doorway, old plaster wall")),
                "name": (N_("What to remove (optional: Qwen-Image names it by itself)"),
                         N_("in English, e.g. the lamp post")),
                "draw": (N_("What to draw (required)"),
                         N_("in English, e.g. a wooden bench, a lemon tree in a terracotta pot"))}

WIDTH = 330  # the panel's width, at 96 dpi

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
        # one Session per photo, as in the window: the photo's removals (its project, its DNG), one per selection made
        # here — (photo, mask, tab) -> Removal — kept until the panel is closed. The ones shown are the selection's now
        # (sync_cur); Save writes every removal with a chosen variant, as the photo in the app shows them
        self.sessions, self.gens = {}, {}
        self.cur = None  # (key, Session, Removal) of the selection now, if it has variants
        self.saved = {}  # Session -> what its last save wrote, {Removal: (variant, strength)}: its DNG has those
        self.window = None  # AI Remove's window while it is open, in this process (full_window)
        self._below = None  # which of the lines under the variants are shown (update_buttons)
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
        self.overlay_problem = None  # why the variants cannot be drawn on this photo (overlay_png), said under them
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
        tabs = self.tabs = tk.Frame(body, bg=BTN)
        tabs.pack(fill="x")
        self.tab_btns = {}
        for mode, (title, __) in TABS.items():  # the window's tabs (ui.TABS)
            b = self.button(tabs, _(title), lambda m=mode: self.set_mode(m))
            b.pack(side="left", fill="x", expand=True)
            self.tab_btns[mode] = b
        # the selection: one of the photo's masks in the app (none in Reflections: the whole photo, as Lightroom's
        # Remove Reflections)
        self.sel_box = tk.Frame(body, bg=CARD)
        self.sel_box.pack(fill="x")
        self.label(self.sel_box, _("Selection: a mask of the photo in {app}", app=self.host.name))
        self.mask_var = tk.StringVar(value="")
        self.mask_menu = tk.OptionMenu(self.sel_box, self.mask_var, "")
        self.style_menu(self.mask_menu)
        self.mask_menu.pack(fill="x")
        self.mask_note = tk.Label(self.sel_box, text="", font=self.f_small, fg=WARN, bg=CARD, anchor="w", justify="left",
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
        # Lightroom's Amount: also after the reflection was found, nothing runs again (strength_done)
        self.strength.bind("<ButtonRelease-1>", lambda e: self.strength_done())
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
        # why it is not drawn there now: the app's view (update_buttons), or the photo itself (overlay_png)
        self.on_photo_note = tk.Label(body, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                      wraplength=self.width - 2 * pad)
        bottom = self.bottom = tk.Frame(body, bg=CARD)
        bottom.pack(fill="x", pady=(8, 0))
        # what Save writes when it is more than the selection shown: the photo's other removals (made for another
        # mask, in the window, or in an earlier session: its project)
        self.save_note = tk.Label(body, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                  wraplength=self.width - 2 * pad)
        self.save_btn = self.button(bottom, _("Save to {app}", app=self.host.name), self.save)
        self.save_btn.pack(side="left", fill="x", expand=True)
        self.del_btn = self.button(bottom, _("Delete removal"), self.discard, small=True)  # the selection's variants
        self.del_btn.pack(side="left", padx=(4, 0))
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
        return [m for m in TABS[mode][1] if m == "lama" or engines.usable(m)]

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
            last = A.setting("model_remove", "rorem")  # the window's too
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
        if mode == "reflect":  # the whole photo: no selection
            self.sel_box.pack_forget()
        elif not self.sel_box.winfo_manager():
            self.sel_box.pack(fill="x", after=self.tabs)
        self.refresh_masks()
        self.model_var.set(self.model_labels[cur] if cur else "")  # on_model_change: the text, the boxes
        self.sync_cur()  # each tab has its own variants

    def on_model_change(self):
        m = self.model_key()
        if self.picker.winfo_manager():
            self.picker.show()
            if m:
                A.remember("model_remove", m)
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
        return [(f"{m.get('name') or _('Mask {id}', id=m['id'])}  ·  {kind_of(m)}", m["id"]) for m in masks]

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
        if self.mode == "reflect":  # the whole photo
            return None
        return dict(self.mask_options()).get(self.mask_var.get())

    def update_buttons(self):
        ready = self.photo is not None and not self.busy
        has_mask = bool(self.mask_options())
        self.gen_btn.configure(state="normal" if ready and (has_mask or self.mode == "reflect") and self.model_key()
                               else "disabled")
        s = self.session_for(self.photo[0])[1] if self.photo else None
        live = self.chosen_removals(s)
        self.save_btn.configure(state="normal" if live and ready else "disabled",
                                text=_("Update in {app}", app=self.host.name) if s and s.dng_path else
                                _("Save to {app}", app=self.host.name))
        self.del_btn.configure(state="normal" if self.cur is not None and ready else "disabled")
        self.full_btn.configure(state="normal" if ready else "disabled")
        self.status_dot.configure(fg=ACCENT if self.busy else ("#4a9c63" if self.photo else DIM))
        # under the variants: the checkbox for the photo in the app, why it is not drawn there now, what Save writes
        n = len(live)
        not_drawn = self.overlay_problem or (None if self.photo is None or self.photo[4] else _(
            "It shows when {app} fits the whole photo in the view (not zoomed in, not cropping).", app=self.host.name))
        below = (bool(live), bool(live) and self.on_photo.get() and bool(not_drawn),
                 bool(n) and (self.cur is None or n > 1), n, not_drawn)
        if below != self._below:
            self._below = below
            self.on_photo_note.configure(text=not_drawn or "")
            self.save_note.configure(text=_n("Save writes {n} removal on this photo (the full window lists it).",
                                             "Save writes {n} removals on this photo (the full window lists them).",
                                             n))
            for w in (self.on_photo_chk, self.on_photo_note, self.save_note):
                w.pack_forget()
            for w, on in zip((self.on_photo_chk, self.on_photo_note, self.save_note), below):
                if on:
                    w.pack(fill="x", pady=(6, 0), before=self.bottom)

    @staticmethod
    def chosen_removals(s):
        """A Session's removals with a chosen variant: what its save writes, and what the photo in the app shows."""
        return [r for r in s.removals if not r.deleted and r.chosen is not None] if s is not None else []

    def session_for(self, pid):
        """(the photo's id here, its Session or None). A result saved from a Session (its DNG, which the app shows
        after a save) is that Session's photo too: what is made on it goes into the same DNG."""
        if pid in self.sessions:
            return pid, self.sessions[pid]
        for base, s in self.sessions.items():
            if s.dng_id is not None and s.dng_id == pid:
                return base, s
        return pid, None

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
            if t.minimized() or self.window is not None:  # the app minimized, or the full window open
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
            elif kind == "window":
                self.open_window(*data)
            elif kind == "overlay_problem":
                self.overlay_problem = data
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
        self.jobs.put(("generate", self.photo[0], self.chosen_mask_dict(), self.mode, model, prompt,
                       self.n_var.get(), self.strength.get() / 100))
        self.update_buttons()

    def save(self):
        s = self.session_for(self.photo[0])[1] if self.photo else None
        if self.busy or not self.chosen_removals(s):
            return
        self.busy = True
        self.overlays.put(None)  # the DNG shows the result itself
        self.jobs.put(("save", s))  # every removal with a chosen variant, as the photo showed them
        self.update_buttons()

    def discard(self):
        """The selection's variants go, as the window's "Delete removal": off the photo and out of the save."""
        if self.cur is None or self.busy:
            return
        key, s, r = self.cur
        r.deleted = True
        self.gens.pop(key, None)
        if s.dng_path:  # a result was saved: its project follows (variants never saved stay in memory only)
            threading.Thread(target=s.save_project, daemon=True).start()
        self.sync_cur()

    def worker(self):
        while True:
            job = self.jobs.get()
            try:
                if job[0] == "generate":
                    self.run_generate(*job[1:])
                elif job[0] == "save":
                    s = job[1]
                    label = _("Saving the DNG and stacking it in {app}…", app=self.host.name)
                    self.events.put(("job_start", (label, A.expected("save"))))
                    self.events.put(("job_part", (label, 0.0, A.expected("save"))))
                    out, nid, updated = s.write_all()
                    self.saved[s] = {r: (r.chosen, r.strength) for r in self.chosen_removals(s)}
                    self.events.put(("progress", (_("{file} updated in {app}", file=out.name, app=self.host.name)
                                                  if updated else
                                                  _("{file} created and stacked on the original in {app}",
                                                    file=out.name, app=self.host.name)) + " ✓"))
                elif job[0] == "window":
                    self.prepare_window(*job[1:])
            except A.Fail as e:
                self.events.put(("error", str(e)))
            except Exception as e:
                A.log("panel ERROR:", repr(e))
                import traceback
                A.log(traceback.format_exc())
                self.events.put(("error", f"{type(e).__name__}: {e}"))
            finally:
                self.events.put(("done", None))

    def run_generate(self, pid, mask, mode, model, prompt, n, strength):
        """Variants of `model` for the selection (a new removal of the photo's Session, or more for the selection's),
        with the window's progress plan: each part's expected seconds on this PC, the model's steps as they go
        (ui.App.run_job)."""
        base, s = self.session_for(pid)
        key = (base, mask["id"] if mask else None, mode)
        reflect, draw = mode == "reflect", mode == "fill"
        r = self.gens.get(key)  # more variants for a selection that has some
        if r is not None and r.deleted:
            r = None

        def variant_secs():  # a long removal's variants are filled in squares: known once its area is
            if r is not None:
                return s.variant_seconds(r, model)
            return A.expected("lama" if model == "lama" else f"{model}_variant")
        parts = []
        if s is None:  # the photo's first selection: its Session, the mask read with it
            parts.append(("read", _("Reading the photo and its mask from {app}…", app=self.host.name),
                          A.expected("panel_read")))
        elif r is None and mask is not None:  # another mask of a photo read already
            parts.append(("mask", _("Reading the mask from {app}…", app=self.host.name), A.expected("panel_mask")))
        if r is None:
            parts.append(("area", _("Preparing the area"), A.expected("reflection_area" if reflect else "area")))
        if model == "lama":  # one result
            if r is None or not any(c[0] == "LaMa" for c in r.candidates):
                parts.append(("lama", "LaMa", variant_secs()))
        else:
            if not (s.engine_loaded(model) if s is not None else self.loaded(model)):
                parts.append(("load", _("Loading {model}", model=A.MODELS[model]), A.expected(f"{model}_load")))
            n = 1 if reflect else n  # DAI: one result, at the strength set
            parts += [("variant", f"{A.MODELS[model]} {i + 1}/{n}", variant_secs()) for i in range(n)]
        self.events.put(("job_start", (parts[0][1] if parts else "", sum(p[2] for p in parts))))
        done, i, sel = 0.0, -1, None
        while i + 1 < len(parts):
            i += 1
            kind, label, secs = parts[i]
            self.events.put(("job_part", (label, done, secs)))
            if kind == "read":
                t0 = time.time()
                s = self.sessions[base] = self.read(pid, mask["id"] if mask else None)
                sel = s.init_mask
                A.measured("panel_read", time.time() - t0)
                r = self.gens.get(key)  # the photo's project had one for this mask: more variants for it
                if r is not None:
                    parts = [p for p in parts if p[0] != "area" and not (
                        p[0] == "lama" and any(c[0] == "LaMa" for c in r.candidates))]
                    parts[i + 1:] = [(k, lb, variant_secs() if k in ("lama", "variant") else sec)
                                     for k, lb, sec in parts[i + 1:]]
                    self.events.put(("job_total", done + secs + sum(p[2] for p in parts[i + 1:])))
                    self.events.put(("thumbs", key))
            elif kind == "mask":
                t0 = time.time()
                sel = A.mask_selection(self.lc, pid, mask, s.work, s.base.size)
                A.measured("panel_mask", time.time() - t0)
            elif kind == "area":
                if sel is None:
                    if not reflect:
                        raise A.Fail(_("The mask selects nothing AI Remove can read: choose another, or make an "
                                       "Object mask."))
                    sel = np.ones(s.base_arr.shape[:2], bool)
                r = s.new_removal(sel, reflection=reflect, draw=draw)
                r.mask_name = (mask or {}).get("name")  # not carried to the result
                self.gens[key] = r
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
        s.prepare()
        for attr, eng in self.engines.items():
            setattr(s, attr, eng)
        # a reopened project: a removal made here from a mask before is that mask's again (its name, in the project)
        names = {m.get("name"): m["id"] for m in s.info["develop"]["masks"] if m.get("name")}
        for r in s.removals:
            if not r.deleted and names.get(r.mask_name) is not None:
                self.gens.setdefault((pid, names[r.mask_name], tab_of(r.kind())), r)
        return s

    def loaded(self, model):
        """Whether an earlier photo's Session left `model`'s engine loaded (Session.engine_loaded, before a Session)."""
        spec = A.ENGINES.get(model)
        return bool(spec and spec.engine and A.ENGINE_ATTRS.get(spec.engine) in self.engines)

    # -------------------------------------------------------------- variants
    def current_key(self):
        """The selection now: the app's active photo (its original, for a result saved here), the mask, the tab."""
        return (self.session_for(self.photo[0])[0], self.chosen_mask(), self.mode) if self.photo else None

    def chosen_mask_dict(self):
        mid = self.chosen_mask()
        return next((m for m in (self.photo[2] if self.photo else []) if m["id"] == mid), None)

    def sync_cur(self):
        """The variants shown are the selection's now (photo, mask, tab), on the photo in the app too: another
        selection's stay in memory until the panel is closed, and come back with it."""
        key = self.current_key()
        s, r = (self.sessions.get(key[0]), self.gens.get(key)) if key else (None, None)
        cur = (key, s, r) if s is not None and r is not None and not r.deleted else None
        choose = _("Choose a variant, then save it to {app}.", app=self.host.name)
        if (cur and cur[0]) != (self.cur and self.cur[0]) and self.job is None:
            if cur is not None:
                self.msg = (choose, DIM)
            elif self.msg[0] == choose:  # nothing to choose for this selection ("Saved: …" stays)
                self.msg = ("", DIM)
            self.status.configure(text=self.msg[0], fg=self.msg[1])
        self.cur = cur
        if cur is not None and cur[2].reflects():  # its Amount
            self.strength.set(round(100 * cur[2].strength))
        self.show_thumbs()
        self.show_on_photo()
        self.update_buttons()

    def strength_done(self):
        """The strength let go: as Lightroom's Amount, how much of the reflection found goes — the variant and the
        photo in the app follow at once (Session.set_strength: nothing runs again)."""
        if self.cur is None or not self.cur[2].reflects() or not self.cur[2].candidates or self.busy:
            return
        __, s, r = self.cur
        s.set_strength(r, self.strength.get() / 100)
        self.show_thumbs()
        self.show_on_photo()

    def show_thumbs(self):
        for w in self.grid.winfo_children():
            w.destroy()
        self.grid.configure(height=1)  # emptied, a frame keeps its size: the thumbnails' room goes too
        self.thumbs = []
        if self.cur is None:
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
        """What Save would write, onto the photo in the app (overlay_worker): every removal of the photo's Session with
        a chosen variant — on a result saved already (its DNG), only those changed since. Else away from it."""
        s = self.session_for(self.photo[0])[1] if self.photo else None
        rs = self.chosen_removals(s)
        if rs and self.photo[0] == s.dng_id:
            done = self.saved.get(s, {})
            rs = [r for r in rs if done.get(r) != (r.chosen, r.strength)]
        # the photo whole in the view (whole_view), and the panel in sight: the full window shows the photo itself
        on = bool(rs) and self.on_photo.get() and self.photo[4] and self.window is None
        self.overlays.put((s, rs, self.photo[0]) if on else None)

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
            shown = tuple((id(r), r.chosen, r.strength) for r in want[1]) + (want[2],) if want else None
            if shown is not None and shown == self.overlay_shown and self.layout_before is not None:
                continue  # already on the photo (another mask clicked in the app, the same variants)
            try:
                path, problem = self.overlay_png(*want) if want else (None, None)
                if path and not self.closing:
                    self.put_layout(path)
                    self.overlay_shown = shown
                else:
                    self.take_layout()
                    self.overlay_shown = None
                if problem != self.overlay_problem:
                    self.events.put(("overlay_problem", problem))
            except Exception as e:
                A.log("panel on the photo:", repr(e))

    def overlay_png(self, s, rs, pid):
        """The removals' chosen variants as the app shows photo pid: transparent but where they change it (their
        blends, one over the other as Session.composite), as the app crops it, as a PNG in the Session's folder:
        (path, None), or (None, why) where the app's view cannot be matched — its Geometry (Upright, perspective,
        scale, offsets), which base.png is without. A lens profile is not undone in base.png either: near the edges of
        a wide lens a variant may sit a pixel or two off."""
        dev = self.lc.one("photo.inspect", {"id": pid})["develop"]
        crop, geo = dev["crop"], dev.get("geometry") or {}
        g = crop["geometry"]
        if any(geo.get(k, v) != v for k, v in A.NEUTRAL_GEOMETRY.items()):
            A.log("panel: not shown on the photo (its Geometry)")
            return None, _("Not shown on this photo: its Geometry (Upright, perspective…) moves it in {app}. Save "
                           "shows the result.", app=self.host.name)
        h, w = s.base_arr.shape[:2]
        rgb, alpha = np.zeros((h, w, 3), np.float32), np.zeros((h, w), np.float32)  # premultiplied
        for r in rs:
            patch, al = s.preview(r)
            y0, y1, x0, x1 = r.base_rect
            sub, sub_a = rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]
            ph, pw = sub_a.shape
            a = np.asarray(al, np.float32)[:ph, :pw]
            sub[:] = sub * (1 - a[..., None]) + patch[:ph, :pw].astype(np.float32) * a[..., None]
            sub_a[:] = sub_a * (1 - a) + a
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., :3] = np.clip(rgb / np.maximum(alpha, 1e-6)[..., None], 0, 255).astype(np.uint8)
        rgba[..., 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
        # the app's crop, as lightcraft-cli renders it (measured): the whole photo turned about its centre by the angle
        # (clockwise when positive) on the same canvas, the rect cut from that, then the flips
        im = Image.fromarray(rgba, "RGBA")
        if g.get("angle"):
            im = im.rotate(-g["angle"], resample=Image.BICUBIC)
        c = g["rect"]
        im = im.crop((round(c["x0"] * w), round(c["y0"] * h), round(c["x1"] * w), round(c["y1"] * h)))
        if crop.get("flip_h"):
            im = ImageOps.mirror(im)
        if crop.get("flip_v"):
            im = ImageOps.flip(im)
        self.overlay_n += 1
        path = s.work / f"on-photo-{self.overlay_n}.png"  # a new name each time: the app reads it again
        im.save(path)
        self.overlay_files.append(path)
        return path, None

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

    # -------------------------------------------------------------- the full window
    def full_window(self):
        """AI Remove's window on this photo, in this process: the panel's Session (the photo's removals and their
        variants, the models loaded), the selection shown, the tab, the model, its text and the number of variants.
        The panel steps aside until the window goes back to it (window_closed)."""
        if self.busy or not self.photo or self.window is not None:
            return
        self.busy = True
        self.jobs.put(("window", self.photo[0], self.chosen_mask_dict(), self.mode))
        self.update_buttons()

    def prepare_window(self, pid, mask, mode):
        """The worker's part: the photo's Session (read now if it has none) and, for a mask nothing was made of yet,
        its selection, which the window starts from."""
        base, s = self.session_for(pid)
        r = self.gens.get((base, mask["id"] if mask else None, mode))
        r = r if r is not None and not r.deleted else None
        sel, label = None, None
        if s is None:
            label, key = _("Reading the photo and its mask from {app}…", app=self.host.name), "panel_read"
        elif r is None and mask is not None:
            label, key = _("Reading the mask from {app}…", app=self.host.name), "panel_mask"
        if label:
            self.events.put(("job_start", (label, A.expected(key))))
            self.events.put(("job_part", (label, 0.0, A.expected(key))))
            t0 = time.time()
            if s is None:
                s = self.sessions[base] = self.read(pid, mask["id"] if mask else None)
                sel = s.init_mask
            else:
                sel = A.mask_selection(self.lc, pid, mask, s.work, s.base.size)
            A.measured(key, time.time() - t0)
        self.events.put(("window", (s, r, sel)))

    def open_window(self, s, r, sel):
        prompts = dict(self.prompt_text)
        if self.prompt_mode:
            prompts[self.prompt_mode] = self.prompt.get()
        start = {"removal": r, "selection": sel, "model": self.model_key(), "prompts": prompts,
                 "variants": self.n_var.get()}
        self.overlays.put(None)  # the window shows the photo itself
        self.root.withdraw()
        A.log(f"panel: the full window on {s.info.get('file_name')}")
        try:
            self.window = ui.App(s, s.args, master=self.root, on_close=self.window_closed, start=start)
        except Exception:
            import traceback
            A.log("panel ERROR (full window):", traceback.format_exc())
            self.window = None
            self.root.deiconify()

    def window_closed(self, app):
        """Back from the window: what was done there stays (the Session is the same), and the panel takes its tab, its
        model, its texts and its number of variants — and the selection it showed, if it is one of the panel's."""
        self.window = None
        s = app.s
        if not app.dng_dirty and s.dng_path:  # saved there and nothing changed since: its DNG has what is chosen
            self.saved[s] = {r: (r.chosen, r.strength) for r in self.chosen_removals(s)}
        key = next((k for k, x in self.gens.items() if x is app.cur), None)
        model = app.model_key()
        self.set_mode(key[2] if key else tab_of(A.model_kind(model)))
        if key and key[1] is not None:
            label = next((lb for lb, mid in self.mask_options() if mid == key[1]), None)
            if label:
                self.mask_var.set(label)
        if model in self.models_for(self.mode):
            self.model_var.set(self.model_labels[model])
        prompts = dict(app.prompt_text)
        if app.prompt_mode:
            prompts[app.prompt_mode] = app.prompt.get()
        self.prompt_text.update(prompts)
        if self.prompt_mode:
            self.prompt.set_text(self.prompt_text.get(self.prompt_mode, ""))
        self.set_n(min(4, max(1, int(app.count.get()))))
        self.engines = {a: getattr(s, a) for a in A.ENGINE_ATTRS.values() if getattr(s, a, None) is not None}
        A.log("panel: back from the full window")
        self.root.deiconify()
        self.sync_cur()

    # -------------------------------------------------------------- the rest

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
        elif kind == "full":  # "Full window"
            self.full_window()
        elif kind == "window":  # until the window shows the photo (or, "window:closed", until it went back)
            w = self.window
            if (w is None or not getattr(w, "base_ok", False)) if arg != "closed" else w is not None:
                self.root.after(500, lambda: self.test(steps))
                return
            delay = 1500
        elif kind == "wshot":  # the window, from the screen
            from PIL import ImageGrab
            w = self.window.root
            w.attributes("-topmost", True)
            w.update()
            time.sleep(0.5)
            x, y = w.winfo_rootx(), w.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height()), all_screens=True).save(
                system.ROOT / "work" / f"window-shot-{arg}.png")
            w.attributes("-topmost", False)
        elif kind == "wtab":  # a tab of the window
            self.window.set_tab(arg)
        elif kind == "wback":  # the window's "Back to the panel"
            self.window.cancel()
        elif kind == "discard":
            self.discard()
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
