"""AI Remove as a small panel next to LightCraft's (or Chromaforge's) window — a prototype (airemove --panel).

LightCraft has no plug-in panels, so, as OpenFill does next to PhotoCraft (beckettharriman/openfill, Apache-2.0:
photocraft/openfill_photocraft/tether.py), the panel is a window of its own that Windows makes an "owned" window of
the app's: it stays above the app (and only above it), hides when the app is minimized, and follows it when it moves.
Elsewhere it is an ordinary window beside it.

Everything else goes through the app's control channel, as AI Remove's window does:
- the app's active photo and its masks are watched; the mask selected in the app (or chosen here) is the selection
  (a SAM 3 Object or Describe mask is read from the develop settings, a brush or gradient one rendered:
  airemove.extract);
- Remove (LaMa, RORem, FLUX Fill, Qwen-Image), Fill (Generative fill: what the prompt describes) or Reflections (DAI,
  the mask optional) runs in this process, with AI Remove's own Session: its area, its tiles, its blend;
- the variants show here; Save writes the DNG, stacks it on the original in the app and shows it there — without the
  mask that was the selection;
- "Full window" opens AI Remove's window on the same photo, for what the panel does not do (describe, split, the
  shadow, the brush).
The panel stays open from one photo to the next, and the models stay loaded: only the first variant pays their load.

Tests: AIREMOVE_PANEL_TEST runs steps separated by ";": wait:ms · mode:remove|fill|reflect · model:key ·
mask:<name> · prompt:<text> · variants:n · generate · waitvars:n · pick:i · save · waitidle · shot:n · quit."""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from argparse import Namespace
from pathlib import Path

import numpy as np
from PIL import Image, ImageTk

import airemove as A
import engines
import system
from i18n import _
from ui import ACCENT, BG, BTN, BTN_HI, CARD, CARD_HI, DIM, FG, FILL_MENU, LINE, MODEL_NAMES, WARN

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
    def __init__(self, args):
        self.args = args
        self.host = A.host_for(args)
        self.lc = A.LC(host=self.host)
        self.events, self.jobs = queue.Queue(), queue.Queue()
        self.photo = None  # (pid, file name, masks) of the app's active photo
        self.cur = None  # (key, Session, Removal) of the last generation: more variants go to it
        self.engines = {}  # Session attribute -> engine, kept loaded from one photo's Session to the next
        self.busy = False
        self.thumbs = []
        self.mode, self.mask_id = "remove", None
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
        self.width = int(WIDTH * k)
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
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=pad, pady=(pad, 4))
        tk.Label(head, text="AI Remove", font=self.f_bold, fg=ACCENT, bg=CARD).pack(side="left")
        self.status_dot = tk.Label(head, text="●", font=self.f_small, fg=DIM, bg=CARD)
        self.status_dot.pack(side="left", padx=(6, 0))
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
        self.model_lbl = self.label(body, _("Model"))
        self.model_var = tk.StringVar(value="")
        self.model_menu = tk.OptionMenu(body, self.model_var, "")
        self.style_menu(self.model_menu)
        self.model_menu.pack(fill="x")
        self.prompt_lbl = self.label(body, "")
        self.prompt = tk.Entry(body, font=self.f_txt, bg=BTN, fg=FG, insertbackground=FG, relief="flat")
        self.prompt.pack(fill="x", ipady=int(4 * k))
        self.label(body, _("Variants"))
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        self.n_var = tk.IntVar(value=2)
        self.n_btns = []
        for n in (1, 2, 3, 4):
            b = self.button(row, str(n), lambda n=n: self.set_n(n), small=True)
            b.pack(side="left", fill="x", expand=True, padx=(0 if n == 1 else 2, 0))
            self.n_btns.append(b)
        self.strength_lbl = self.label(body, _("Strength (how much of the reflection goes)"))
        self.strength = tk.Scale(body, from_=0, to=150, orient="horizontal", bg=CARD, fg=FG, troughcolor=BTN,
                                 highlightthickness=0, bd=0, font=self.f_small)
        self.strength.set(75)
        self.gen_btn = self.button(body, "", self.generate, accent=True)
        self.gen_btn.pack(fill="x", pady=(10, 0))
        self.progress = tk.Label(body, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                 wraplength=self.width - 2 * pad)
        self.progress.pack(fill="x", pady=(6, 0))
        self.grid = tk.Frame(body, bg=CARD)
        self.grid.pack(fill="x", pady=(6, 0))
        bottom = tk.Frame(body, bg=CARD)
        bottom.pack(fill="x", pady=(8, 0))
        self.save_btn = self.button(bottom, _("Save to {app}", app=self.host.name), self.save)
        self.save_btn.pack(side="left", fill="x", expand=True)
        self.full_btn = self.button(bottom, _("Full window"), self.full_window, small=True)
        self.full_btn.pack(side="left", padx=(4, 0))
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
        self.model_options = [(_(MODEL_NAMES[m]), m) for m in models]
        self.set_options(self.model_menu, self.model_var, self.model_options)
        prompt_txt = {"remove": _("What to put there (optional, FLUX Fill only)"),
                      "fill": _("What to draw (required, in English)")}.get(mode)
        if prompt_txt:
            self.prompt_lbl.configure(text=prompt_txt)
            if not self.prompt_lbl.winfo_manager():
                self.prompt_lbl.pack(fill="x", pady=(8, 2), after=self.model_menu)
                self.prompt.pack(fill="x", ipady=int(4 * self.k), after=self.prompt_lbl)
        else:
            self.prompt_lbl.pack_forget()
            self.prompt.pack_forget()
        if mode == "reflect":
            self.strength_lbl.pack(fill="x", pady=(8, 2), before=self.gen_btn)
            self.strength.pack(fill="x", before=self.gen_btn)
        else:
            self.strength_lbl.pack_forget()
            self.strength.pack_forget()
        self.gen_btn.configure(text={"remove": _("Remove the selection"), "fill": _("Draw in the selection"),
                                     "reflect": _("Remove reflections")}[mode])
        self.refresh_masks()
        self.update_buttons()

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

    def chosen_model(self):
        return dict(self.model_options).get(self.model_var.get())

    def update_buttons(self):
        ready = self.photo is not None and not self.busy
        has_mask = bool(self.mask_options())
        self.gen_btn.configure(state="normal" if ready and has_mask and self.chosen_model() else "disabled")
        live = self.cur is not None and self.cur[2].candidates and self.cur[2].chosen is not None
        self.save_btn.configure(state="normal" if live and not self.busy else "disabled")
        self.full_btn.configure(state="normal" if self.photo else "disabled")
        self.status_dot.configure(fg=ACCENT if self.busy else ("#4a9c63" if self.photo else DIM))

    # -------------------------------------------------------------- following the app
    def follow(self):
        """Docked inside the app's window, at its right edge under its title bar; hidden while it is minimized."""
        t = self.tether
        if t.hwnd and not t.alive():
            t.find()
            if t.hwnd:
                t.own(self.root_hwnd())
        if t.hwnd:
            if t.minimized():
                self.root.withdraw()
            else:
                left, top, right, bottom = t.rect()
                h = self.root.winfo_reqheight()
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
        """The app's active photo and its masks, every second and a half (the app has no events to listen to)."""
        last = None
        while True:
            try:
                st = self.lc.state()
                pid = (st.get("selection") or {}).get("active")
                info = self.lc.one("photo.inspect", {"id": pid}) if pid else None
                now = None if info is None else (pid, info.get("file_name"),
                                                 [m for m in info["develop"]["masks"] if m.get("visible", True)],
                                                 st.get("activeMask"))  # the mask being edited in the app
                key = None if now is None else (pid, tuple((m["id"], m.get("name")) for m in now[2]), now[3])
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
            elif kind == "down":
                self.photo = None
                self.photo_lbl.configure(text=data)
            elif kind == "progress":
                self.progress.configure(text=data, fg=DIM)
            elif kind == "error":
                self.progress.configure(text=data, fg=WARN)
            elif kind == "thumbs":
                self.show_thumbs()
            elif kind == "done":
                self.busy = False
            self.update_buttons()
        self.root.after(100, self.pump)

    # -------------------------------------------------------------- generating
    def generate(self):
        if self.busy or not self.photo:
            return
        model, prompt = self.chosen_model(), self.prompt.get().strip()
        if self.mode == "fill" and not prompt:
            self.progress.configure(text=_("Write what to draw first, in English (e.g. a wooden bench)."), fg=WARN)
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
        self.jobs.put(("save",))
        self.update_buttons()

    def worker(self):
        while True:
            job = self.jobs.get()
            try:
                if job[0] == "generate":
                    self.run_generate(*job[1:])
                elif job[0] == "save":
                    s = self.cur[1]
                    self.events.put(("progress", _("Saving the DNG and stacking it in {app}…", app=self.host.name)))
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
        key = (pid, mask_id, mode)
        if self.cur is not None and self.cur[0] == key and not self.cur[2].deleted:
            __, s, r = self.cur  # more variants for the same selection
        else:
            t0 = time.time()
            self.events.put(("progress", _("Reading the photo and its mask from {app}…", app=self.host.name)))
            args = Namespace(id=pid, raw=None, variants=None, auto=None, shadow=False, check=False,
                             app=self.host.key)
            s = A.Session(self.lc, args)
            s.find()
            chosen = [m for m in s.info["develop"]["masks"] if m["id"] == mask_id]
            s.targets, s.prompt = chosen, ""
            s.used_masks = [m["name"] for m in chosen if m.get("name")]
            s.prepare()
            for attr, eng in self.engines.items():  # loaded by an earlier photo's Session
                setattr(s, attr, eng)
            sel = s.init_mask
            if sel is None:
                if mode != "reflect":
                    raise A.Fail(_("The mask selects nothing AI Remove can read: choose another, or make an Object "
                                   "mask."))
                sel = np.ones(s.base_arr.shape[:2], bool)
            r = s.new_removal(sel, reflection=mode == "reflect", draw=mode == "fill")
            self.cur = (key, s, r)
            A.log(f"panel: #{r.id} on {s.info.get('file_name')} in {time.time() - t0:.1f}s")
            self.events.put(("thumbs", None))
        for i in range(1 if model in ("lama", "dai") else n):
            self.events.put(("progress", _("{model}: variant {i} of {n}…", model=_(MODEL_NAMES[model]), i=i + 1,
                                           n=1 if model in ("lama", "dai") else n)))
            if model == "lama":
                if any(c[0] == "LaMa" for c in r.candidates):
                    break
                s.run_lama(r)
            else:
                s.run_model(r, model, prompt)
            self.events.put(("thumbs", None))
        if mode == "reflect":
            s.set_strength(r, strength)
        self.engines = {a: getattr(s, a) for a in A.ENGINE_ATTRS.values() if getattr(s, a, None) is not None}
        self.events.put(("progress", _("Choose a variant, then save it to {app}.", app=self.host.name)))
        self.events.put(("thumbs", None))

    # -------------------------------------------------------------- variants
    def show_thumbs(self):
        for w in self.grid.winfo_children():
            w.destroy()
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
            self.update_buttons()

    # -------------------------------------------------------------- the rest
    def full_window(self):
        """AI Remove's own window on the same photo (describe, split, the shadow, the brush)."""
        if not self.photo:
            return
        main = Path(A.__file__).resolve()
        subprocess.Popen([sys.executable, str(main), "--id", str(self.photo[0]), "--app", self.host.key],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

    def fold(self):
        if self.body.winfo_manager():
            self.body.pack_forget()
            self.fold_btn.configure(text="+")
        else:
            self.body.pack(fill="both", expand=True, padx=int(10 * self.k), pady=(0, int(10 * self.k)))
            self.fold_btn.configure(text="–")

    def close(self):
        A.log("panel closed")
        self.root.destroy()

    def shot(self, n):
        """The app's window with the panel on it, from the screen."""
        from PIL import ImageGrab
        self.tether.front()
        self.root.lift()
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
            self.model_var.set(next(lb for lb, m in self.model_options if m == arg))
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
