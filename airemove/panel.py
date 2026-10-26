"""AI Remove as a small panel next to LightCraft's (or Chromaforge's) window (airemove --panel): the floating view of
the tool whose full view is AI Remove's window. docs/design/AI Remove - workflows.figcraft draws both, every state of
Remove, Fill and Reflections, and the ways between them; they share one order, the same words, controls and keys.

LightCraft has no plug-in panels, so, as OpenFill does next to PhotoCraft (beckettharriman/openfill, Apache-2.0:
photocraft/openfill_photocraft/tether.py), the panel is a window of its own that Windows makes an "owned" window of
the app's: it stays above the app (and only above it), hides when the app is minimized, and follows it when it moves.
It starts docked at the app's right edge; dragged by its header it stays where it was let go, from the app window's
top-left (it moves with the app and opens there next time), and a double-click on the header docks it again.
Elsewhere it is an ordinary window beside it. Taller than the room the app leaves, it scrolls.

Everything else goes through the app's control channel, as AI Remove's window does:
- the app's active photo and its masks are watched; the mask selected in the app (or chosen here) is the selection
  (a SAM 3 Object or Describe mask is read from the develop settings, a brush or gradient one rendered:
  airemove.extract, airemove.mask_selection); Reflections takes the whole photo, as Lightroom's Remove Reflections;
- the window's tabs (ui.TABS), model menu (ModelPicker) and "What it does", the text field only for a model that reads
  one, the variants − N +, the action ("＋ N more for #id" once the selection has variants), the progress bar with
  Stop; the variants as the window's tiles (right-click: delete one), a reflection's strength under them (Lightroom's
  Amount, also afterwards), the photo's removals as the window's list;
- one Session per photo, as in the window, with one removal per selection (mask, tab), kept until the panel is
  closed (and found again in the photo's project, by its mask's name, once saved). Every removal with a chosen
  variant shows on the photo in the app, as its Layout Image (a PNG it draws over the photo, fitted to it: only while
  the photo is shown whole, at Fit; ◐ Original or the backslash key, held, takes it away), and that is what Save
  writes into the DNG,
  stacked on the original — without the masks that were the selections. After a save the app shows the DNG: it is the
  same photo here, and the next save updates it;
- "Full window" opens AI Remove's window in this process on the same Session (ui.App with master / on_close /
  start): the removals and variants, the removal shown, the tab, the model, the texts; "Back to the panel" brings them
  back, and the window, kept hidden, reopens at once the next time.
The panel stays open from one photo to the next, and the models stay loaded: only the first variant pays their load.
Keys, as in the window: Enter the action, Esc Stop, ← → the variants, the backslash (held) the original.

Tests: AIREMOVE_PANEL_TEST runs steps separated by ";": wait:ms · mode:remove|fill|reflect · model:key ·
mask:<name> · prompt:<text> · variants:n · generate · waitvars:n · pick:i · step:±1 · list:<id> · original:0|1 ·
info · stop · split · save · waitidle · drag:dx,dy · dock · menu[:close] · discard · full · window[:closed] · wshot:n ·
wtab:<tab> · wback · shot:n · pshot:n · quit."""
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
from ui import (ACCENT, ACCENT_HI, BG, BTN, BTN_HI, CARD, CARD_HI, DIM, FG, GREEN, GREEN_HI, LINE, MODEL_NAMES, OFF,
                PROMPT_MODE, SIDE, TABS, WARN, HintEntry, ModelPicker, Stepper, model_infos, model_meta, tab_of,
                tile_image)

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
        self.photo = None  # (pid, file name, masks, the mask selected, shown whole) of the app's active photo
        # one Session per photo, as in the window: the photo's removals (its project, its DNG), one per selection made
        # here — (photo, mask, tab) -> Removal — kept until the panel is closed. The ones shown are the selection's now
        # (sync_cur); Save writes every removal with a chosen variant, as the photo in the app shows them
        self.sessions, self.gens = {}, {}
        self.cur = None  # (key or None, Session, Removal) shown: the selection's, or one chosen in the photo's list
        self.list_pick = None  # a removal chosen in the photo's list that no selection here made (the window's)
        self.saved = {}  # Session -> what its last save wrote, {Removal: (variant, strength)}: its DNG has those
        self.window_app = None  # AI Remove's window, kept hidden after it went back: it reopens at once
        self.window = None  # it, while it is open (full_window)
        self.engines = {}  # Session attribute -> engine, kept loaded from one photo's Session to the next
        self.busy = False
        self.job, self.task = None, ""  # the generation's progress plan (the window's update_progress)
        self.msg = ("", DIM)  # what the status line says once nothing is running
        self.thumbs, self.row_photos = [], []
        self._shown = None  # which parts of the panel are packed (layout)
        # the chosen variants drawn on the photo in the app, as its Layout Image (a PNG over the photo, fitted to it):
        # what the app's own setting was before (put back when it is taken away), its files
        self.overlays = queue.Queue()
        self.layout_before, self.overlay_files, self.overlay_n = None, [], 0
        self.overlay_shown = None  # what is on the photo now
        self.overlay_problem = None  # why the variants cannot be drawn on this photo (overlay_png), said under them
        self.original_held = False  # ◐ Original (or \) held: the photo in the app as it is
        self.view_px = None  # the photo's size in the app's view, in pixels: the preview's (whole_view)
        self.closing = False
        self.mode = "remove"
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
        self.f_head = (self.f_txt[0], self.f_txt[1] - 2, "bold")
        self.width = int(WIDTH * k)
        self.side_w = self.width + int(30 * k)  # ModelPicker's caveat wraps at side_w - 90 (the window's side panel)
        self.on_photo = tk.BooleanVar(value=bool(A.setting("panel_on_photo", True)))
        self.show_info = bool(A.setting("model_info", False))  # "What it does", open or not: the window's too
        self.tether = Tether(self.host.exe + ".exe")
        if self.tether.find():
            r.overrideredirect(True)  # docked: its own header, no frame
        self.build()
        self.bind_keys()
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

    # -------------------------------------------------------------- layout: the design file's order, the window's words
    def button(self, master, text, cmd, accent=False, small=False, green=False):
        bg, fg = (ACCENT, "#1b1b1b") if accent else (GREEN, "#ffffff") if green else (BTN, FG)
        return tk.Button(master, text=text, command=cmd, relief="flat", bd=0, cursor="hand2",
                         font=self.f_bold if accent or green else (self.f_small if small else self.f_txt),
                         bg=bg, fg=fg, activebackground=ACCENT_HI if accent else GREEN_HI if green else BTN_HI,
                         activeforeground=fg, disabledforeground=OFF, padx=int(8 * self.k),
                         pady=int((4 if small else 6) * self.k))

    def head(self, master, text, right=None, command=None):
        """A part's title, as the window's sections: small capitals; on its right a note or a link."""
        row = tk.Frame(master, bg=CARD)
        row.pack(fill="x", pady=(int(9 * self.k), int(3 * self.k)))
        lbl = tk.Label(row, text=text.upper(), font=self.f_head, fg=DIM, bg=CARD, anchor="w")
        lbl.pack(side="left")
        extra = None
        if right is not None:
            extra = tk.Label(row, text=right, font=self.f_small, fg=DIM, bg=CARD, cursor="hand2" if command else "")
            extra.pack(side="right")
            if command:
                extra.bind("<Button-1>", lambda e: command())
        return lbl, extra

    def build(self):
        k, r = self.k, self.root
        pad = int(10 * k)
        st = ttk.Style(r)
        st.theme_use("clam")
        st.configure("AI.Horizontal.TProgressbar", troughcolor=BTN, background=ACCENT, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT, thickness=max(3, int(4 * k)))
        st.configure("AI.Horizontal.TScale", troughcolor="#3a3a3a", background=ACCENT, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT, gripcount=0)
        st.configure("AI.Vertical.TScrollbar", troughcolor=CARD, background="#3a3a3a", bordercolor=CARD,
                     arrowcolor=DIM, lightcolor="#3a3a3a", darkcolor="#3a3a3a", gripcount=0, arrowsize=int(9 * k))
        outer = tk.Frame(r, bg=LINE)
        outer.pack(fill="both", expand=True)
        box = self.box = tk.Frame(outer, bg=CARD)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        # the header: the panel moves by it, a double-click docks it again; the photo it works on
        head = self.header = tk.Frame(box, bg=CARD, cursor="fleur")
        head.pack(fill="x", padx=pad, pady=(pad, int(6 * k)))
        title = tk.Label(head, text="AI Remove", font=self.f_bold, fg=ACCENT, bg=CARD, cursor="fleur")
        title.pack(side="left")
        self.status_dot = tk.Label(head, text="●", font=self.f_small, fg=DIM, bg=CARD, cursor="fleur")
        self.status_dot.pack(side="left", padx=(int(5 * k), 0))
        self.photo_lbl = tk.Label(head, text=_("Waiting for {app}…", app=self.host.name), font=self.f_small, fg=DIM,
                                  bg=CARD, cursor="fleur")
        self.photo_lbl.pack(side="left", padx=(int(6 * k), 0))
        for w in (head, title, self.status_dot, self.photo_lbl):
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_move)
            w.bind("<ButtonRelease-1>", self.drag_end)
            w.bind("<Double-Button-1>", self.dock)
        self.button(head, "×", self.close, small=True).pack(side="right")
        self.fold_btn = self.button(head, "–", self.fold, small=True)
        self.fold_btn.pack(side="right", padx=(0, int(4 * k)))
        # the rest scrolls when it is taller than the app's window leaves room for
        self.scroller = ui.Panel(box, k, CARD)
        self.scroller.pack(fill="both", expand=True)
        body = self.body = tk.Frame(self.scroller.inner, bg=CARD)
        body.pack(fill="x", padx=pad, pady=(0, pad))
        wrap = self.width - 2 * pad - 4

        # 1 · the tabs
        self.tabs = tk.Frame(body, bg=LINE)
        self.tab_btns = {}
        for i, (mode, (title_, __)) in enumerate(TABS.items()):
            b = self.button(self.tabs, _(title_), lambda m=mode: self.set_mode(m))
            b.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 1, 0))
            self.tabs.columnconfigure(i, weight=1)
            self.tab_btns[mode] = b
        # 2 · the selection: one of the photo's masks in the app — or, in Reflections, the whole photo
        self.sel_box = tk.Frame(body, bg=CARD)
        self.head(self.sel_box, _("Selection"), _("Follows the mask selected in {app}", app=self.host.name))
        self.mask_var = tk.StringVar(value="")
        self.mask_menu = tk.OptionMenu(self.sel_box, self.mask_var, "")
        self.style_menu(self.mask_menu)
        self.mask_menu.pack(fill="x")
        self.mask_note = tk.Label(self.sel_box, text="", font=self.f_small, fg=WARN, bg=CARD, anchor="w",
                                  justify="left", wraplength=wrap)
        self.whole_box = tk.Frame(body, bg=CARD)
        self.head(self.whole_box, _("Selection"))
        tk.Label(self.whole_box, text=_("Whole photo  ·  as Lightroom's Remove Reflections"), font=self.f_small, fg=FG,
                 bg=SIDE, anchor="w", padx=int(8 * k), pady=int(5 * k)).pack(fill="x")
        # 3 · the model: the window's menu where there is a choice (Remove), else its one model on a line; what it does
        self.model_box = tk.Frame(body, bg=CARD)
        __, self.info_btn = self.head(self.model_box, _("Model"), "", self.toggle_info)
        self.model_var = tk.StringVar(value="")
        self.model_labels = {}
        self.picker = ModelPicker(self.model_box, self, self.model_var)
        self.model_line = tk.Label(self.model_box, text="", font=self.f_small, fg=FG, bg=SIDE, anchor="w",
                                   padx=int(8 * k), pady=int(5 * k))
        self.info_lbl = tk.Label(self.model_box, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w",
                                 justify="left", wraplength=wrap)
        # 4 · the text, only for a model that reads one (PROMPT_MODE); each kind kept apart, as in the window
        self.prompt_box = tk.Frame(body, bg=CARD)
        self.prompt_lbl, __ = self.head(self.prompt_box, "")
        self.prompt = HintEntry(self.prompt_box, "", font=self.f_txt, bg=BTN, fg=FG, insertbackground=FG,
                                relief="flat", highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        self.prompt.pack(fill="x", ipady=int(4 * k))
        self.prompt_mode, self.prompt_text = None, {}
        # 5 · how many variants (not LaMa, not DAI: one result each), − N +, the window's: one remembered value
        self.n_box = tk.Frame(body, bg=CARD)
        row = tk.Frame(self.n_box, bg=CARD)
        row.pack(fill="x", pady=(int(9 * k), 0))
        tk.Label(row, text=_("Variants").upper(), font=self.f_head, fg=DIM, bg=CARD).pack(side="left")
        self.count = Stepper(row, int(A.setting("variants", 2)), 1, 8, self,
                             on_change=lambda: (A.remember("variants", int(self.count.get())), self.update_buttons()))
        self.count.configure(bg=CARD)
        self.count.pack(side="right")
        # 6 · the action; in Remove, a mask with nothing made of it yet can first be split, in the app, into one mask
        # per part (the window's "Split into parts", for the app's masks): each a selection here, with its own model
        self.gen_btn = self.button(body, "", self.generate, accent=True)
        self.split_btn = self.button(body, "✂  " + _("Split into masks in {app}: one per part", app=self.host.name),
                                     self.split_masks, small=True)
        # 7 · progress: one bar for the whole job, what it does, Stop (Esc)
        self.prog_box = tk.Frame(body, bg=CARD)
        self.bar = ttk.Progressbar(self.prog_box, mode="determinate", maximum=1000, value=0,
                                   style="AI.Horizontal.TProgressbar")
        srow = tk.Frame(self.prog_box, bg=CARD)
        srow.pack(fill="x", pady=(int(5 * k), 0), side="bottom")
        self.stop_btn = self.button(srow, "■  " + _("Stop") + "  (Esc)", self.stop_jobs, small=True)
        self.status = tk.Label(srow, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                               wraplength=wrap - int(80 * k))
        self.status.pack(side="left", fill="x", expand=True)
        # 8 · the variants of the removal shown (the window's tiles), a reflection's strength under them
        self.var_box = tk.Frame(body, bg=CARD)
        self.var_title, __ = self.head(self.var_box, "")
        self.grid = tk.Frame(self.var_box, bg=CARD)
        self.grid.pack(fill="x")
        self.var_note = tk.Label(self.var_box, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w",
                                 justify="left", wraplength=wrap)
        self.str_row = tk.Frame(self.var_box, bg=CARD)
        srow = tk.Frame(self.str_row, bg=CARD)
        srow.pack(fill="x", pady=(int(8 * k), int(2 * k)))
        tk.Label(srow, text=_("Strength").upper(), font=self.f_head, fg=DIM, bg=CARD).pack(side="left")
        self.str_lbl = tk.Label(srow, text="", font=self.f_small, fg=FG, bg=CARD)
        self.str_lbl.pack(side="right")
        self.str_scale = ttk.Scale(self.str_row, from_=0, to=round(100 * engines.mf.REFLECTION_MAX),
                                   orient="horizontal", style="AI.Horizontal.TScale", command=self.on_strength)
        self.str_scale.pack(fill="x")
        self.str_scale.bind("<ButtonRelease-1>", lambda e: self.strength_done())
        self._str_busy = False
        # 9 · on the photo in the app (its Layout Image), and the original while held
        self.photo_box = tk.Frame(body, bg=CARD)
        prow = tk.Frame(self.photo_box, bg=CARD)
        prow.pack(fill="x", pady=(int(8 * k), 0))
        self.on_photo_chk = tk.Checkbutton(prow, text=_("On the photo in {app}", app=self.host.name),
                                           variable=self.on_photo, command=self.on_photo_toggled, font=self.f_small,
                                           bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                                           selectcolor=BTN, highlightthickness=0, bd=0, anchor="w", cursor="hand2",
                                           wraplength=wrap - int(90 * k), justify="left")
        self.on_photo_chk.pack(side="left", fill="x", expand=True)
        self.orig_btn = self.button(prow, "◐  " + _("Original"), None, small=True)
        self.orig_btn.pack(side="right")
        self.orig_btn.bind("<ButtonPress-1>", lambda e: self.hold_original(True))
        self.orig_btn.bind("<ButtonRelease-1>", lambda e: self.hold_original(False))
        # why it is not drawn there now: the app's view (update_buttons), or the photo itself (overlay_png)
        self.on_photo_note = tk.Label(self.photo_box, text="", font=self.f_small, fg=WARN, bg=CARD, anchor="w",
                                      justify="left", wraplength=wrap)
        # 10 · the photo's removals: what Save writes, the window's list
        self.list_box = tk.Frame(body, bg=CARD)
        self.head(self.list_box, _("On this photo"))
        self.list_rows = tk.Frame(self.list_box, bg=CARD)
        self.list_rows.pack(fill="x")
        # 11 · save, delete the removal shown, the full window
        self.bottom = tk.Frame(body, bg=CARD)
        self.save_btn = self.button(self.bottom, _("Save to {app}", app=self.host.name), self.save, green=True)
        self.save_btn.pack(side="left", fill="x", expand=True)
        self.del_btn = self.button(self.bottom, _("Delete removal"), self.discard, small=True)
        self.del_btn.pack(side="left", padx=(int(4 * k), 0))
        self.full_btn = self.button(self.bottom, _("Full window"), self.full_window, small=True)
        self.full_btn.pack(side="left", padx=(int(4 * k), 0))
        self.parts = [(self.tabs, {}), (self.sel_box, {}), (self.whole_box, {}), (self.model_box, {}),
                      (self.prompt_box, {}), (self.n_box, {}), (self.gen_btn, {"pady": (int(12 * k), 0)}),
                      (self.split_btn, {"pady": (int(5 * k), 0)}),
                      (self.prog_box, {"pady": (int(6 * k), 0)}), (self.var_box, {}), (self.photo_box, {}),
                      (self.list_box, {}), (self.bottom, {"pady": (int(12 * k), 0)})]
        self.model_var.trace_add("write", lambda *a: self.on_model_change())  # also when set by code
        self.mask_var.trace_add("write", lambda *a: self.selection_changed())  # another selection: its own variants
        self.set_mode("remove")

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

    def layout(self):
        """The parts that make sense now, packed in the file's order (only when that changes: no flicker)."""
        r = self.cur[2] if self.cur else None
        s = self.session_for(self.photo[0])[1] if self.photo else None
        working = self.job is not None or bool(self.status.cget("text"))  # the bar, or something to say
        splits = self.mode == "remove" and self.chosen_mask() is not None and r is None
        shown = (True, self.mode != "reflect", self.mode == "reflect", True, self.prompt_mode is not None,
                 self.model_key() not in ("lama", "dai"), True, splits, working, r is not None,
                 bool(self.chosen_removals(s)), bool(s and any(not x.deleted for x in s.removals)), True)
        if shown == self._shown:
            return
        self._shown = shown
        for w, __ in self.parts:
            w.pack_forget()
        for (w, kw), on in zip(self.parts, shown):
            if on:
                w.pack(fill="x", **kw)

    def bind_keys(self):
        """The window's keys: Enter the action, Esc Stop, ← → the variants, \\ held the original."""
        r = self.root
        r.bind("<Return>", lambda e: self.generate())
        r.bind("<Escape>", lambda e: self.stop_jobs())
        r.bind("<Left>", lambda e: None if self.typing() else self.step_variant(-1))
        r.bind("<Right>", lambda e: None if self.typing() else self.step_variant(1))
        r.bind("<KeyPress-backslash>", lambda e: None if self.typing() else self.hold_original(True))
        r.bind("<KeyRelease-backslash>", lambda e: self.hold_original(False))
        self.bind_wheel()

    def bind_wheel(self):
        """The wheel scrolls the panel when it is taller than its room (again after the window, which binds its own)."""
        self.root.bind_all("<MouseWheel>", self.on_wheel)

    def on_wheel(self, e):
        c = self.scroller.canvas
        if self.scroller.scrolls:
            c.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def typing(self):
        return self.root.focus_get() is self.prompt

    # -------------------------------------------------------------- modes and choices
    def models_for(self, mode):
        return [m for m in TABS[mode][1] if m == "lama" or engines.usable(m)]

    def set_mode(self, mode):
        self.mode, self.list_pick = mode, None
        for m, b in self.tab_btns.items():
            b.configure(bg=ACCENT if m == mode else BTN, fg="#1b1b1b" if m == mode else FG,
                        activebackground=ACCENT if m == mode else BTN_HI)
        models = self.models_for(mode)
        meta = model_meta()  # its times from this PC's last runs: read again at each change of tab
        self.model_labels = {m: f"{n} · {u} · {t}" for m, (n, u, t) in meta.items()}
        if len(models) > 1:  # Remove: the menu, on the model chosen last time (RORem at first)
            last = A.setting("model_remove", "rorem")  # the window's too
            cur = last if last in models else ("rorem" if "rorem" in models else models[0])
            self.picker.set_models(meta, models)
            self.model_line.pack_forget()
            self.picker.pack(fill="x", **self.before_info())
        else:
            cur = models[0] if models else None
            name, __, t = meta.get(cur, ("", "", ""))
            self.model_line.configure(text=f"{name}  ·  {t}" if cur else _("Not available on this computer"))
            self.picker.pack_forget()
            self.model_line.pack(fill="x", **self.before_info())
        self.refresh_masks()
        self.model_var.set(self.model_labels[cur] if cur else "")  # on_model_change: the text, the info
        self.sync_cur()  # each tab has its own variants

    def before_info(self):
        return {"before": self.info_lbl} if self.info_lbl.winfo_manager() else {}

    def on_model_change(self):
        m = self.model_key()
        if self.picker.winfo_manager():
            self.picker.show()
            if m:
                A.remember("model_remove", m)
        self.apply_prompt_mode()
        self.show_model_info()
        self.update_buttons()

    def model_key(self):
        return next((m for m, label in self.model_labels.items() if label == self.model_var.get()), None)

    def toggle_info(self):
        self.show_info = not self.show_info
        A.remember("model_info", self.show_info)
        self.show_model_info()

    def show_model_info(self):
        """"What it does": the window's description of the model, under it, open or closed as in the window."""
        m = self.model_key()
        self.info_btn.configure(text="ⓘ  " + (_("Hide") if self.show_info else _("What it does")))
        if self.show_info and m:
            self.info_lbl.configure(text=model_infos()[m])
            self.info_lbl.pack(fill="x", pady=(int(5 * self.k), 0))
        else:
            self.info_lbl.pack_forget()

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
            self.prompt_lbl.configure(text=_(label).upper())
            self.prompt.set_hint(_(hint))

    def n_variants(self):
        return max(1, min(8, int(self.count.get())))

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
            self.mask_note.pack(fill="x", pady=(int(4 * self.k), 0), after=self.mask_menu)
        else:
            self.mask_note.pack_forget()

    def chosen_mask(self):
        if self.mode == "reflect":  # the whole photo
            return None
        return dict(self.mask_options()).get(self.mask_var.get())

    def chosen_mask_dict(self):
        mid = self.chosen_mask()
        return next((m for m in (self.photo[2] if self.photo else []) if m["id"] == mid), None)

    def selection_changed(self):
        self.list_pick = None
        self.sync_cur()

    def action(self):
        """The action's words and whether it can run: the tab's ("Remove selection"…), or, for a selection that has
        variants, more of them — the window's "＋ N more for #id with <model>"."""
        r, m = (self.cur[2] if self.cur else None), self.model_key()
        if r is not None and r.candidates and m:
            if self.mode == "reflect":  # one result per photo: its strength is what changes
                return _("Remove reflections") + "  ⏎", False
            if m == "lama" and any(c[0] == "LaMa" for c in r.candidates):
                return _("#{id} has LaMa's result already: choose another model", id=r.id), False
            n = 1 if m == "lama" else self.n_variants()
            return "＋  " + _n("{n} more for #{id} with {model}", "{n} more for #{id} with {model}", n, id=r.id,
                               model=_(MODEL_NAMES[m])) + "  ⏎", True
        return {"remove": _("Remove selection"), "fill": _("Draw in the selection"),
                "reflect": _("Remove reflections")}[self.mode] + "  ⏎", True

    def update_buttons(self):
        ready = self.photo is not None and not self.busy
        text, can = self.action()
        listed = self.cur is not None and self.cur[0] is None  # chosen in the list: more for it, no mask needed
        has_sel = bool(self.mask_options()) or self.mode == "reflect" or listed
        on = bool(ready and has_sel and self.model_key() and can)
        # off, the accent and green buttons are grey, as the window's (FlatButton): never dimmed text on a colour
        self.gen_btn.configure(text=text, state="normal" if on else "disabled", bg=ACCENT if on else BTN)
        s = self.session_for(self.photo[0])[1] if self.photo else None
        live = self.chosen_removals(s)
        on = bool(live and ready)
        self.save_btn.configure(state="normal" if on else "disabled", bg=GREEN if on else BTN,
                                text=_("Update in {app}", app=self.host.name) if s and s.dng_path else
                                _("Save to {app}", app=self.host.name))
        self.del_btn.configure(state="normal" if self.cur is not None and ready else "disabled")
        self.split_btn.configure(state="normal" if ready else "disabled")
        self.full_btn.configure(state="normal" if ready else "disabled")
        self.status_dot.configure(fg=ACCENT if self.busy else ("#4a9c63" if self.photo else DIM))
        if self.busy and not self.stop_btn.winfo_manager():
            self.stop_btn.pack(side="right")
        elif not self.busy:
            self.stop_btn.pack_forget()
        # why the variants are not on the photo in the app now: the photo itself, or how the app shows it
        not_drawn = self.overlay_problem or (None if self.photo is None or self.photo[4] else _(
            "It shows when {app} fits the whole photo in the view (not zoomed in, not cropping).", app=self.host.name))
        if live and self.on_photo.get() and not_drawn:
            self.on_photo_note.configure(text=not_drawn)
            if not self.on_photo_note.winfo_manager():
                self.on_photo_note.pack(fill="x", pady=(int(4 * self.k), 0))
        else:
            self.on_photo_note.pack_forget()
        self.layout()

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
        right edge under its title bar; as tall as its content, up to the room the app's window leaves (then it
        scrolls); hidden while the app is minimized or the full window is open."""
        t = self.tether
        if t.hwnd and not t.alive():
            t.find()
            if t.hwnd:
                t.own(self.root_hwnd())
        if t.hwnd and self._drag is None:
            if t.minimized() or self.window is not None:
                self.root.withdraw()
            else:
                left, top, right, bottom = t.rect()
                want = (self.header.winfo_reqheight() + int(16 * self.k)
                        + (self.body.winfo_reqheight() + int(12 * self.k) if self.scroller.winfo_manager() else 0))
                if self.offset:
                    # never lost: at least its header stays over the app's window
                    x = min(max(left + self.offset[0], left - self.width + int(80 * self.k)), right - int(80 * self.k))
                    y = min(max(top + self.offset[1], top), bottom - int(40 * self.k))
                else:
                    x, y = right - self.width - int(24 * self.k), top + int(96 * self.k)
                h = max(int(120 * self.k), min(want, bottom - y - int(24 * self.k)))
                geo = f"{self.width}x{h}+{x}+{y}"
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                if self.root.geometry() != geo:
                    self.root.geometry(geo)
        elif not t.hwnd and not getattr(self, "_placed", False):
            self.root.geometry(f"{self.width}x{max(self.root.winfo_reqheight(), 600)}")
            self._placed = True
        self.root.after(250, self.follow)

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
        before/after): its Layout Image then lies on the photo. Zoomed in, it stays fitted to the view instead. The
        photo's size there is the preview's (no need to draw it bigger than it is shown)."""
        try:
            u = self.lc.call("ui.inspect")
        except A.Fail:
            return True  # an app without ui.inspect: as at Fit
        ui_ = u.get("ui") or {}
        rect, ppp = u.get("imageRect"), u.get("pixelsPerPoint") or 1
        if rect and len(rect) == 4 and rect[2] > 0:
            self.view_px = (round(rect[2] * ppp), round(rect[3] * ppp))
        return (ui_.get("view", "detail") == "detail" and ui_.get("zoom", "fit") == "fit"
                and ui_.get("right") != "crop" and ui_.get("beforeAfter", "off") == "off")

    def pump(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "photo":
                if (data and data[0]) != (self.photo and self.photo[0]):
                    self.list_pick = None  # another photo: its own removals
                self.photo = data
                name = data[1] if data else _("No active photo in {app}", app=self.host.name)
                self.photo_lbl.configure(text=name if len(name) <= 30 else name[:13] + "…" + name[-14:])
                self.refresh_masks()
                if data and data[3] is not None:  # the mask selected in the app becomes the selection here
                    label = next((lb for lb, mid in self.mask_options() if mid == data[3]), None)
                    if label:
                        self.mask_var.set(label)
                self.sync_cur()  # another photo or mask: its own variants, on the photo too
            elif kind == "down":
                self.photo = None
                self.photo_lbl.configure(text=data[:40])
                self.status.configure(text=data, fg=WARN)
            elif kind in ("progress", "error"):
                self.msg = (data, WARN if kind == "error" else DIM)
                if self.job is None:
                    self.status.configure(text=data, fg=self.msg[1])
            elif kind == "job_start":
                label, total = data
                now = time.time()
                self.job = {"label": label, "total": total, "t0": now, "mode": "timed", "base": 0.0, "secs": 1.0,
                            "t_part": now, "exact": 0.0}
                self.bar.pack(fill="x", side="top")
            elif kind == "job_total":
                self.on_job_total(data)
            elif kind == "job_part":
                self.on_job_part(data)
            elif kind == "job_exact":
                self.on_job_exact(data)
            elif kind == "thumbs":  # new variants, a new removal: what is shown follows
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
                self.sync_cur()
            self.update_buttons()
        if self.job is not None:
            self.update_progress()  # the window's: the bar and "what · 42% · ~12 s"
        self.scroller.fit()  # the content's height may have changed
        self.root.after(100, self.pump)

    # -------------------------------------------------------------- generating
    def generate(self):
        if self.busy or not self.photo or str(self.gen_btn["state"]) != "normal":
            return
        model = self.model_key()
        prompt = self.prompt.get().strip() if self.prompt_mode else ""  # a model that reads no text gets none
        if self.prompt_mode == "draw" and not prompt:
            self.status.configure(text=_("Write what to draw first, in English (e.g. a wooden bench)."), fg=WARN)
            self.prompt.focus_set()
            return
        target = self.cur[2] if self.cur is not None and self.cur[0] is None else None  # chosen in the list
        self.busy = True
        self.jobs.put(("generate", self.photo[0], self.chosen_mask_dict(), self.mode, model, prompt,
                       self.n_variants(), target))
        self.update_buttons()

    def split_masks(self):
        """"Split into masks": the mask chosen, replaced in the app by one Object mask per part (run_split)."""
        mask = self.chosen_mask_dict()
        if self.busy or not self.photo or mask is None:
            return
        self.busy = True
        self.jobs.put(("split", self.photo[0], mask))
        self.update_buttons()

    def run_split(self, pid, mask):
        """The worker's part: the mask's selection (the photo read first if it was not), its parts as the window splits
        a selection (airemove.split_selection; a mask of several Object clicks: along them), then the app's masks
        (airemove.split_into_masks). One part: nothing changes, and the panel says so."""
        base, s = self.session_for(pid)
        label = _("Splitting the selection")
        self.events.put(("job_start", (label, 2.0 + (A.expected("panel_read") if s is None else
                                                      A.expected("panel_mask")))))
        self.events.put(("job_part", (label, 0.0, 2.0)))
        if s is None:
            s = self.sessions[base] = self.read(pid, mask["id"])
            sel = s.init_mask
        else:
            sel = A.mask_selection(self.lc, pid, mask, s.work, s.base.size)
        if sel is None:
            raise A.Fail(_("The mask selects nothing AI Remove can read: choose another, or make an Object mask."))
        h, w = sel.shape
        parts = A.split_selection(sel, s.base_scale, units=A.mask_units(mask, w, h))
        name = mask.get("name") or _("Mask {id}", id=mask["id"])
        if len(parts) < 2:
            self.events.put(("progress", _("{name} is one part: nothing to split", name=name)))
            return
        A.split_into_masks(self.lc, pid, mask, parts)
        self.events.put(("progress", _("{name} split into {n} masks in {app}: each one a selection here, with its own "
                                       "model", name=name, n=len(parts), app=self.host.name)))

    def stop_jobs(self):
        """Stop (Esc), as in the window: what runs ends at its next step, the variants made stay; what waits goes
        (but a save)."""
        if not self.busy:
            return
        kept = []
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            if job[0] == "save":
                kept.append(job)
        for job in kept:
            self.jobs.put(job)
        for s in self.sessions.values():
            s.stop.set()
        if self.job:
            self.job["label"] = _("Stopping…")
        A.log("panel: stop pressed")

    def save(self):
        s = self.session_for(self.photo[0])[1] if self.photo else None
        if self.busy or not self.chosen_removals(s):
            return
        self.busy = True
        self.overlays.put(None)  # the DNG shows the result itself
        self.jobs.put(("save", s))  # every removal with a chosen variant, as the photo showed them
        self.update_buttons()

    def discard(self):
        """The removal shown goes, as the window's "Delete removal": off the photo and out of the save."""
        if self.cur is None or self.busy:
            return
        __, s, r = self.cur
        r.deleted = True
        for k in [k for k, x in self.gens.items() if x is r]:
            del self.gens[k]
        self.list_pick = None
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
                elif job[0] == "split":
                    self.run_split(*job[1:])
            except A.Stopped:
                self.events.put(("progress", _("Stopped: the variants already made are kept")))
            except A.Fail as e:
                self.events.put(("error", str(e)))
            except Exception as e:
                A.log("panel ERROR:", repr(e))
                import traceback
                A.log(traceback.format_exc())
                self.events.put(("error", f"{type(e).__name__}: {e}"))
            finally:
                self.events.put(("done", None))

    def run_generate(self, pid, mask, mode, model, prompt, n, target=None):
        """Variants of `model` for the selection (a new removal of the photo's Session, or more for the selection's;
        target: a removal chosen in the photo's list), with the window's progress plan: each part's expected seconds
        on this PC, the model's steps as they go (ui.App.run_job)."""
        base, s = self.session_for(pid)
        key = (base, mask["id"] if mask else None, mode)
        reflect, draw = mode == "reflect", mode == "fill"
        r = target if target is not None else self.gens.get(key)  # more variants for a selection that has some
        if r is not None and r.deleted:
            r = None
        if s is not None:
            s.stop.clear()  # a Stop pressed before this job was for the one before

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
            n = 1 if reflect else n  # DAI: one result, its strength after
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
                s.stop.clear()
                sel = s.init_mask
                A.measured("panel_read", time.time() - t0)
                r = self.gens.get(key)  # the photo's project had one for this mask: more variants for it
                if r is not None:
                    parts = [p for p in parts if p[0] != "area" and not (
                        p[0] == "lama" and any(c[0] == "LaMa" for c in r.candidates))]
                    parts[i + 1:] = [(k, lb, variant_secs() if k in ("lama", "variant") else sec)
                                     for k, lb, sec in parts[i + 1:]]
                    self.events.put(("job_total", done + secs + sum(p[2] for p in parts[i + 1:])))
                    self.events.put(("thumbs", None))
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
                self.events.put(("thumbs", None))
                parts[i + 1:] = [(k, lb, variant_secs() if k in ("lama", "variant") else sec)
                                 for k, lb, sec in parts[i + 1:]]
                self.events.put(("job_total", done + secs + sum(p[2] for p in parts[i + 1:])))
            elif kind == "lama":
                s.run_lama(r)
                self.events.put(("thumbs", None))
            elif kind == "load":
                s.get_engine(model)
            else:
                def prog(step, total, base=done, secs=secs, label=label):
                    self.events.put(("job_exact", (_("{task} · step {i}/{total}", task=label, i=step, total=total),
                                                   base + secs * step / max(1, total))))
                s.run_model(r, model, prompt, progress=prog)
                self.events.put(("thumbs", None))
            done += secs
        self.engines = {a: getattr(s, a) for a in A.ENGINE_ATTRS.values() if getattr(s, a, None) is not None}
        self.events.put(("progress", _("Choose a variant, then save it to {app}.", app=self.host.name)))

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
            if r.deleted:
                continue
            if names.get(r.mask_name) is not None:
                self.gens.setdefault((pid, names[r.mask_name], tab_of(r.kind())), r)
            elif r.reflects() and r.mask_name is None and r.mask_e.all():  # the whole photo's: the Reflections tab's,
                self.gens.setdefault((pid, None, "reflect"), r)  # its strength moved, never a second one on top
        return s

    def loaded(self, model):
        """Whether an earlier photo's Session left `model`'s engine loaded (Session.engine_loaded, before a Session)."""
        spec = A.ENGINES.get(model)
        return bool(spec and spec.engine and A.ENGINE_ATTRS.get(spec.engine) in self.engines)

    # -------------------------------------------------------------- the removal shown, its variants, the photo's list
    def current_key(self):
        """The selection now: the app's active photo (its original, for a result saved here), the mask, the tab."""
        return (self.session_for(self.photo[0])[0], self.chosen_mask(), self.mode) if self.photo else None

    def sync_cur(self):
        """The removal shown: the selection's now (photo, mask, tab) — or one chosen in the photo's list — with its
        variants, the photo's list and the photo in the app. Another selection's stay in memory until the panel is
        closed, and come back with it."""
        key = self.current_key()
        s = self.sessions.get(key[0]) if key else None
        r = self.gens.get(key) if key else None
        if self.list_pick is not None and s is not None and self.list_pick in s.removals and not self.list_pick.deleted:
            cur = (None, s, self.list_pick)
        else:
            self.list_pick = None
            cur = (key, s, r) if s is not None and r is not None and not r.deleted else None
        choose = _("Choose a variant, then save it to {app}.", app=self.host.name)
        if (cur and cur[2]) is not (self.cur and self.cur[2]) and self.job is None:
            if cur is not None and cur[2].candidates:
                self.msg = (choose, DIM)
            elif self.msg[0] == choose:  # nothing to choose here ("Saved: …" stays)
                self.msg = ("", DIM)
            self.status.configure(text=self.msg[0], fg=self.msg[1])
        self.cur = cur
        if cur is not None and cur[2].reflects():  # its strength
            self._str_busy = True
            self.str_scale.set(round(100 * cur[2].strength))
            self._str_busy = False
            self.str_lbl.configure(text=f"{round(100 * cur[2].strength)} %")
        self.show_thumbs()
        self.show_list()
        self.show_on_photo()
        self.update_buttons()

    def show_thumbs(self):
        """The window's tiles: each variant cropped around what it changed, the chosen one framed; a click chooses it,
        a right-click deletes it."""
        for w in self.grid.winfo_children():
            w.destroy()
        self.grid.configure(height=1)  # emptied, a frame keeps its size: the tiles' room goes too
        self.thumbs = []
        self.var_note.pack_forget()
        self.str_row.pack_forget()
        if self.cur is None:
            return
        __, s, r = self.cur
        self.var_title.configure(text=_("Variants of #{id}", id=r.id).upper())
        side = (self.width - int(20 * self.k) - 4 - 2 * 10) // 2  # the body's padding, the border, two cells' frames
        for c in range(2):
            self.grid.columnconfigure(c, weight=1)
        for i, (label, __) in enumerate(r.candidates):
            try:
                ph = ImageTk.PhotoImage(tile_image(s, r, i, side))
            except Exception as e:
                A.log("panel tile:", repr(e))
                continue
            self.thumbs.append(ph)
            on = r.chosen == i
            cell = tk.Frame(self.grid, bg=CARD_HI, highlightthickness=2, highlightbackground=ACCENT if on else CARD_HI,
                            cursor="hand2")
            cell.grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="n")
            img = tk.Label(cell, image=ph, bg=CARD_HI, bd=0)
            img.pack(padx=2, pady=(2, 0))
            cap = tk.Label(cell, text=("✓  " if on else "") + A.variant_text(r, label), font=self.f_small,
                           fg=ACCENT if on else FG, bg=CARD_HI)
            cap.pack(pady=(1, 2))
            for w in (cell, img, cap):
                w.bind("<Button-1>", lambda e, i=i: self.pick(i))
                w.bind("<Button-3>", lambda e, i=i: self.variant_menu(e, i))
        if not r.candidates:
            self.var_note.configure(text=_("Generating the variants…") if self.busy else
                                    _("No variants: add some with \"＋ more for #{id}\" under \"Remove selection\"",
                                      id=r.id))
            self.var_note.pack(fill="x")
        elif r.draws():
            f = s.enlarged(r, "fill")
            self.var_note.configure(text=_("Generative fill: drawn {f}× smaller than the photo here, so it looks soft "
                                           "at 100 %. A smaller selection draws it sharper.", f=f"{f:.1f}")
                                    if f > A.DRAW_SOFT else
                                    _("Generative fill: drawn near the photo's resolution (Full detail is for long "
                                      "removals)."))
            self.var_note.pack(fill="x", pady=(int(4 * self.k), 0))
        if r.reflects() and r.candidates:
            self.str_row.pack(fill="x")

    def show_list(self):
        """The photo's removals, as the window's list: each with its chosen variant, a click shows it."""
        for w in self.list_rows.winfo_children():
            w.destroy()
        self.list_rows.configure(height=1)
        self.row_photos = []
        s = self.session_for(self.photo[0])[1] if self.photo else None
        k, side = self.k, int(30 * self.k)
        for r in [x for x in (s.removals if s else []) if not x.deleted]:
            on = self.cur is not None and self.cur[2] is r
            bg = CARD_HI if on else CARD
            f = tk.Frame(self.list_rows, bg=bg, highlightthickness=1, highlightbackground=ACCENT if on else LINE,
                         cursor="hand2")
            f.pack(fill="x", pady=1)
            try:
                im = tile_image(s, r, r.chosen, side) if r.chosen is not None else Image.new("RGB", (side, side),
                                                                                            (44, 44, 44))
            except Exception:
                im = Image.new("RGB", (side, side), (44, 44, 44))
            ph = ImageTk.PhotoImage(im)
            self.row_photos.append(ph)
            th = tk.Label(f, image=ph, bg=bg, bd=0)
            th.pack(side="left", padx=int(3 * k), pady=int(3 * k))
            txt = tk.Frame(f, bg=bg)
            txt.pack(side="left", fill="x", expand=True, padx=int(6 * k))
            n = len(r.candidates)
            t1 = tk.Label(txt, text=f"#{r.id}" + (f"  ·  {A.variant_text(r, r.chosen_label())}" if r.chosen is not None
                                                 else ""), font=self.f_bold, fg=FG, bg=bg, anchor="w")
            t1.pack(anchor="w")
            named = r.mask_name + "  ·  " if r.mask_name else ""
            t2 = tk.Label(txt, text=named + (_n("{n} variant", "{n} variants", n) if n else _("no variants")),
                          font=self.f_small, fg=DIM, bg=bg, anchor="w")
            t2.pack(anchor="w")
            for w in (f, th, txt, t1, t2):
                w.bind("<Button-1>", lambda e, r=r: self.select_removal(r))

    def select_removal(self, r):
        """A removal chosen in the photo's list: its selection here (its tab, its mask) when it has one, else it alone
        (made in the window), in its tab."""
        key = next((k for k, x in self.gens.items() if x is r), None)
        if key is not None:
            if key[2] != self.mode:
                self.set_mode(key[2])
            label = next((lb for lb, mid in self.mask_options() if mid == key[1]), None)
            if label and label != self.mask_var.get():
                self.mask_var.set(label)
        else:
            tab = tab_of(r.kind())
            if tab != self.mode:
                self.set_mode(tab)
            self.list_pick = r
        self.sync_cur()

    def pick(self, i):
        if self.cur is None or self.busy:
            return
        r = self.cur[2]
        if 0 <= i < len(r.candidates) and i != r.chosen:
            r.chosen, r.user_picked = i, True
            self.sync_cur()

    def step_variant(self, d):
        """← / →: the previous / next variant of the removal shown becomes the chosen one."""
        r = self.cur[2] if self.cur else None
        if r is None or not r.candidates or self.busy:
            return
        self.pick(int(np.clip((r.chosen if r.chosen is not None else 0) + d, 0, len(r.candidates) - 1)))

    def variant_menu(self, e, i):
        """Right-click on a variant: a menu to delete it, as in the window."""
        m = tk.Menu(self.root, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground="#1b1b1b", bd=0,
                    relief="flat", font=self.f_small)
        m.add_command(label=_("Delete variant"), command=lambda: self.delete_variant(i))
        m.tk_popup(e.x_root, e.y_root)

    def delete_variant(self, i):
        if self.cur is None:
            return
        if self.busy:
            self.status.configure(text=_("Wait for the generation in progress to finish, then delete the variant"))
            return
        __, s, r = self.cur
        if i < len(r.candidates):
            s.delete_variant(r, i)
            if s.dng_path:
                threading.Thread(target=s.save_project, daemon=True).start()
            self.sync_cur()

    def on_strength(self, v):
        """The strength moving (Lightroom's Amount): its number now; the variant and the photo in the app on release."""
        if not self._str_busy:
            self.str_lbl.configure(text=f"{round(float(v))} %")

    def strength_done(self):
        """The strength let go: how much of the reflection found goes — nothing runs again (Session.set_strength)."""
        if self.cur is None or not self.cur[2].reflects() or not self.cur[2].candidates or self.busy:
            return
        __, s, r = self.cur
        s.set_strength(r, round(float(self.str_scale.get())) / 100)
        self.sync_cur()

    # -------------------------------------------------------------- the variants on the photo in the app
    def show_on_photo(self):
        """What Save would write, onto the photo in the app (overlay_worker): every removal of the photo's Session with
        a chosen variant — on a result saved already (its DNG), only those changed since. Else away from it."""
        s = self.session_for(self.photo[0])[1] if self.photo else None
        rs = self.chosen_removals(s)
        if rs and self.photo[0] == s.dng_id:
            done = self.saved.get(s, {})
            rs = [r for r in rs if done.get(r) != (r.chosen, r.strength)]
        # the photo whole in the view (whole_view), the panel in sight (the full window shows the photo itself), and
        # not while the original is held
        on = (bool(rs) and self.on_photo.get() and self.photo[4] and self.window is None
              and not self.original_held)
        self.overlays.put((s, rs, self.photo[0]) if on else None)

    def hold_original(self, on):
        """◐ Original (or \\) held: the photo in the app without the variants, as the window's Original."""
        if on != self.original_held:
            self.original_held = on
            self.show_on_photo()

    def on_photo_toggled(self):
        A.remember("panel_on_photo", self.on_photo.get())
        self.show_on_photo()
        self.update_buttons()

    def overlay_worker(self):
        """The app's Layout Image (a PNG it draws over the photo, fitted to it): the chosen variants, or the app's own
        setting back. Only the latest request counts."""
        while True:
            want = self.overlays.get()
            while not self.overlays.empty():
                want = self.overlays.get()
            shown = tuple((id(r), r.chosen, r.strength) for r in want[1]) + (want[2],) if want else None
            if shown is not None and shown == self.overlay_shown and self.layout_before is not None:
                continue  # already on the photo (another mask clicked in the app, the same variants)
            try:
                t0 = time.time()
                path, problem = self.overlay_png(*want) if want else (None, None)
                if path and not self.closing:
                    self.put_layout(path)
                    self.overlay_shown = shown
                    A.log(f"panel: on the photo in {time.time() - t0:.2f}s")
                else:
                    self.take_layout()
                    self.overlay_shown = None
                if problem != self.overlay_problem:
                    self.events.put(("overlay_problem", problem))
            except Exception as e:
                A.log("panel on the photo:", repr(e))

    def overlay_png(self, s, rs, pid):
        """The removals' chosen variants as the app shows photo pid: transparent but where they change it, as the app
        crops it, at the size it shows it, as a PNG in the Session's folder: (path, None), or (None, why) where the
        app's view cannot be matched — its Geometry (Upright, perspective, scale, offsets), which base.png is
        without. A lens profile is not undone in base.png either: near the edges of a wide lens a variant may sit a
        pixel or two off."""
        dev = self.lc.one("photo.inspect", {"id": pid})["develop"]
        crop, geo = dev["crop"], dev.get("geometry") or {}
        g = crop["geometry"]
        if any(geo.get(k, v) != v for k, v in A.NEUTRAL_GEOMETRY.items()):
            A.log("panel: not shown on the photo (its Geometry)")
            return None, _("Not shown on this photo: its Geometry (Upright, perspective…) moves it in {app}. Save "
                           "shows the result.", app=self.host.name)
        h, w = s.base_arr.shape[:2]
        alpha = np.zeros((h, w), np.float32)  # where the removals shown change the photo
        for r in rs:
            __, al = s.preview(r)
            y0, y1, x0, x1 = r.base_rect
            sub_a = alpha[y0:y1, x0:x1]
            ph, pw = sub_a.shape
            np.maximum(sub_a, np.asarray(al, np.float32)[:ph, :pw], out=sub_a)
        rgba = np.zeros((h, w, 4), np.uint8)
        # every chosen removal as the photo shows them (a reflection's change on the ones before it): on a saved
        # result the DNG has some of them already, and what is drawn over it must have them too
        rgba[..., :3] = s.composite(only=self.chosen_removals(s))
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
        if self.view_px and self.view_px[0] < im.width:  # no bigger than the app shows it: written and read faster
            im = im.resize(self.view_px, Image.BILINEAR)
        self.overlay_n += 1
        path = s.work / f"on-photo-{self.overlay_n}.png"  # a new name each time: the app reads it again
        im.save(path, compress_level=1)
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
        variants, the models loaded), the removal shown, the tab, the model, its text and the number of variants.
        The panel steps aside until the window goes back to it (window_closed); the window is then kept, hidden, and
        reopens at once."""
        if self.busy or not self.photo or self.window is not None:
            return
        self.busy = True
        self.t_window = time.time()
        self.jobs.put(("window", self.photo[0], self.chosen_mask_dict(), self.mode,
                       self.cur[2] if self.cur is not None else None))
        self.update_buttons()

    def prepare_window(self, pid, mask, mode, shown=None):
        """The worker's part: the photo's Session (read now if it has none) and, for a mask nothing was made of yet,
        its selection, which the window starts from."""
        base, s = self.session_for(pid)
        r = shown if shown is not None and not shown.deleted else None
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
                 "variants": self.n_variants()}
        self.overlays.put(None)  # the window shows the photo itself
        self.root.withdraw()
        if self.window_app is not None and self.window_app.s is not s:  # another photo: its own window
            self.window_app.destroy()
            self.window_app = None
        try:
            if self.window_app is None:
                self.window_app = ui.App(s, s.args, master=self.root, on_close=self.window_closed, start=start)
            else:
                self.window_app.reopen(start)
            self.window = self.window_app
            A.log(f"panel: the full window in {time.time() - self.t_window:.2f}s")
        except Exception:
            import traceback
            A.log("panel ERROR (full window):", traceback.format_exc())
            self.window = self.window_app = None
            self.root.deiconify()

    def window_closed(self, app):
        """Back from the window: what was done there stays (the Session is the same), and the panel takes its tab, its
        model, its texts and its number of variants — and the removal it showed."""
        t0 = time.time()
        self.window = None
        s = app.s
        if not app.dng_dirty and s.dng_path:  # saved there and nothing changed since: its DNG has what is chosen
            self.saved[s] = {r: (r.chosen, r.strength) for r in self.chosen_removals(s)}
        model = app.model_key()
        self.set_mode(app.tab or tab_of(A.model_kind(model)))
        if model in self.models_for(self.mode):
            self.model_var.set(self.model_labels[model])
        prompts = dict(app.prompt_text)
        if app.prompt_mode:
            prompts[app.prompt_mode] = app.prompt.get()
        self.prompt_text.update(prompts)
        if self.prompt_mode:
            self.prompt.set_text(self.prompt_text.get(self.prompt_mode, ""))
        self.count.set(int(app.count.get()))
        self.engines = {a: getattr(s, a) for a in A.ENGINE_ATTRS.values() if getattr(s, a, None) is not None}
        if app.cur is not None and not app.cur.deleted:
            self.select_removal(app.cur)  # its mask here, or it alone (made in the window)
        else:
            self.sync_cur()
        self.bind_wheel()
        self.root.deiconify()
        A.log(f"panel: back from the full window in {time.time() - t0:.2f}s")

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
        if self.scroller.winfo_manager():
            self.scroller.pack_forget()
            self.fold_btn.configure(text="+")
        else:
            self.scroller.pack(fill="both", expand=True)
            self.fold_btn.configure(text="–")

    def close(self):
        self.closing = True
        try:
            self.take_layout()  # the app's own Layout Image setting back
        except Exception as e:
            A.log("panel on the photo:", repr(e))
        if self.window_app is not None:
            self.window_app.destroy()
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

    def pshot(self, n):
        """The panel alone, from the screen."""
        from PIL import ImageGrab
        self.root.lift()
        self.root.update()
        time.sleep(0.4)
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height()), all_screens=True).save(
            system.ROOT / "work" / f"panel-only-{n}.png")

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
            self.prompt.set_text(arg)
        elif kind == "variants":
            self.count.set(int(arg))
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
        elif kind == "step":
            self.step_variant(int(arg))
        elif kind == "list":  # the photo's list: removal #id
            s = self.session_for(self.photo[0])[1]
            self.select_removal(next(x for x in s.removals if x.id == int(arg)))
        elif kind == "original":
            self.hold_original(arg == "1")
        elif kind == "info":
            self.toggle_info()
        elif kind == "stop":
            self.stop_jobs()
        elif kind == "split":
            self.split_masks()
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
                self.root.after(200, lambda: self.test(steps))
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
        elif kind == "pshot":
            self.pshot(int(arg or 0))
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
