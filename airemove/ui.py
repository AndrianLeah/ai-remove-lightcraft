"""AI Remove window, organised like Lightroom's Generative Remove.

The photo fills the left side and always shows the result: every removal with its chosen variant. Select what to
remove (Clic SAM: SAM 3 outlines the whole object · Alt/Option+click / Shift+click refine it · Pennello + / Gomma −),
then "Rimuovi selezione": it becomes removal #n with its own area and its own variants (LaMa + SDXL or FLUX).
On the right: the removals; click one to see only its variants, pick one, ask for more or delete it — the other
removals are not touched. "Salva in LightCraft" writes one DNG with all of them, stacked on the original.
Zoom: Ctrl+wheel (Cmd+wheel on a Mac) or + / −, 0 = whole photo; pan with the wheel, middle button or Space+drag.
Hold "Originale" (or \\) to compare with the photo before the removals.

Windows, macOS and Linux: modifiers, mouse buttons and the wheel differ between Tk's backends (see PLATFORM below).
"""
import ctypes
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

import numpy as np
from PIL import Image, ImageDraw, ImageTk
from scipy import ndimage as ndi

import airemove as A
import engines
import i18n
from i18n import _, _n

# ---------------------------------------------------------------------------------------------- PLATFORM
MAC, WIN = sys.platform == "darwin", sys.platform == "win32"
X11 = not (MAC or WIN)
# Tk's event.state bits: Shift 0x1 and Control 0x4 everywhere; Alt is 0x20000 on Windows and Mod1 (0x8) on X11; on
# macOS Mod1 (0x8) is Command and Mod2 (0x10) is Option
ALT_MASK = 0x20000 if WIN else (0x10 if MAC else 0x8)
CMD_MASK = 0x8 if MAC else 0
# right button: Button-2 on macOS's Tk (Aqua), Button-3 elsewhere; the middle one is the other
RIGHT, MIDDLE = ("2", "3") if MAC else ("3", "2")
MOD = "Cmd" if MAC else "Ctrl"  # the zoom / undo modifier, as shown in the hints
ALT = "Option" if MAC else "Alt"
ICON = A.ROOT / "assets" / "icon" / "airemove-256.png"


def mods(e):
    """(zoom modifier: Ctrl, or Cmd on a Mac; Shift; Alt / Option) from a Tk event."""
    st = getattr(e, "state", 0) or 0
    return bool(st & (0x4 | CMD_MASK)), bool(st & 0x1), bool(st & ALT_MASK)


def num(x, decimals):
    """A number with the language's decimal mark (1.5 / 1,5)."""
    t = f"{x:.{decimals}f}"
    return t.replace(".", ",") if i18n.language() == "it" else t


def bring_to_front(root):
    """A window started from another app (LightCraft) opens behind it on macOS unless the process activates itself."""
    root.lift()
    root.attributes("-topmost", True)
    root.after(800, lambda: root.attributes("-topmost", False))
    root.focus_force()
    if MAC:
        try:
            import ctypes.util
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.objc_msgSend.restype = ctypes.c_void_p
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            app = objc.objc_msgSend(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"))
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            objc.objc_msgSend(app, objc.sel_registerName(b"activateIgnoringOtherApps:"), True)
        except Exception:
            pass

BG, SIDE, CARD, CARD_HI, LINE, CANVAS = "#141414", "#1b1b1b", "#232323", "#2c2c2c", "#303030", "#0e0e0e"
BTN, BTN_HI, FG, DIM = "#2f2f2f", "#3c3c3c", "#ececec", "#8e8e8e"
ACCENT, ACCENT_HI, GREEN, GREEN_HI = "#e8c35a", "#f2d27a", "#3d8a55", "#4a9c63"
PANEL = CARD
RED = (235, 64, 52)
WHITE = (240, 240, 240)
MODEL_KEYS = ["sdxl", "flux", "lama"]


def outline(u, width=2):
    """Edge pixels of a bool mask (computed on its bounding box only: quick on a full-size photo)."""
    e = np.zeros_like(u)
    sl = ndi.find_objects(u.astype(np.uint8))
    if sl and sl[0]:
        ys, xs = sl[0]
        y0, y1 = max(0, ys.start - 3), min(u.shape[0], ys.stop + 3)
        x0, x1 = max(0, xs.start - 3), min(u.shape[1], xs.stop + 3)
        sub = u[y0:y1, x0:x1]
        e[y0:y1, x0:x1] = sub ^ ndi.binary_erosion(sub, iterations=width)
    return e


class ZoomView:
    """A Canvas showing a PIL image fitted to it, with zoom (1 = fit, up to 400 % of the image's pixels) around a
    point and panning. Only the visible part is resampled, so it stays quick when zoomed in."""

    def __init__(self, canvas, on_change=None):
        self.c, self.on_change = canvas, on_change
        self.img, self._tk, self.last = None, None, None
        self.z, self.cx, self.cy = 1.0, 0.0, 0.0

    def size(self):
        w, h = self.c.winfo_width(), self.c.winfo_height()
        if w <= 1 or h <= 1:
            w, h = int(self.c.cget("width")), int(self.c.cget("height"))
        return max(1, w), max(1, h)

    def fit(self):
        cw, ch = self.size()
        return min(cw / self.img.width, ch / self.img.height)

    def scale(self):
        return self.fit() * self.z

    def set_image(self, img, keep=True):
        fresh = self.img is None or img.size != self.img.size or not keep
        self.img = img
        if fresh:
            self.z, self.cx, self.cy = 1.0, img.width / 2, img.height / 2
        self.render()

    def _clamp(self):
        s, (cw, ch), (W, H) = self.scale(), self.size(), self.img.size
        hw, hh = cw / s / 2, ch / s / 2
        self.cx = W / 2 if hw >= W / 2 else min(max(self.cx, hw), W - hw)
        self.cy = H / 2 if hh >= H / 2 else min(max(self.cy, hh), H - hh)

    def render(self):
        if self.img is None:
            return
        self._clamp()
        s, (cw, ch), (W, H) = self.scale(), self.size(), self.img.size
        x0, y0 = self.cx - cw / s / 2, self.cy - ch / s / 2
        ix0, iy0 = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
        ix1, iy1 = min(W, int(np.ceil(x0 + cw / s))), min(H, int(np.ceil(y0 + ch / s)))
        out = (max(1, round((ix1 - ix0) * s)), max(1, round((iy1 - iy0) * s)))
        crop = self.img.crop((ix0, iy0, ix1, iy1))
        crop = crop.resize(out, Image.NEAREST) if s >= 2 else crop.resize(out, Image.BILINEAR, reducing_gap=2.0)
        self.last = crop  # what is on screen (tests save it)
        self._tk = ImageTk.PhotoImage(crop)
        self.c.delete("img", "mark")
        self.c.create_image((ix0 - x0) * s, (iy0 - y0) * s, image=self._tk, anchor="nw", tags="img")
        self.c.tag_lower("img")
        if self.on_change:
            self.on_change(self)

    def to_image(self, x, y):
        s, (cw, ch) = self.scale(), self.size()
        return self.cx + (x - cw / 2) / s, self.cy + (y - ch / 2) / s

    def to_canvas(self, ix, iy):
        s, (cw, ch) = self.scale(), self.size()
        return (ix - self.cx) * s + cw / 2, (iy - self.cy) * s + ch / 2

    def zoom(self, factor, x=None, y=None):
        if self.img is None:
            return
        cw, ch = self.size()
        x = cw / 2 if x is None else x
        y = ch / 2 if y is None else y
        ix, iy = self.to_image(x, y)
        z = min(max(self.z * factor, 1.0), max(1.0, 4.0 / self.fit()))
        if abs(z - self.z) < 1e-6:
            return
        self.z = z
        s = self.scale()
        self.cx, self.cy = ix - (x - cw / 2) / s, iy - (y - ch / 2) / s
        self.render()

    def zoom_to(self, y0, y1, x0, x1, margin=1.5):
        if self.img is None:
            return
        cw, ch = self.size()
        want = min(cw / max(1, (x1 - x0) * margin), ch / max(1, (y1 - y0) * margin))
        self.z = min(max(want / self.fit(), 1.0), max(1.0, 4.0 / self.fit()))
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.render()

    def reset(self):
        if self.img is not None:
            self.z = 1.0
            self.render()

    def pan(self, dx, dy):
        if self.img is not None and self.z > 1.0:
            s = self.scale()
            self.cx -= dx / s
            self.cy -= dy / s
            self.render()

    def percent(self):
        return 0 if self.img is None else round(self.scale() * 100)


class Scroll(tk.Frame):
    """A vertically scrollable frame (self.inner holds the content, as wide as the frame)."""

    def __init__(self, master, height, width, bg=None):
        bg = bg or CARD
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, height=height, width=width)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="AI.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")


class Stepper(tk.Frame):
    """−  N  +  (with the Spinbox methods the window uses: get / delete / insert)."""

    def __init__(self, master, value, lo, hi, app):
        super().__init__(master, bg=CARD)
        self.lo, self.hi = lo, hi
        self.minus = app.button(self, "−", lambda: self.set(self.v - 1), small=True)
        self.minus.pack(side="left")
        self.lbl = tk.Label(self, text="", font=app.f_bold, fg=FG, bg=CARD, width=3)
        self.lbl.pack(side="left")
        self.plus = app.button(self, "+", lambda: self.set(self.v + 1), small=True)
        self.plus.pack(side="left")
        self.set(value)

    def set(self, v):
        self.v = int(min(max(int(v), self.lo), self.hi))
        self.lbl.configure(text=str(self.v))

    def get(self):
        return str(self.v)

    def delete(self, *a):
        pass

    def insert(self, i, v):
        self.set(v)


class HintEntry(tk.Entry):
    """Entry showing a grey hint while empty; get() returns "" then."""

    def __init__(self, master, hint, **kw):
        super().__init__(master, **kw)
        self.hint, self._fg, self._ph = hint, kw.get("fg", FG), False
        self.bind("<FocusIn>", self._in, add="+")
        self.bind("<FocusOut>", self._out, add="+")
        self._out()

    def _in(self, e=None):
        if self._ph:
            super().delete(0, "end")
            self.configure(fg=self._fg)
            self._ph = False

    def _out(self, e=None):
        if not super().get():
            self._ph = True
            self.configure(fg=DIM)
            super().insert(0, self.hint)

    def get(self):
        return "" if self._ph else super().get()

    def delete(self, a, b=None):
        if not self._ph:
            super().delete(a, b)

    def insert(self, i, s):
        self._in()
        super().insert(i, s)
        if not super().get() and self.focus_get() is not self:
            self._out()



class App:
    def __init__(self, session, args):
        self.s, self.args = session, args
        self.events = queue.Queue()  # workers -> window
        self.jobs = queue.Queue()  # window -> main worker (new removal / more variants / save)
        self.clicks = queue.Queue()  # window -> SAM worker
        self.base_ready = threading.Event()
        # selection being built, a list of operations on base.png's frame applied in order:
        # {"kind": "obj" (SAM object, refinable) | "add" (brush, LightCraft mask) | "erase", "mask", "id", ...}
        self.ops, self.history, self.op_seq = [], [], 0
        self.sel_mask = None
        self.tool, self.brush, self.stroke, self.pending = "sam", 0.02, None, {}
        self.cur = None  # removal shown in the panel
        self.row_widgets, self.tiles = {}, []
        self.outlines = {}  # removal id -> (ys, xs) of its outline in base.png
        self.show_original = False
        self.dng_dirty = False  # choices changed since the DNG was last written
        self.busy = self.extracting = self.writing = False
        self.sam_ready = False
        self.job = None  # progress of the running job
        self.task, self.task_t0 = "", time.time()
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        r = self.root = tk.Tk(className="airemove")  # WM_CLASS "Airemove": the Linux menu entry matches it
        k = self.k = max(1.0, r.winfo_fpixels("1i") / 96.0)
        self.side_w = int(372 * k)
        self.THUMB, self.ROWTHUMB = (self.side_w - int(96 * k)) // 2, int(52 * k)
        r.title("AI Remove")
        r.configure(bg=BG)
        r.protocol("WM_DELETE_WINDOW", self.cancel)
        self._build()
        self.set_tool("sam")
        try:
            self._icon = tk.PhotoImage(file=str(ICON))
            r.iconphoto(True, self._icon)
        except (tk.TclError, OSError):
            pass
        try:
            if X11:
                r.attributes("-zoomed", True)  # X11 window managers: maximized
            else:
                r.state("zoomed")  # the photo gets the whole screen
        except tk.TclError:
            r.geometry(f"{int(r.winfo_screenwidth() * .9)}x{int(r.winfo_screenheight() * .85)}+20+10")
        bring_to_front(r)
        threading.Thread(target=self.worker, daemon=True).start()
        r.after(100, self.poll)

    # ------------------------------------------------------------------------------------------ layout
    def button(self, parent, text, cmd, kind="grey", small=False, **kw):
        """Flat button with a hover colour. kind: grey | accent | green | ghost."""
        bg, fg, hi = {"grey": (BTN, FG, BTN_HI), "accent": (ACCENT, "#1b1b1b", ACCENT_HI),
                      "green": (GREEN, "#ffffff", GREEN_HI), "ghost": (SIDE, DIM, CARD)}[kind]
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hi, activeforeground=fg,
                      relief="flat", bd=0, cursor="hand2", font=self.f_small if small else self.f_txt,
                      padx=int(12 * self.k), pady=int((4 if small else 7) * self.k), disabledforeground="#666666",
                      **kw)
        b._bg, b._hi = bg, hi
        b.bind("<Enter>", lambda e: b.configure(bg=b._hi) if str(b["state"]) == "normal" else None)
        b.bind("<Leave>", lambda e: b.configure(bg=b._bg))
        return b

    def font(self, size, bold=False):
        """The system's UI font: Segoe UI on Windows, the San Francisco / Helvetica family on a Mac, the desktop's
        sans on Linux. Tk sizes are points; a Mac's are drawn smaller, so they get a bit more."""
        if not hasattr(self, "_family"):
            have = set(tkfont.families(self.root))
            prefs = (("Segoe UI",) if WIN else ("SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue") if MAC
                     else ("Inter", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans", "Liberation Sans"))
            self._family = next((f for f in prefs if f in have), "TkDefaultFont")
        size = size + 3 if MAC else size
        if WIN and bold:
            return ("Segoe UI Semibold", size)
        return (self._family, size, "bold") if bold else (self._family, size)

    def section(self, parent, title, expand=False):
        """A titled card of the side panel; returns (title label, inner frame)."""
        hdr = tk.Label(parent, text=title.upper(), font=self.f_head, fg=DIM, bg=SIDE, anchor="w")
        hdr.pack(fill="x", pady=(int(14 * self.k), int(6 * self.k)))
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        card.pack(fill="both" if expand else "x", expand=expand)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="both", expand=expand, padx=int(10 * self.k), pady=int(10 * self.k))
        return hdr, inner

    def _build(self):
        r, k = self.root, self.k
        self.f_txt, self.f_small = self.font(10), self.font(9)
        self.f_head, self.f_bold = self.font(8, True), self.font(10, True)
        st = ttk.Style(r)
        st.theme_use("clam")
        st.configure("AI.Horizontal.TProgressbar", troughcolor=BG, background=ACCENT, bordercolor=BG,
                     lightcolor=ACCENT, darkcolor=ACCENT, thickness=max(3, int(3 * k)))
        st.configure("AI.Vertical.TScrollbar", troughcolor=CARD, background="#3a3a3a", bordercolor=CARD,
                     arrowcolor=DIM, lightcolor="#3a3a3a", darkcolor="#3a3a3a", gripcount=0, arrowsize=int(9 * k))
        st.map("AI.Vertical.TScrollbar", background=[("active", "#4a4a4a")])
        st.configure("AI.TCombobox", fieldbackground=BTN, background=BTN, foreground=FG, arrowcolor=FG,
                     bordercolor=LINE, lightcolor=BTN, darkcolor=BTN, selectbackground=BTN, selectforeground=FG,
                     padding=int(5 * k))
        st.map("AI.TCombobox", fieldbackground=[("readonly", BTN)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", BTN)], selectforeground=[("readonly", FG)],
               background=[("readonly", BTN), ("active", BTN_HI)])
        st.configure("AI.Horizontal.TScale", troughcolor="#3a3a3a", background=ACCENT, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT, gripcount=0)
        r.option_add("*TCombobox*Listbox.background", CARD)
        r.option_add("*TCombobox*Listbox.foreground", FG)
        r.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        r.option_add("*TCombobox*Listbox.selectForeground", "#1b1b1b")
        r.option_add("*TCombobox*Listbox.font", self.f_txt)
        r.configure(bg=BG)
        r.minsize(int(1100 * k), int(700 * k))

        # --- status bar (bottom): progress, status, hint for the active tool
        sbar = tk.Frame(r, bg=BG)
        sbar.pack(side="bottom", fill="x")
        self.bar = ttk.Progressbar(sbar, mode="determinate", maximum=1000, value=0,
                                   style="AI.Horizontal.TProgressbar")
        self.bar.pack(fill="x")
        row = tk.Frame(sbar, bg=BG)
        row.pack(fill="x", padx=int(16 * k), pady=(int(5 * k), int(8 * k)))
        self.status = tk.Label(row, text="", font=self.f_small, fg=ACCENT, bg=BG)
        self.status.pack(side="left")
        self.hint_lbl = tk.Label(row, text="", font=self.f_small, fg=DIM, bg=BG)
        self.hint_lbl.pack(side="right")

        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True)

        # --- side panel (right)
        side = tk.Frame(body, bg=SIDE, width=self.side_w)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        sp = tk.Frame(side, bg=SIDE)
        sp.pack(fill="both", expand=True, padx=int(14 * k), pady=(0, int(14 * k)))

        _hdr, sel = self.section(sp, _("Selection"))
        seg = tk.Frame(sel, bg=LINE)
        seg.pack(fill="x")
        self.tool_btns = {}
        for i, (name, text) in enumerate((("sam", "◎  " + _("SAM click")), ("brush", "✎  " + _("Brush")),
                                                 ("erase", "⌫  " + _("Eraser")))):
            b = self.button(seg, text, lambda n=name: self.set_tool(n), small=True)
            b.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 1, 0))
            seg.columnconfigure(i, weight=1)
            self.tool_btns[name] = b
        srow = tk.Frame(sel, bg=CARD)
        srow.pack(fill="x", pady=(int(10 * k), 0))
        tk.Label(srow, text=_("Size"), font=self.f_small, fg=DIM, bg=CARD).pack(side="left")
        self.size_lbl = tk.Label(srow, text="", font=self.f_small, fg=FG, bg=CARD, width=6, anchor="e")
        self.size_lbl.pack(side="right")
        self.size_scale = ttk.Scale(srow, from_=0, to=100, orient="horizontal", style="AI.Horizontal.TScale",
                                    command=self.on_size_scale)
        self.size_scale.pack(side="left", fill="x", expand=True, padx=int(8 * k))
        urow = tk.Frame(sel, bg=CARD)
        urow.pack(fill="x", pady=(int(10 * k), 0))
        self.undo_btn = self.button(urow, "↶  " + _("Undo"), self.undo, small=True)
        self.undo_btn.pack(side="left", fill="x", expand=True)
        self.clear_btn = self.button(urow, _("Clear"), self.clear, small=True)
        self.clear_btn.pack(side="left", fill="x", expand=True, padx=(int(6 * k), 0))

        _hdr, gen = self.section(sp, _("Generate"))
        tk.Label(gen, text=_("Model"), font=self.f_small, fg=DIM, bg=CARD).pack(anchor="w")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(gen, textvariable=self.model_var, state="readonly", style="AI.TCombobox",
                                      font=self.f_txt)
        self.model_box.pack(fill="x", pady=(int(3 * k), 0))
        self.model_info = tk.Label(gen, font=self.f_small, fg=DIM, bg=CARD, justify="left", anchor="w",
                                   wraplength=self.side_w - int(56 * k))
        self.model_info.pack(fill="x", pady=(int(6 * k), int(10 * k)))
        self.model_box.bind("<<ComboboxSelected>>", lambda e: self.root.focus_set())
        self.model_var.trace_add("write", lambda *a: self.on_model_change())  # any change, also from code
        tk.Label(gen, text=_("What to put there (optional)"), font=self.f_small, fg=DIM, bg=CARD).pack(anchor="w")
        self.prompt = HintEntry(gen, _("in English, e.g. dark doorway, old plaster wall"), font=self.f_txt, bg=BTN,
                                fg=FG, insertbackground=FG, relief="flat", highlightthickness=1,
                                highlightbackground=LINE, highlightcolor=ACCENT)
        self.prompt.pack(fill="x", pady=(int(3 * k), int(10 * k)), ipady=int(5 * k))
        vrow = tk.Frame(gen, bg=CARD)
        vrow.pack(fill="x")
        tk.Label(vrow, text=_("Variants"), font=self.f_small, fg=DIM, bg=CARD).pack(side="left")
        self.count = Stepper(vrow, int(A.setting("variants", self.args.variants or 4)), 1, 8, self)
        self.count.pack(side="right")
        self.gen_btn = self.button(gen, _("Remove selection") + "  ⏎", self.remove_selection, kind="accent")
        self.gen_btn.configure(state="disabled", font=self.f_bold)
        self.gen_btn.pack(fill="x", pady=(int(12 * k), 0))
        self.refresh_models()

        self.rows_hdr, rows = self.section(sp, _("Removals"))
        self.rows = Scroll(rows, height=int((self.ROWTHUMB + 16 * k) * 3), width=self.side_w - int(60 * k))
        self.rows.pack(fill="x")
        self.rows_empty = tk.Label(self.rows.inner, font=self.f_small, fg=DIM, bg=CARD, justify="left",
                                   text=_("None yet: select something on the photo\nand press \"Remove selection\"."))
        self.rows_empty.pack(anchor="w", pady=4)

        self.var_title, vars_ = self.section(sp, _("Variants"), expand=True)
        self.vars = Scroll(vars_, height=int(200 * k), width=self.side_w - int(60 * k))
        self.vars.pack(fill="both", expand=True)
        vb = tk.Frame(vars_, bg=CARD)
        vb.pack(fill="x", pady=(int(8 * k), 0))
        self.more_btn = self.button(vb, "＋ " + _("More variants"), self.more, small=True)
        self.more_btn.configure(state="disabled")
        self.more_btn.pack(side="left", fill="x", expand=True)
        self.del_btn = self.button(vb, _("Delete removal"), self.delete_cur, small=True)
        self.del_btn.configure(state="disabled")
        self.del_btn.pack(side="left", fill="x", expand=True, padx=(int(6 * k), 0))

        foot = tk.Frame(sp, bg=SIDE)
        foot.pack(fill="x", pady=(int(14 * k), 0))
        self.save_btn = self.button(foot, _("Save to LightCraft"), self.save, kind="green")
        self.save_btn.configure(state="disabled", font=self.f_bold)
        self.save_btn.pack(fill="x")
        self.button(foot, _("Close"), self.cancel, kind="ghost", small=True).pack(fill="x", pady=(int(6 * k), 0))

        # --- photo (left): header with title and view controls, the zoomable photo
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(int(16 * k), int(12 * k)), pady=(int(12 * k), 0))
        head = tk.Frame(left, bg=BG)
        head.pack(fill="x", pady=(0, int(10 * k)))
        tk.Label(head, text="AI Remove", font=self.font(13, True), fg=ACCENT, bg=BG).pack(side="left")
        self.title = tk.Label(head, text="", font=self.font(13), fg=FG, bg=BG)
        self.title.pack(side="left", padx=(int(10 * k), 0))
        # the window's language, far right: as LightCraft's (Auto) or one of ours; it applies at the next opening
        chosen = A.setting("language", "auto")
        self.lang_code = tk.StringVar(value=chosen if chosen in i18n.LANGUAGES else "auto")
        self.lang_btn = self.button(head, i18n.language().upper() + "  ▾", self.show_lang_menu, small=True)
        self.lang_btn.pack(side="right", padx=(int(14 * k), 0))
        self.lang_menu = tk.Menu(r, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground="#1b1b1b",
                                 selectcolor=ACCENT, bd=0, relief="flat", font=self.f_small)
        self.lang_menu.add_radiobutton(label=_("Auto (as LightCraft)"), value="auto", variable=self.lang_code,
                                       command=self.on_language)
        for code, name in i18n.LANGUAGES.items():
            self.lang_menu.add_radiobutton(label=name, value=code, variable=self.lang_code, command=self.on_language)
        self.zoom_lbl = tk.Label(head, text=_("Fit"), font=self.f_small, fg=DIM, bg=BG, width=7)
        self.button(head, "+", lambda: self.zsel.zoom(1.25), small=True).pack(side="right")
        self.zoom_lbl.pack(side="right")
        self.button(head, "−", lambda: self.zsel.zoom(0.8), small=True).pack(side="right")
        self.button(head, _("Fit"), self.zsel_reset, small=True).pack(side="right", padx=(0, int(6 * k)))
        self.orig_btn = self.button(head, "◐  " + _("Original"), None, small=True)
        self.orig_btn.pack(side="right", padx=(0, int(14 * k)))
        self.orig_btn.bind("<ButtonPress-1>", lambda e: self.set_original(True), add="+")
        self.orig_btn.bind("<ButtonRelease-1>", lambda e: self.set_original(False), add="+")
        self.canvas_sel = tk.Canvas(left, bg=CANVAS, highlightthickness=0, cursor="crosshair")
        self.canvas_sel.pack(fill="both", expand=True, pady=(0, int(10 * k)))
        self.canvas_sel.create_text(10, 10, text=_("Preparing the photo…"), fill=DIM, font=self.f_txt, tags="msg")
        self.zsel = ZoomView(self.canvas_sel, self.on_zoom)
        c = self.canvas_sel
        c.bind("<Configure>", self.on_canvas_resize)
        c.bind("<ButtonPress-1>", self.on_press_any)
        c.bind("<B1-Motion>", self.on_motion)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Motion>", self.on_hover)
        c.bind("<Leave>", lambda e: c.delete("cursor"))
        c.bind(f"<Button-{RIGHT}>", self.on_right_click)
        c.bind(f"<ButtonPress-{MIDDLE}>", lambda e: self.drag_start(c, e))
        c.bind(f"<B{MIDDLE}-Motion>", lambda e: self.drag(self.zsel, e))
        c.bind(f"<ButtonRelease-{MIDDLE}>", lambda e: self.drag_end(c, "crosshair"))

        r.bind_all("<MouseWheel>", self.on_wheel)
        if X11:  # X11 has no wheel event: buttons 4 / 5 are the wheel
            r.bind_all("<Button-4>", lambda e: self.on_wheel(e, 120))
            r.bind_all("<Button-5>", lambda e: self.on_wheel(e, -120))
        r.bind("<Control-z>", lambda e: self.undo())
        if MAC:
            r.bind("<Command-z>", lambda e: self.undo())
        r.bind("<Return>", lambda e: self.remove_selection())
        for keys, f in ((("plus", "equal", "KP_Add"), 1.25), (("minus", "KP_Subtract"), 0.8), (("0", "KP_0"), 0)):
            for key in keys:
                r.bind(f"<KeyPress-{key}>", lambda e, f=f: self.on_zoom_key(e, f))
                r.bind(f"<Control-KeyPress-{key}>", lambda e, f=f: self.on_zoom_key(e, f, ctrl=True))
                if MAC:
                    r.bind(f"<Command-KeyPress-{key}>", lambda e, f=f: self.on_zoom_key(e, f, ctrl=True))
        for key, tool in (("s", "sam"), ("b", "brush"), ("e", "erase")):
            r.bind(f"<KeyPress-{key}>", lambda e, t=tool: self.on_tool_key(t))
        r.bind("<KeyPress-bracketleft>", lambda e: self.on_size_key(0.8))
        r.bind("<KeyPress-bracketright>", lambda e: self.on_size_key(1.25))
        r.bind("<KeyPress-backslash>", lambda e: None if self.typing() else self.set_original(True))
        r.bind("<KeyRelease-backslash>", lambda e: self.set_original(False))
        self.space = False
        r.bind("<KeyPress-space>", self.on_space)
        r.bind("<KeyRelease-space>", lambda e: setattr(self, "space", False))
        self.drag_xy = None

    def show_lang_menu(self):
        b = self.lang_btn
        self.lang_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def on_language(self, e=None):
        code = self.lang_code.get()
        A.remember("language", code)
        self.root.focus_set()
        new = code if code != "auto" else (i18n.lightcraft_language() or i18n.system_language() or i18n.SOURCE)
        if new != i18n.language():
            self.set_idle_status(_("The language changes the next time AI Remove opens"))

    def on_canvas_resize(self, e):
        if self.zsel.img is not None:
            self.zsel.render()
        else:
            self.canvas_sel.coords("msg", e.width / 2, e.height / 2)

    def zsel_reset(self):
        self.zsel.reset()

    def refresh_models(self):
        """Model names with what one variant takes on this PC (from the last runs)."""
        keys = self.model_keys()
        cur = self.model_key() if self.model_var.get() else A.setting("model", keys[0])
        cur = cur if cur in keys else keys[0]
        self.model_labels = {
            "sdxl": _("SDXL · ~{time}/variant", time=self.fmt_s(A.expected("sdxl_variant"))),
            "flux": _("FLUX Fill · ~{time}/variant", time=self.fmt_s(A.expected("flux_variant"))),
            "lama": _("LaMa only · ~{time}", time=self.fmt_s(A.expected("lama")))}
        self.model_box.configure(values=[self.model_labels[k] for k in keys])
        self.model_var.set(self.model_labels[cur])
        self.show_model_info()

    def model_keys(self):
        """Models installed and sensible on this computer (LaMa always)."""
        if not hasattr(self, "_keys"):
            self._keys = [k for k in MODEL_KEYS if k == "lama" or engines.usable(k)]
        return self._keys

    def show_model_info(self):
        """What the selected model is good at, in one or two lines under the menu."""
        flux = A.expected("flux_variant")
        info = {
            "lama": _("LaMa — on the processor, a single result in ~{time}. It continues what is around (wall, sky, "
                      "lawn, tarmac): very good for small and medium objects on plain or repetitive backgrounds. On "
                      "large areas or structures (doors, windows, people in front of buildings) it tends to blur.",
                      time=self.fmt_s(A.expected("lama"))),
            "sdxl": (_("SDXL — on the processor (no GPU: slow), ~{time} per variant, each one different.",
                       time=self.fmt_s(A.expected("sdxl_variant"))) if engines.device() == "cpu" else
                     _("SDXL — on the GPU, ~{time} per variant, each one different.",
                       time=self.fmt_s(A.expected("sdxl_variant"))))
            + " " + _("It invents new content that fits the scene: good for medium areas with detail. Sometimes it "
                      "adds things that were not there: make 3–4 and pick one. Text in English guides it (e.g. "
                      "\"dark doorway\")."),
            "flux": _("FLUX Fill — the most realistic: it respects light, perspective and the lines of architecture; "
                      "best for large or difficult areas and when SDXL invents odd things. ~{time} per variant (Turbo, "
                      "8 steps). It takes almost the whole GPU: switching to FLUX unloads SDXL and SAM (~15 s the first "
                      "time; SAM reloads by itself at the next click).", time=self.fmt_s(flux))}
        if hasattr(self, "model_info"):
            self.model_info.configure(text=info[self.model_key()])

    def model_key(self):
        v = self.model_var.get()
        return next((k for k, lbl in getattr(self, "model_labels", {}).items() if lbl == v), self.model_keys()[0])

    def typing(self):
        return self.root.focus_get() in (self.prompt, self.count)

    def update_buttons(self):
        has = self.sel_mask is not None and bool(self.sel_mask.any())
        ready = self.s.raw is not None and not self.writing
        self.gen_btn.configure(state="normal" if (has and ready) else "disabled")
        self.undo_btn.configure(state="normal" if self.history else "disabled")
        self.clear_btn.configure(state="normal" if self.ops else "disabled")
        live = [r for r in self.s.removals if not r.deleted]
        self.save_btn.configure(state="normal" if (ready and any(r.chosen is not None for r in live)) else "disabled",
                                text=_("Update in LightCraft") if self.s.dng_path else _("Save to LightCraft"))
        on = self.cur is not None and not self.cur.deleted and not self.writing
        self.more_btn.configure(state="normal" if on else "disabled")
        self.del_btn.configure(state="normal" if on else "disabled")

    # ------------------------------------------------------------------------------------------ workers
    def post(self, kind, data=None):
        self.events.put((kind, data))

    def worker(self):
        s = self.s
        try:
            self.post("task", _("Reading the photo from LightCraft"))
            s.find()
            self.post("found")
            threading.Thread(target=self.sam_worker, daemon=True).start()
            self.post("task", _("Preparing the photo"))
            self.extracting = True
            try:
                s.prepare()
            finally:
                self.extracting = False
            self.base_ready.set()
            self.post("base")
        except A.Fail as e:
            A.log("ERROR:", e)
            self.base_ready.set()
            self.post("fatal", str(e))
            return
        except Exception:
            A.log("ERROR:", traceback.format_exc())
            self.base_ready.set()
            self.post("fatal", traceback.format_exc(limit=3))
            return
        while True:
            job = self.jobs.get()
            try:
                if job[0] == "new":
                    __, mask, n, model, prompt = job
                    self.run_job(None, mask, n, model, prompt)
                elif job[0] == "more":
                    __, r, n, model, prompt = job
                    if not r.deleted:
                        self.run_job(r, None, n, model, prompt)
                elif job[0] == "save":
                    self.post("job_start", (_("Writing the DNG for LightCraft"), A.expected("save")))
                    self.post("job_part", (_("Saving"), 0.0, A.expected("save")))
                    self.post("saved", s.write_all())
            except Exception as e:
                A.log("ERROR:", traceback.format_exc())
                self.post("error", str(e) if isinstance(e, A.Fail) else traceback.format_exc(limit=3))
            finally:
                self.post("job_end")

    def run_job(self, r, mask, n, model, prompt):
        """A new removal (r None: from mask) or more variants for r, with a progress plan in expected seconds."""
        s = self.s
        parts = []
        if r is None:
            parts.append(("area", _("Preparing the area"), A.expected("area")))
        if model == "lama":  # only the model the user picked runs
            if r is None or not any(c[0] == "LaMa" for c in r.candidates):
                parts.append(("lama", "LaMa", A.expected("lama")))
        else:
            if not s.engine_loaded(model):
                parts.append(("load", _("Loading {model}", model=A.MODELS[model]), A.expected(f"{model}_load")))
            parts += [("variant", f"{A.MODELS[model]} {i + 1}/{n}", A.expected(f"{model}_variant")) for i in range(n)]
        total = sum(p[2] for p in parts)
        self.post("job_start", (f"#{r.id}" if r else _("New removal"), total))
        done = 0.0
        for kind, label, secs in parts:
            if r is not None and r.deleted:
                break
            tag = f"#{r.id} · {label}" if r is not None else label
            self.post("job_part", (tag, done, secs))
            if kind == "area":
                r = s.new_removal(mask)
                self.post("removal_new", r)
            elif kind == "lama":
                s.run_lama(r)
                self.post("cand", r)
            elif kind == "load":
                s.get_engine(model)
            else:
                base_done = done

                def prog(i, tot, base_done=base_done, secs=secs, tag=tag):
                    self.post("job_exact", (_("{task} · step {i}/{total}", task=tag, i=i, total=tot),
                                            base_done + secs * i / max(1, tot)))
                s.run_model(r, model, prompt, progress=prog)
                self.post("cand", r)
            done += secs
        self.post("models")

    def sam_worker(self):
        try:
            self.base_ready.wait()
            if getattr(self.s, "base", None) is None:
                return
            if not engines.available()["sam3"]:
                self.post("no_sam")
                threading.Thread(target=self.preload_sdxl, daemon=True).start()
                return
            self.s.get_sam()  # loads it and analyses the photo
            self.post("sam_ready")
            threading.Thread(target=self.preload_sdxl, daemon=True).start()
        except Exception:
            A.log("ERROR SAM 3:", traceback.format_exc())
            self.post("error", _("SAM 3 did not start: see {log}", log=A.LOG_FILE))
            return
        while True:
            job = self.clicks.get()
            try:
                sam = self.s.get_sam()  # reloaded if FLUX pushed it off the GPU
                t0 = time.time()
                if job[0] == "new":
                    __, x, y = job
                    m, logit = sam.click(x, y)
                    A.log(f"click ({x:.0f},{y:.0f}) -> {int(m.sum())} px in {time.time() - t0:.2f}s")
                    self.post("obj", {"id": None, "mask": m, "logit": logit, "pts": [(x, y)], "labels": [1]})
                else:  # ("refine", op id, points, labels, previous logit)
                    __, oid, pts, labels, logit = job
                    m, logit = sam.refine(pts, labels, logit)
                    A.log(f"refine object {oid} ({len(pts)} points, {labels.count(0)} excluded) -> "
                          f"{int(m.sum())} px in {time.time() - t0:.2f}s")
                    self.post("obj", {"id": oid, "mask": m, "logit": logit, "pts": pts, "labels": labels})
            except Exception:
                A.log("ERROR click:", traceback.format_exc())
                self.post("error", traceback.format_exc(limit=2))

    def preload_sdxl(self):
        if os.environ.get("AIREMOVE_TEST_NO_SDXL"):
            return
        try:
            if self.model_key() == "sdxl" and engines.device() != "cpu":
                self.s.load_sdxl()
        except Exception:
            A.log("ERROR loading SDXL:", traceback.format_exc())

    # ------------------------------------------------------------------------------------------ events
    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                getattr(self, "on_" + kind)(data)
        except queue.Empty:
            pass
        self.update_progress()
        self.root.after(120, self.poll)

    def update_progress(self):
        j = self.job
        if j is None:
            if self.task:
                self.status.configure(text=f"{self.task}…  {time.time() - self.task_t0:.0f}s")
            return
        now = time.time()
        if j["mode"] == "timed":
            done = j["base"] + min(0.95, (now - j["t_part"]) / max(j["secs"], 0.1)) * j["secs"]
        else:
            done = j["exact"]
        frac = min(0.99, done / max(j["total"], 0.1))
        elapsed = now - j["t0"]
        speed = elapsed / done if done > 0.05 * j["total"] else 1.0
        eta = max(0, (j["total"] - done) * speed)
        queued = self.jobs.qsize()
        self.bar.configure(value=int(frac * 1000))
        self.status.configure(text=f"{j['label']} · {frac * 100:.0f}% · ~{self.fmt_s(eta)}"
                                   + (" · " + _n("{n} queued", "{n} queued", queued) if queued else ""))

    @staticmethod
    def fmt_s(s):
        return f"{s:.0f} s" if s < 90 else f"{s / 60:.1f} min"

    def on_task(self, text):
        self.task, self.task_t0 = text, time.time()

    def set_idle_status(self, text):
        self.task, self.job = "", None
        self.bar.configure(value=0)
        self.status.configure(text=text)

    def on_job_start(self, data):
        label, total = data
        self.busy = True
        self.job = {"label": label, "total": total, "t0": time.time(), "mode": "timed", "base": 0.0, "secs": 1.0,
                    "t_part": time.time(), "exact": 0.0}
        self.update_buttons()

    def on_job_part(self, data):
        label, base, secs = data
        if self.job:
            self.job.update(label=label, mode="timed", base=base, secs=secs, t_part=time.time())

    def on_job_exact(self, data):
        label, done = data
        if self.job:
            self.job.update(label=label, mode="exact", exact=done)

    def on_job_end(self, _data):
        if self.jobs.qsize() == 0:
            self.busy = False
            self.set_idle_status(_("Click something else to remove, or \"Save to LightCraft\"")
                                 if self.s.removals else _("Click what you want to remove"))
        self.update_buttons()

    def on_no_sam(self, _data):
        """No SAM 3 model: selection with the brush (and LightCraft's "Rimuovi" masks) only."""
        self.tool_btns["sam"].configure(state="disabled")
        self.set_tool("brush")
        self.set_idle_status(_("SAM 3 is not installed: select with the Brush (or with a \"Remove\" mask in LightCraft)"))

    def on_models(self, _data):
        self.refresh_models()

    def on_found(self, _data):
        self.title.configure(text=self.s.info['file_name'])
        self.prompt.delete(0, "end")
        self.prompt.insert(0, self.s.prompt or "")

    def on_base(self, _data):
        b = self.s.base
        geo = (self.s.info["develop"].get("crop") or {}).get("geometry") or {}
        rc = geo.get("rect")
        self.dim = None
        if rc and not geo.get("angle"):  # dim what the photo's crop leaves out
            h, w = b.height, b.width
            inside = np.zeros((h, w), bool)
            inside[int(rc["y0"] * h):int(np.ceil(rc["y1"] * h)), int(rc["x0"] * w):int(np.ceil(rc["x1"] * w))] = True
            self.dim = ~inside
        self.base_ok = True
        self.comp, self.comp_key = None, None
        self.canvas_sel.delete("msg")
        self.canvas_sel.update_idletasks()
        if self.s.init_mask is not None:  # "Rimuovi" masks made in LightCraft
            self.ops = [self.new_op("add", self.s.init_mask)]
        for rem in self.s.removals:  # reopened project: every removal as it was left
            ys, xs = np.nonzero(outline(rem.mask_e, 2))
            self.outlines[rem.id] = (ys, xs)
            self.add_row(rem)
        if self.s.removals:
            self.select_removal(self.s.removals[-1])
        self.render_main()
        n = len(self.s.removals)
        self.set_idle_status(
            _n("Project reopened: {n} removal — change it or add more",
               "Project reopened: {n} removals — change them or add more", n)
            if n else (_("Click what you want to remove") if self.sam_ready else
                       _("SAM 3 is getting ready: you can click already")))
        self.update_buttons()

    def on_sam_ready(self, _data):
        if not self.task and not self.busy and not self.s.removals:  # keep "Project reopened…" if shown
            self.status.configure(text=_("Click what you want to remove"))
        self.sam_ready = True
        actions = os.environ.get("AIREMOVE_TEST_ACTIONS")  # tests only, see run_test_actions
        if actions and hasattr(self, "base_ok"):
            self.root.after(300, lambda: self.run_test_actions(actions.split(";")))

    def on_obj(self, data):
        fields = {k: data[k] for k in ("logit", "pts", "labels")}
        if data["id"] is None:
            ops = self.ops + [self.new_op("obj", data["mask"], **fields)]
        else:
            idx = next((i for i, o in enumerate(self.ops) if o["id"] == data["id"]), None)
            if idx is None:  # undone in the meantime
                return
            ops = list(self.ops)
            ops[idx] = dict(ops[idx], mask=data["mask"], **fields)
        self.commit(ops)
        if not self.busy and not self.task:
            self.status.configure(text=_("{alt}+click a part to take it out · then \"Remove selection\"", alt=ALT))

    def on_removal_new(self, r):
        ys, xs = np.nonzero(outline(r.mask_e, 2))
        self.outlines[r.id] = (ys, xs)
        self.add_row(r)
        self.select_removal(r)

    def on_cand(self, r):
        self.comp_key = None
        self.dng_dirty = True
        self.update_row(r)
        if r is self.cur:
            self.fill_tiles()
        self.render_main()
        self.update_buttons()
        self.autosave()

    def autosave(self):
        """The project file (all removals and variants) follows every change, in the background."""
        threading.Thread(target=self.s.save_project, daemon=True).start()

    def on_saved(self, data):
        out, nid, updated = data
        self.writing, self.dng_dirty = False, False
        self.set_idle_status((_("{file} updated in LightCraft", file=out.name) if updated else
                              _("{file} created and stacked on the original in LightCraft", file=out.name)) + " ✓")
        self.update_buttons()
        if getattr(self, "quit_after_save", False):
            self.root.after(800, self.quit)

    def on_error(self, msg):
        self.writing = False
        self.update_buttons()
        messagebox.showerror("AI Remove", msg, parent=self.root)

    def on_fatal(self, msg):
        self.set_idle_status("")
        messagebox.showerror("AI Remove", msg, parent=self.root)
        self.quit()

    # ------------------------------------------------------------------------------------------ main view
    def composite(self):
        live = [r for r in self.s.removals if not r.deleted and r.chosen is not None]
        key = tuple((r.id, r.chosen_label()) for r in live)
        if key != self.comp_key:
            self.comp, self.comp_key = self.s.composite(), key
        return self.comp

    def render_main(self):
        if not hasattr(self, "base_ok"):
            return
        a = (self.s.base_arr if self.show_original else self.composite()).copy()
        if not self.show_original:
            for r in self.s.removals:
                if not r.deleted and r.id in self.outlines:
                    ys, xs = self.outlines[r.id]
                    a[ys, xs] = ACCENT_RGB if r is self.cur else WHITE
        sel = np.zeros(a.shape[:2], bool)
        for op in self.ops:
            if op["kind"] == "erase":
                sel &= ~op["mask"]
            else:
                sel |= op["mask"]
        self.sel_mask = sel
        if sel.any() and not self.show_original:
            a[sel] = ((a[sel].astype(np.uint16) + np.array(RED, np.uint16)) // 2).astype(np.uint8)
            a[outline(sel, 2)] = RED
        if self.dim is not None:
            a[self.dim] = (a[self.dim] * 0.45).astype(np.uint8)
        self.zsel.set_image(Image.fromarray(a), keep=True)
        self.canvas_sel.tag_raise("cursor")

    def draw_labels(self):
        c = self.canvas_sel
        c.delete("labels")
        if self.show_original:
            return
        for r in self.s.removals:
            if r.deleted:
                continue
            ys, xs = np.nonzero(r.mask_e[::4, ::4])
            if len(ys) == 0:
                continue
            x, y = self.zsel.to_canvas(xs.mean() * 4, ys.min() * 4)
            col = "#e8c35a" if r is self.cur else "#f0f0f0"
            c.create_text(x + 1, y - 9, text=f"#{r.id}", fill="#000000", font=self.font(11, True), tags="labels")
            c.create_text(x, y - 10, text=f"#{r.id}", fill=col, font=self.font(11, True), tags="labels")

    def set_original(self, on):
        if self.show_original != on and hasattr(self, "base_ok"):
            self.show_original = on
            self.render_main()

    # ------------------------------------------------------------------------------------------ removals panel
    def add_row(self, r):
        self.rows_empty.pack_forget()
        k = self.k
        f = tk.Frame(self.rows.inner, bg=CARD, highlightthickness=2, highlightbackground=CARD, cursor="hand2")
        f.pack(fill="x", pady=2)
        blank = ImageTk.PhotoImage(Image.new("RGB", (self.ROWTHUMB, self.ROWTHUMB), (44, 44, 44)))
        th = tk.Label(f, bg=CARD, image=blank, bd=0)
        th.image = blank
        th.pack(side="left", padx=int(4 * k), pady=int(4 * k))
        txt = tk.Frame(f, bg=CARD)
        txt.pack(side="left", fill="x", expand=True, padx=int(8 * k))
        t1 = tk.Label(txt, text=f"#{r.id}", font=self.f_bold, fg=FG, bg=CARD, anchor="w")
        t1.pack(anchor="w")
        t2 = tk.Label(txt, text=_("queued…"), font=self.f_small, fg=DIM, bg=CARD, anchor="w")
        t2.pack(anchor="w")
        ws = (f, th, txt, t1, t2)
        for w in ws:
            w.bind("<Button-1>", lambda e, r=r: self.select_removal(r))
            w.bind("<Double-Button-1>", lambda e, r=r: self.zoom_to(r))
            w.bind("<Enter>", lambda e, ws=ws: [x.configure(bg=CARD_HI) for x in ws if x is not ws[1]])
            w.bind("<Leave>", lambda e, ws=ws: [x.configure(bg=CARD) for x in ws if x is not ws[1]])
        self.row_widgets[r.id] = (f, th, t1, t2)
        self.update_row(r)

    def update_row(self, r):
        if r.id not in self.row_widgets:
            return
        f, th, t1, t2 = self.row_widgets[r.id]
        n = len(r.candidates)
        t1.configure(text=f"#{r.id}" + (f"  ·  {A.label_text(r.chosen_label())}" if r.chosen is not None else ""))
        t2.configure(text=_n("{n} variant", "{n} variants", n) if n else _("generating…"))
        if r.chosen is not None:
            ph = ImageTk.PhotoImage(self.tile_image(r, r.chosen, self.ROWTHUMB, square=True))
            th.configure(image=ph)
            th.image = ph
        f.configure(highlightbackground=ACCENT if r is self.cur else CARD)

    def tile_image(self, r, idx, size, square=False):
        """Candidate idx of r on the photo around its area (base.png look), as a thumbnail."""
        patch, al = self.s.preview(r, idx)
        Y0, Y1, X0, X1 = r.base_rect
        base = self.s.base_arr[Y0:Y1, X0:X1].astype(np.float32)
        ph, pw = base.shape[:2]
        im = base * (1 - al[:ph, :pw, None]) + patch[:ph, :pw].astype(np.float32) * al[:ph, :pw, None]
        out = Image.fromarray(np.clip(im, 0, 255).astype(np.uint8))
        if square:  # centre crop to a square for the list
            s = min(out.size)
            out = out.crop(((out.width - s) // 2, (out.height - s) // 2, (out.width + s) // 2, (out.height + s) // 2))
            return out.resize((size, size), Image.LANCZOS)
        out.thumbnail((size, size), Image.LANCZOS)
        return out

    def select_removal(self, r):
        self.cur = r
        for rid, (f, *_rest) in self.row_widgets.items():
            f.configure(highlightbackground=ACCENT if rid == r.id else CARD)
        self.var_title.configure(text=_("Variants of #{id}", id=r.id).upper())
        self.fill_tiles()
        self.render_main()
        self.update_buttons()

    def fill_tiles(self):
        for w in self.vars.inner.winfo_children():
            w.destroy()
        self.tiles = []
        r = self.cur
        if r is None:
            return
        if not r.candidates:
            tk.Label(self.vars.inner, text=_("Generating the variants…"), font=self.f_small, fg=DIM, bg=CARD).pack(anchor="w")
            return
        for c in range(2):
            self.vars.inner.columnconfigure(c, weight=1)
        for i, (label, _im) in enumerate(r.candidates):
            ph = ImageTk.PhotoImage(self.tile_image(r, i, self.THUMB))
            on = i == r.chosen
            f = tk.Frame(self.vars.inner, bg=CARD_HI, highlightthickness=2,
                         highlightbackground=ACCENT if on else CARD_HI, cursor="hand2")
            f.grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky="n")
            lb = tk.Label(f, image=ph, bg=CARD_HI, bd=0)
            lb.image = ph
            lb.pack(padx=3, pady=(3, 0))
            cap = tk.Label(f, text=("✓  " if on else "") + A.label_text(label), font=self.f_small, fg=ACCENT if on else FG,
                           bg=CARD_HI)
            cap.pack(pady=(2, 3))
            for w in (f, lb, cap):
                w.bind("<Button-1>", lambda e, i=i: self.choose(i))
                w.bind("<Double-Button-1>", lambda e: self.zoom_to(self.cur))
                w.bind("<Enter>", lambda e, f=f, i=i: f.configure(
                    highlightbackground=ACCENT if i == self.cur.chosen else "#5a5a5a"))
                w.bind("<Leave>", lambda e, f=f, i=i: f.configure(
                    highlightbackground=ACCENT if i == self.cur.chosen else CARD_HI))
            self.tiles.append(f)

    def choose(self, i):
        r = self.cur
        if r is None or i >= len(r.candidates):
            return
        if r.chosen != i:
            self.dng_dirty = True
        r.chosen, r.user_picked = i, True
        A.log(f"#{r.id}: picked {r.chosen_label()}")
        for j, f in enumerate(self.tiles):
            f.configure(highlightbackground=ACCENT if j == i else BG)
        self.update_row(r)
        self.render_main()
        self.update_buttons()
        self.autosave()

    def zoom_to(self, r):
        if r is not None:
            Y0, Y1, X0, X1 = r.base_rect
            self.zsel.zoom_to(Y0, Y1, X0, X1)

    def more(self):
        r = self.cur
        if r is None or r.deleted:
            return
        if self.model_key() == "lama" and any(c[0] == "LaMa" for c in r.candidates):
            self.status.configure(text=_("LaMa always gives the same result: pick SDXL or FLUX for more variants"))
            return
        self.jobs.put(("more", r, self.n_variants(), self.model_key(), self.prompt.get().strip()))
        self.busy = True
        self.update_buttons()

    def delete_cur(self):
        r = self.cur
        if r is None:
            return
        r.deleted = True
        self.dng_dirty = True
        self.autosave()
        f = self.row_widgets.pop(r.id)[0]
        f.destroy()
        self.outlines.pop(r.id, None)
        self.comp_key = None
        self.cur = next((x for x in reversed(self.s.removals) if not x.deleted), None)
        if self.cur:
            self.select_removal(self.cur)
        else:
            self.var_title.configure(text=_("Variants").upper())
            self.fill_tiles()
            self.rows_empty.pack(anchor="w", pady=6)
            self.render_main()
        self.update_buttons()

    def n_variants(self):
        try:
            n = max(1, min(8, int(self.count.get())))
        except ValueError:
            n = 4
        A.remember("variants", n)
        return n

    def on_model_change(self):
        self.show_model_info()
        if getattr(self, "model_labels", None):
            A.remember("model", self.model_key())

    def remove_selection(self):
        if self.sel_mask is None or not self.sel_mask.any() or self.writing or self.s.raw is None:
            return
        self.jobs.put(("new", self.sel_mask.copy(), self.n_variants(), self.model_key(), self.prompt.get().strip()))
        self.ops, self.history, self.pending = [], [], {}
        self.busy = True
        self.render_main()
        self.update_buttons()

    def save(self):
        if self.writing:
            return
        self.writing = True
        self.update_buttons()
        self.jobs.put(("save",))
        if self.busy:
            self.status.configure(text=_("Finishing the generations under way, then saving…"))

    # ------------------------------------------------------------------------------------------ selection
    def new_op(self, kind, mask, **extra):
        self.op_seq += 1
        return dict(kind=kind, mask=mask, id=self.op_seq, **extra)

    def commit(self, ops):
        """Every change of the selection goes through here, so Ctrl+Z can undo it."""
        self.history = (self.history + [self.ops])[-60:]
        self.ops = ops
        self.render_main()
        self.update_buttons()

    def set_tool(self, name):
        self.tool = name
        for n, b in self.tool_btns.items():
            on = n == name
            b._bg, b._hi = (ACCENT, ACCENT_HI) if on else (BTN, BTN_HI)
            b.configure(bg=b._bg, fg="#1b1b1b" if on else FG, activebackground=b._hi)
        self.size_lbl.configure(text=num(self.brush * 100, 1) + " %")
        if not getattr(self, "_scale_busy", False):
            self._scale_busy = True
            self.size_scale.set(100 * np.log(self.brush / 0.002) / np.log(100))
            self._scale_busy = False
        if name == "sam":
            self.hint_lbl.configure(text=_("Click: object  ·  {alt}+click: take a part out  ·  Shift+click: add  ·  "
                                           "right-click: delete  ·  {mod}+wheel: zoom  ·  Space+drag: pan",
                                           alt=ALT, mod=MOD))
            self.canvas_sel.delete("cursor")
        else:
            what = _("Brush: paint what goes") if name == "brush" else _("Eraser: paint what stays")
            self.hint_lbl.configure(text=what + "  ·  " + _("{alt}: swaps  ·  [ ]: size  ·  {mod}+wheel: zoom",
                                                            alt=ALT, mod=MOD))

    def on_size_scale(self, v):
        if getattr(self, "_scale_busy", False):
            return
        self._scale_busy = True
        self.brush = float(0.002 * 100 ** (float(v) / 100))  # 0.2 % .. 20 % of the long edge, log scale
        self.set_tool(self.tool)
        self._scale_busy = False

    def on_tool_key(self, tool):
        if not self.typing():
            self.set_tool(tool)

    def on_size_key(self, f):
        if not self.typing():
            self.brush_size(f)

    def brush_size(self, f):
        self.brush = float(min(max(self.brush * f, 0.002), 0.2))
        self.set_tool(self.tool)
        if self.tool != "sam":
            px, py = self.root.winfo_pointerxy()
            self.on_hover(type("E", (), {"x": px - self.canvas_sel.winfo_rootx(),
                                         "y": py - self.canvas_sel.winfo_rooty()})())

    def brush_radius(self):
        return self.brush * max(self.s.base.size) / 2  # in base.png pixels

    def on_hover(self, e):
        self.canvas_sel.delete("cursor")
        if self.tool == "sam" or not hasattr(self, "base_ok"):
            return
        r = self.brush_radius() * self.zsel.scale()
        for col, w in (("#000000", 3), ("#ffffff", 1)):
            self.canvas_sel.create_oval(e.x - r, e.y - r, e.x + r, e.y + r, outline=col, width=w, tags="cursor")

    def on_press_any(self, e):
        """Left button: Alt (Option) / Shift from the event's modifiers; on a Mac Control+click is the right click."""
        ctrl, shift, alt = mods(e)
        if MAC and (e.state & 0x4):
            return self.on_right_click(e)
        return self.on_press(e, alt=alt, shift=shift)

    def on_press(self, e, alt=False, shift=False):
        self.canvas_sel.focus_set()  # so Space / + / − / [ ] reach the window, not a button
        if self.space:
            self.drag_start(self.canvas_sel, e)
            return
        if not hasattr(self, "base_ok") or self.writing:
            return
        ix, iy = self.zsel.to_image(e.x, e.y)
        if self.tool in ("brush", "erase"):
            kind = "erase" if (self.tool == "erase") != alt else "add"  # Alt flips brush <-> eraser
            self.stroke = {"kind": kind, "pts": [(ix, iy)], "last": (e.x, e.y)}
            self._stroke_segment(e.x, e.y, e.x, e.y)
            return
        W, H = self.s.base.size
        if not (0 <= ix < W and 0 <= iy < H):
            return
        if alt or shift:
            self.refine_click(ix, iy, positive=not alt, e=e)
            return
        rad = 5 * self.k
        self.canvas_sel.create_oval(e.x - rad, e.y - rad, e.x + rad, e.y + rad, outline=ACCENT, width=2, tags="mark")
        self.clicks.put(("new", ix, iy))
        if not self.sam_ready and not self.busy:
            self.status.configure(text=_("SAM 3 is getting ready: the selection follows as soon as it is…"))

    def _stroke_segment(self, x0, y0, x1, y1):
        w = max(1.0, 2 * self.brush_radius() * self.zsel.scale())
        col = "#eb4034" if self.stroke["kind"] == "add" else "#9a9a9a"
        self.canvas_sel.create_line(x0, y0, x1, y1, fill=col, width=w, capstyle="round", tags="stroke")
        self.canvas_sel.tag_raise("cursor")

    def on_motion(self, e):
        if self.drag_xy is not None:
            self.drag(self.zsel, e)
            return
        if self.stroke is None:
            return
        self.stroke["pts"].append(self.zsel.to_image(e.x, e.y))
        lx, ly = self.stroke["last"]
        self._stroke_segment(lx, ly, e.x, e.y)
        self.stroke["last"] = (e.x, e.y)
        self.on_hover(e)

    def on_release(self, e):
        if self.drag_xy is not None:
            self.drag_end(self.canvas_sel, "crosshair")
            return
        if self.stroke is None:
            return
        st, self.stroke = self.stroke, None
        W, H = self.s.base.size
        r = self.brush_radius()
        im = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(im)
        if len(st["pts"]) > 1:
            d.line(st["pts"], fill=255, width=max(1, int(round(2 * r))))
        for x, y in st["pts"]:  # round ends and joints
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        self.canvas_sel.delete("stroke")
        self.commit(self.ops + [self.new_op(st["kind"], np.asarray(im) > 0)])

    def refine_click(self, ix, iy, positive, e=None):
        """Alt+click: the part under the click does not belong to its object · Shift+click: it does (added to the
        object under the click, else to the last one). SAM recomputes that object with all its points."""
        objs = [o for o in self.ops if o["kind"] == "obj"]
        if not objs:
            if positive:
                self.clicks.put(("new", ix, iy))
            return
        target = next((o for o in reversed(objs) if o["mask"][int(iy), int(ix)]), None)
        if target is None:
            if not positive:
                self.status.configure(text=_("{alt}+click a red area to take it out (or use the Eraser)", alt=ALT))
                return
            target = objs[-1]
        pts, labels = self.pending.get(target["id"], (target["pts"], target["labels"]))
        pts, labels = pts + [(ix, iy)], labels + [1 if positive else 0]
        self.pending[target["id"]] = (pts, labels)
        self.clicks.put(("refine", target["id"], pts, labels, target["logit"]))
        if e is not None:
            rad = 5 * self.k
            self.canvas_sel.create_oval(e.x - rad, e.y - rad, e.x + rad, e.y + rad, width=2, tags="mark",
                                        outline="#4cd964" if positive else "#38c6f4")

    def on_right_click(self, e):
        if not hasattr(self, "base_ok"):
            return
        x, y = (int(v) for v in self.zsel.to_image(e.x, e.y))
        W, H = self.s.base.size
        if not (0 <= x < W and 0 <= y < H):
            return
        hit = next((o for o in reversed(self.ops) if o["kind"] != "erase" and o["mask"][y, x]), None)
        if hit is not None:
            self.commit([o for o in self.ops if o is not hit])

    def undo(self):
        if self.history and not self.typing():
            self.ops = self.history.pop()
            self.pending = {}
            self.render_main()
            self.update_buttons()

    def clear(self):
        if self.ops:
            self.commit([])

    # ------------------------------------------------------------------------------------------ zoom and pan
    def on_zoom(self, zv):
        self.zoom_lbl.configure(text=_("whole") if zv.z <= 1.0 else "×" + num(zv.z, 1))
        self.draw_labels()

    def on_wheel(self, e, delta=None):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        d = e.delta if delta is None else delta
        # Windows: multiples of 120 per notch; macOS: small numbers (trackpads send many); X11: +-120 (buttons 4/5)
        steps = max(-3.0, min(3.0, d / 4.0)) if MAC else d / 120
        if not steps:
            return None
        ctrl, shift, alt = mods(e)
        if w is self.canvas_sel:
            x, y = e.x_root - w.winfo_rootx(), e.y_root - w.winfo_rooty()
            if alt and self.tool != "sam":
                self.brush_size(1.15 ** steps)
            elif ctrl:
                self.zsel.zoom(1.25 ** steps, x, y)
            elif shift:
                self.zsel.pan(steps * 80 * self.k, 0)
            else:
                self.zsel.pan(0, steps * 80 * self.k)
            return "break"
        for sc in (self.rows, self.vars):  # the side lists scroll normally
            p = w
            while p is not None and p is not sc:
                p = p.master
            if p is sc:
                sc.canvas.yview_scroll(int(-steps), "units")
                return "break"

    def on_zoom_key(self, e, factor, ctrl=False):
        if not ctrl and self.typing():
            return None  # typing "+", "-" or "0" in a field
        c = self.canvas_sel
        if factor == 0:
            self.zsel.reset()
            return "break"
        px, py = self.root.winfo_pointerxy()
        x, y = px - c.winfo_rootx(), py - c.winfo_rooty()
        inside = 0 <= x < c.winfo_width() and 0 <= y < c.winfo_height()
        self.zsel.zoom(factor, x if inside else None, y if inside else None)
        return "break"

    def on_space(self, e):
        if self.typing():
            return None
        self.space = True
        return "break"

    def drag_start(self, canvas, e):
        self.drag_xy = (e.x, e.y)
        canvas.configure(cursor="fleur")

    def drag(self, zv, e):
        if self.drag_xy is None:
            return
        dx, dy = e.x - self.drag_xy[0], e.y - self.drag_xy[1]
        self.drag_xy = (e.x, e.y)
        zv.pan(dx, dy)

    def drag_end(self, canvas, cursor):
        self.drag_xy = None
        canvas.configure(cursor=cursor)

    # ------------------------------------------------------------------------------------------ tests
    def run_test_actions(self, actions):
        """Tests: drive the window through the real handlers. Actions (coordinates normalized to the photo):
        zoom:f,x,y · click:x,y · alt:x,y · shift:x,y · brush:x1,y1,… · erase:… · size:f · wait:ms · undo · log ·
        snap:n · remove:n[,model 0 sdxl/1 flux/2 lama] · more:n · pick:i · select:id · delete · waitidle · save · quit"""
        if not actions:
            return
        kind, __, arg = actions[0].partition(":")
        vals = [float(v) for v in arg.split(",")] if arg else []
        W, H = self.s.base.size
        delay = 900

        def ev(x, y):
            cx, cy = self.zsel.to_canvas(x * W, y * H)
            return type("E", (), {"x": cx, "y": cy, "state": 0})()
        if kind == "zoom":
            e = ev(vals[1], vals[2])
            self.zsel.zoom(vals[0], e.x, e.y)
            delay = 200
        elif kind in ("click", "alt", "shift"):
            self.set_tool("sam")
            e = ev(vals[0], vals[1])
            self.on_press(e, alt=kind == "alt", shift=kind == "shift")
            self.on_release(e)
        elif kind in ("brush", "erase"):
            self.set_tool(kind)
            pts = [ev(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]
            self.on_press(pts[0])
            for p in pts[1:]:
                self.on_motion(p)
            self.on_release(pts[-1])
            delay = 300
        elif kind == "size":
            self.brush = vals[0]
            self.set_tool(self.tool)
            delay = 50
        elif kind == "wait":
            delay = int(vals[0])
        elif kind == "undo":
            self.undo()
            delay = 300
        elif kind == "log":
            A.log(f"TEST state: selection {len(self.ops)} op {int(self.sel_mask.sum()) if self.sel_mask is not None else 0}"
                  f" px | removals " + ", ".join(f"#{r.id}{'(x)' if r.deleted else ''}:{[c[0] for c in r.candidates]}"
                                                  f"->{r.chosen_label()}" for r in self.s.removals))
            delay = 50
        elif kind == "snap":
            self.zsel.last.save(A.ROOT / "work" / f"snap-{int(vals[0]) if vals else 0}.png")
            delay = 50
        elif kind == "shot":  # the whole window, from the screen (brought on top for a moment)
            from PIL import ImageGrab
            r = self.root
            r.attributes("-topmost", True)
            r.update()
            x, y = r.winfo_rootx(), r.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + r.winfo_width(), y + r.winfo_height())).save(
                A.ROOT / "work" / f"shot-{int(vals[0]) if vals else 0}.png")
            r.attributes("-topmost", False)
            delay = 100
        elif kind == "remove":
            self.count.delete(0, "end")
            self.count.insert(0, str(int(vals[0]) if vals else 1))
            if len(vals) > 1:
                self.model_var.set(self.model_labels[MODEL_KEYS[int(vals[1])]])
            self.remove_selection()
            delay = 500
        elif kind == "more":
            self.count.delete(0, "end")
            self.count.insert(0, str(int(vals[0]) if vals else 1))
            self.more()
            delay = 500
        elif kind == "model":
            self.model_var.set(self.model_labels[MODEL_KEYS[int(vals[0])]])
            delay = 50
        elif kind == "pick":
            self.choose(int(vals[0]))
            delay = 300
        elif kind == "select":
            r = next((x for x in self.s.removals if x.id == int(vals[0])), None)
            if r:
                self.select_removal(r)
            delay = 300
        elif kind == "delete":
            self.delete_cur()
            delay = 300
        elif kind == "waitidle":
            if self.busy or self.jobs.qsize():
                self.root.after(500, lambda: self.run_test_actions(actions))
                return
            delay = 200
        elif kind == "save":
            self.save()
        elif kind == "quit":  # without the "update LightCraft?" question
            A.log("TEST end")
            self.quit()
            return
        self.root.after(delay, lambda: self.run_test_actions(actions[1:]))

    # ------------------------------------------------------------------------------------------ closing
    def cancel(self):
        if self.writing:
            self.status.configure(text=_("Writing the DNG: one moment…"))
            return
        if self.extracting:  # LightCraft's crop/lens are temporarily neutral: wait for the restore
            self.status.configure(text=_("Waiting for LightCraft to restore the development…"))
            self.root.after(300, self.cancel)
            return
        live = any(not r.deleted and r.chosen is not None for r in self.s.removals)
        if self.dng_dirty and live:
            ans = messagebox.askyesnocancel(
                "AI Remove", _("Update the photo in LightCraft with the latest changes?\n\n(The removals and "
                               "variants stay saved in the project next to the RAW anyway: opening AI Remove on this "
                               "photo brings them back.)"), parent=self.root)
            if ans is None:
                return
            if ans:
                self.quit_after_save = True
                self.save()
                return
        A.log("closed")
        self.quit()

    def quit(self):
        try:
            self.s.close()
        finally:
            self.root.destroy()
            A.system.hard_exit(0)  # do not wait for work on the GPU (nor for ROCm's shutdown, which can hang)


ACCENT_RGB = (232, 195, 90)


def run(session, args):
    App(session, args).root.mainloop()
    return 0
