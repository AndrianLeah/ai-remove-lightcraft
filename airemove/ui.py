"""AI Remove window, organised like Lightroom's Generative Remove.

The photo fills the left side and always shows the result: every removal with its chosen variant. Select what to
remove (Clic SAM: SAM 3 outlines the whole object · Alt/Option+click / Shift+click refine it · Pennello + / Gomma −;
or "Descrivi": every instance of what is typed, e.g. "people", each its own object — a right-click drops one),
then "Rimuovi selezione": it becomes removal #n with its own area and its own variants (LaMa, RORem, FLUX Fill or
Qwen-Image).
On the right: the removals; click one to see only its variants, pick one, ask for more or delete it — the other
removals are not touched. "Salva in LightCraft" writes one DNG with all of them, stacked on the original; a photo
opened on its own ("Apri foto…", or AI Remove started without LightCraft) gets it next to the file, "Salva come DNG".
An ordinary picture (JPEG, PNG, TIFF, WebP, HEIC, AVIF) gets a copy in its own format instead of a DNG.
Zoom: Ctrl+wheel (Cmd+wheel on a Mac) or + / −, 0 = whole photo; pan with the wheel, middle button or Space+drag.
With the Brush or the Eraser, Ctrl+wheel (Cmd+wheel) sets its size and Alt+wheel (Option+wheel) zooms.
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
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

import numpy as np
from PIL import Image, ImageDraw, ImageTk
from scipy import ndimage as ndi

import airemove as A
import engines
import i18n
from i18n import _, _n, N_

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
WARN = "#e8955a"  # what a model is not for (model_caveat)
WAITING_RGB = (235, 120, 90)  # the outline of a part still waiting for its model ("Split selection")
PANEL = CARD
RED = (235, 64, 52)
SHADOW_RGB = (56, 198, 244)  # the selection's shadow part ("Include the shadow")
WHITE = (240, 240, 240)
MODEL_KEYS = ["sdxl", "flux", "lama", "osor", "qwen", "rorem", "dai"]  # tests: remove:n,i / model:i use these
# the models' own names, as the menu shows them (variant labels keep their short ones: airemove.MODELS)
MODEL_NAMES = {"sdxl": "SDXL", "flux": "FLUX Fill", "lama": "LaMa", "osor": "OSOR",
               "qwen": "Qwen-Image", "rorem": "RORem", "dai": "DAI"}
# the menu: what fills the selection, quickest first, then what takes the object's shadow too
# the menu: four models, each with a job of its own (model_caveat says what each is not for). SDXL stays an engine
# (RORem runs on its files, "Full detail" without FLUX) and OSOR too ("Include the shadow"), out of the menu: SDXL drew
# a person back where RORem drew none, OSOR's fills are softer than FLUX's after "Include the shadow".
FILL_MENU = ("lama", "rorem", "flux", "qwen")
# then what takes a reflection away instead: "Remove reflections" works on the whole photo with nothing selected
MENU_MODELS = FILL_MENU + A.REFLECTION_MODELS
MODEL_GROUPS = ((N_("Fill the selection"), FILL_MENU), (N_("Remove reflections"), A.REFLECTION_MODELS))
# what the text field is for: what to put there (SDXL, FLUX Fill), the name of what to remove (Qwen-Image: it names
# the selection itself, a name corrects it) or nothing (LaMa and OSOR read no text; RORem works with its
# authors' fixed prompt and no guidance, which a text would hardly steer; DAI has its own fixed prompt)
PROMPT_MODE = {"sdxl": "fill", "flux": "fill", "qwen": "name", "lama": None, "osor": None,
               "rorem": None, "dai": None}
# every model of airemove.ENGINES (the one list of models) has a name, a place in the menu and a text mode here: a model
# added there and forgotten here stops the window at once, instead of a menu that cannot show it
assert (set(MODEL_KEYS) == set(MODEL_NAMES) == set(PROMPT_MODE) == set(A.ENGINES)
        and set(MENU_MODELS) <= set(A.ENGINES)), "ui.py's model tables differ from airemove.ENGINES"


def elide(text, font, width):
    """text shortened in the middle with "…" to fit `width` pixels in `font` (a file name keeps its extension);
    "" when not even a few letters fit."""
    if font.measure(text) <= width:
        return text
    lo, hi = 0, len(text)  # how many characters are kept, half from each end
    while lo < hi:
        n = (lo + hi + 1) // 2
        cut = text[:(n + 1) // 2] + "…" + text[len(text) - n // 2:]
        lo, hi = (n, hi) if font.measure(cut) <= width else (lo, n - 1)
    return "" if lo < 4 else text[:(lo + 1) // 2] + "…" + text[len(text) - lo // 2:]


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


class Panel(tk.Frame):
    """The side panel's body (self.inner): as tall as the window. Content taller than that (a small screen, the
    model's description open) scrolls, with a scrollbar shown only then, over the content's right margin (so the
    content keeps its width and nothing wraps anew); on a taller window the content gets the extra height, so what
    is packed to expand (the variants) grows. fit() follows the content's size: the window calls it on every poll,
    as no event says that a frame's requested size changed."""

    def __init__(self, master, k, bg):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, yscrollincrement=int(24 * k))
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="AI.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.fit())
        self._last, self.scrolls = None, False

    def fit(self):
        req, h, w = self.inner.winfo_reqheight(), self.canvas.winfo_height(), self.canvas.winfo_width()
        if (req, h, w) == self._last or h <= 1:
            return
        self._last = (req, h, w)
        scrolls = req > h
        if scrolls != self.scrolls:
            self.scrolls = scrolls
            if scrolls:
                self.sb.place(relx=1, rely=0, relheight=1, anchor="ne")
            else:
                self.sb.place_forget()
                self.canvas.yview_moveto(0)
        self.canvas.itemconfigure(self.win, width=w, height=max(req, h))
        self.canvas.configure(scrollregion=(0, 0, w, max(req, h)))


class Stepper(tk.Frame):
    """−  N  +  (with the Spinbox methods the window uses: get / delete / insert)."""

    def __init__(self, master, value, lo, hi, app, on_change=None):
        super().__init__(master, bg=CARD)
        self.lo, self.hi, self.on_change = lo, hi, None
        self.minus = app.button(self, "−", lambda: self.set(self.v - 1), small=True)
        self.minus.pack(side="left")
        self.lbl = tk.Label(self, text="", font=app.f_bold, fg=FG, bg=CARD, width=3)
        self.lbl.pack(side="left")
        self.plus = app.button(self, "+", lambda: self.set(self.v + 1), small=True)
        self.plus.pack(side="left")
        self.set(value)
        self.on_change = on_change

    def set(self, v):
        self.v = int(min(max(int(v), self.lo), self.hi))
        self.lbl.configure(text=str(self.v))
        if self.on_change:
            self.on_change()

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

    def set_hint(self, hint):
        """Another grey hint, shown at once if the field is empty (also while it is disabled)."""
        st = self.cget("state")
        self.configure(state="normal")
        self.hint = hint
        if self._ph:
            super().delete(0, "end")
            super().insert(0, hint)
        self.configure(state=st)

    def set_text(self, s):
        """Replaces what is typed (the hint comes back when s is empty)."""
        st = self.cget("state")
        self.configure(state="normal")
        self._in()
        super().delete(0, "end")
        super().insert(0, s)
        if not s and self.focus_get() is not self:
            self._out()
        self.configure(state=st)


class ModelPicker(tk.Frame):
    """The model menu: a button with the chosen model's name, what it is for and its time on this PC; a click opens
    the list, in two groups, each model with what it is best for (a Combobox line was too short to say it)."""

    def __init__(self, master, app, var):
        super().__init__(master, bg=BTN, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        self.app, self.var, self.k = app, var, app.k
        self.meta, self.keys, self.pop = {}, [], None
        k, pad = app.k, int(9 * app.k)
        self.name = tk.Label(self, font=app.f_bold, fg=FG, bg=BTN, anchor="w")
        self.time = tk.Label(self, font=app.f_small, fg=DIM, bg=BTN, anchor="e")
        self.arrow = tk.Label(self, text="▾", font=app.f_txt, fg=FG, bg=BTN)
        self.use = tk.Label(self, font=app.f_small, fg=DIM, bg=BTN, anchor="w")
        # what the model is not for, always in sight (model_caveat): FLUX Fill draws people back into a crowd
        self.caveat = tk.Label(self, font=app.f_small, fg=WARN, bg=BTN, anchor="w", justify="left")
        self.name.grid(row=0, column=0, sticky="w", padx=(pad, 0), pady=(int(5 * k), 0))
        self.time.grid(row=0, column=1, sticky="e", padx=(int(6 * k), 0), pady=(int(5 * k), 0))
        self.arrow.grid(row=0, column=2, rowspan=3, padx=pad)
        self.use.grid(row=1, column=0, columnspan=2, sticky="w", padx=(pad, 0), pady=(0, int(5 * k)))
        self.caveat.grid(row=2, column=0, columnspan=2, sticky="w", padx=(pad, 0), pady=(0, int(5 * k)))
        self.columnconfigure(0, weight=1)
        self.parts = (self, self.name, self.time, self.arrow, self.use, self.caveat)
        for w in self.parts:
            w.bind("<Button-1>", lambda e: self.open())
            w.bind("<Enter>", lambda e: self._paint(BTN_HI))
            w.bind("<Leave>", lambda e: self._paint(BTN))

    def _paint(self, bg):
        for w in self.parts:
            w.configure(bg=bg)

    def set_models(self, meta, keys):
        """meta: model -> (name, what it is for, time); keys: the models installed, in MODEL_KEYS order."""
        self.meta, self.keys = meta, keys
        self.show()

    def show(self):
        m = self.app.model_key()
        name, use, t = self.meta.get(m, ("", "", ""))
        self.name.configure(text=name)
        self.use.configure(text=use)
        self.time.configure(text=t)
        caveat = self.app.model_caveat(m) if m in self.meta else ""
        self.caveat.configure(text="⚠  " + caveat if caveat else "", wraplength=self.app.side_w - int(90 * self.k))
        if caveat:
            self.caveat.grid()
        else:
            self.caveat.grid_remove()

    def open(self):
        if self.pop is not None:
            self.close()
            return
        app, k = self.app, self.k
        top = self.pop = tk.Toplevel(self)
        top.overrideredirect(True)
        top.configure(bg=LINE)
        box = tk.Frame(top, bg=CARD)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        width = max(self.winfo_width(), int(360 * k))
        cur = app.model_key()
        for title, keys in MODEL_GROUPS:
            keys = [m for m in keys if m in self.keys]
            if not keys:
                continue
            tk.Label(box, text=_(title).upper(), font=app.f_head, fg=DIM, bg=CARD, anchor="w").pack(
                fill="x", padx=int(12 * k), pady=(int(9 * k), int(3 * k)))
            for m in keys:
                self._row(box, m, m == cur, width - int(44 * k))
        tk.Frame(box, bg=CARD, height=int(6 * k)).pack()
        top.update_idletasks()
        w, h = max(width, top.winfo_reqwidth()), top.winfo_reqheight()
        x, y = self.winfo_rootx() + self.winfo_width() - w, self.winfo_rooty() + self.winfo_height() + 2
        if y + h > self.winfo_screenheight() - int(40 * k):  # no room below: it opens upwards
            y = max(0, self.winfo_rooty() - h - 2)
        top.geometry(f"{w}x{h}+{max(0, x)}+{y}")
        top.bind("<Escape>", lambda e: self.close())
        top.bind("<ButtonPress>", self._outside, add="+")
        top.focus_force()
        try:
            top.grab_set()  # a click anywhere else in the window closes it
        except tk.TclError:
            pass

    def _row(self, box, m, on, wrap):
        app, k = self.app, self.k
        name, __, t = self.meta[m]  # the list says what the model is best for (model_best), not its short use
        bg = CARD_HI if on else CARD
        f = tk.Frame(box, bg=bg, cursor="hand2")
        f.pack(fill="x", padx=int(5 * k), pady=1)
        bar = tk.Frame(f, bg=ACCENT if on else bg, width=max(2, int(3 * k)))
        bar.pack(side="left", fill="y")
        txt = tk.Frame(f, bg=bg)
        txt.pack(side="left", fill="x", expand=True, padx=int(8 * k), pady=int(6 * k))
        head = tk.Frame(txt, bg=bg)
        head.pack(fill="x")
        a = tk.Label(head, text=name, font=app.f_bold, fg=ACCENT if on else FG, bg=bg, anchor="w")
        a.pack(side="left")
        b = tk.Label(head, text=t, font=app.f_small, fg=DIM, bg=bg, anchor="e")
        b.pack(side="right")
        c = tk.Label(txt, text=app.model_best(m), font=app.f_small, fg=DIM, bg=bg, anchor="w", justify="left",
                     wraplength=wrap)
        c.pack(fill="x")
        ws = (f, txt, head, a, b, c)
        if app.model_caveat(m):  # what it is not for, in the list too: chosen knowing it
            d = tk.Label(txt, text="⚠  " + app.model_caveat(m), font=app.f_small, fg=WARN, bg=bg, anchor="w",
                         justify="left", wraplength=wrap)
            d.pack(fill="x", pady=(int(2 * k), 0))
            ws += (d,)
        for w in ws + (bar,):
            w.bind("<ButtonRelease-1>", lambda e, m=m: self.pick(m))
            w.bind("<Enter>", lambda e, ws=ws: [x.configure(bg=CARD_HI) for x in ws])
            w.bind("<Leave>", lambda e, ws=ws, bg=bg: [x.configure(bg=bg) for x in ws])

    def _outside(self, e):
        t = self.pop
        if t is None:
            return
        x, y = e.x_root, e.y_root
        if not (t.winfo_rootx() <= x < t.winfo_rootx() + t.winfo_width()
                and t.winfo_rooty() <= y < t.winfo_rooty() + t.winfo_height()):
            self.close()

    def pick(self, m):
        self.close()
        if m in self.app.model_labels:
            self.var.set(self.app.model_labels[m])
        self.app.root.focus_set()

    def close(self):
        t, self.pop = self.pop, None
        if t is not None:
            try:
                t.grab_release()
            except tk.TclError:
                pass
            t.destroy()



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
        self.dng_dirty = False  # choices changed since the result (DNG or picture) was last written
        self.busy = self.extracting = self.writing = False
        self.describing = False  # a Describe is on its way (SAM's worker)
        self.sam_ready = False
        self.job = None  # progress of the running job
        self.task, self.task_t0 = "", time.time()
        # the text field holds one of two texts, kept apart: what to put there (SDXL, FLUX Fill) and the name of what
        # to remove (Qwen-Image); PROMPT_MODE says which one the chosen model reads
        self.prompt_text, self.prompt_mode = {"fill": "", "name": ""}, "fill"
        self.qwen_names = {}  # removal id -> what Qwen-Image recognised in its selection
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        r = self.root = tk.Tk(className="airemove")  # WM_CLASS "Airemove": the Linux menu entry matches it
        k = self.k = max(1.0, r.winfo_fpixels("1i") / 96.0)
        self.side_w = int(min(372 * k, max(300 * k, 0.34 * r.winfo_screenwidth())))  # narrower on a narrow screen
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

    def fit_header(self):
        """The top bar on any width (its <Configure>, a photo's name). The view controls stay at the right end of the
        photo's row while the photo's name keeps ~160 px there (or all it needs); on a narrower window they go to a
        row of their own below it. On the photo's row "Open photo…" (on its own) always stays, then, as room allows,
        the photo's
        name (shortened in the middle to fit), "GitHub" (else just ⓘ), the version and, last, the mode of a photo
        opened on its own."""
        W = self.head.winfo_width()
        if W <= 1:
            return
        k = self.k

        def width(lbl, text, pad):  # what a label takes with this text: the text, its own border, its padding
            f = tkfont.Font(font=lbl.cget("font"))
            return (f.measure(text) + lbl.winfo_reqwidth() - f.measure(lbl.cget("text")) + int(pad * k)) if text else 0
        ver, gh_full, gh_short = A.system.VERSION, "ⓘ  GitHub", "ⓘ"
        title_w = width(self.title, self.title_text, 12)
        fixed = self.app_lbl.winfo_reqwidth() + int(18 * k) + (
            self.open_btn.winfo_reqwidth() if self.open_btn.winfo_manager() else 0)
        beside = W - self.head_r.winfo_reqwidth() - int(14 * k)  # the photo's row with the controls on it
        one_row = beside - fixed - width(self.repo_lbl, gh_short, 10) >= min(title_w, int(160 * k))
        if one_row != self.head_one_row:
            self.head_one_row = one_row
            self.head_l.pack_forget()
            self.head_r.pack_forget()
            if one_row:
                self.head_r.pack(side="right")
                self.head_l.pack(side="left", fill="x", expand=True)
            else:
                self.head_l.pack(side="top", fill="x")
                self.head_r.pack(side="top", anchor="e", pady=(int(8 * k), 0))
        room = (beside if one_row else W) - fixed
        mode_w = width(self.mode_lbl, self.mode_text, 8)
        if room >= title_w + width(self.version_lbl, ver, 6) + width(self.repo_lbl, gh_full, 10) + mode_w:
            parts = (ver, gh_full, self.mode_text)
        elif room >= title_w + width(self.version_lbl, ver, 6) + width(self.repo_lbl, gh_full, 10):
            parts = (ver, gh_full, "")
        elif room >= title_w + width(self.version_lbl, ver, 6) + width(self.repo_lbl, gh_short, 10):
            parts = (ver, gh_short, "")
        else:
            parts = ("", gh_short, "")
        self.version_lbl.configure(text=parts[0])
        self.repo_lbl.configure(text=parts[1])
        self.mode_lbl.configure(text=parts[2])
        left = (room - width(self.version_lbl, parts[0], 6) - width(self.repo_lbl, parts[1], 10)
                - width(self.mode_lbl, parts[2], 8) - int(12 * k))
        self.title.configure(text=elide(self.title_text, tkfont.Font(font=self.title.cget("font")), left))

    def fit_status(self):
        """The tool's hint (status bar, right) gives way to the status (left) when both do not fit."""
        need = self.status.winfo_reqwidth() + self.hint_lbl.winfo_reqwidth() + int(24 * self.k)
        show = need <= self.status_row.winfo_width()
        if show != bool(self.hint_lbl.winfo_manager()):
            if show:
                self.hint_lbl.pack(side="right")
            else:
                self.hint_lbl.pack_forget()

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
        st.configure("AI.Horizontal.TScale", troughcolor="#3a3a3a", background=ACCENT, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT, gripcount=0)
        r.configure(bg=BG)
        # small enough for a laptop at 125-150 %: the side panel scrolls (Panel), the header takes two rows (fit_header)
        r.minsize(min(int(840 * k), int(0.95 * r.winfo_screenwidth())),
                  min(int(520 * k), int(0.9 * r.winfo_screenheight())))

        # --- status bar (bottom): progress, status, hint for the active tool
        sbar = tk.Frame(r, bg=BG)
        sbar.pack(side="bottom", fill="x")
        self.bar = ttk.Progressbar(sbar, mode="determinate", maximum=1000, value=0,
                                   style="AI.Horizontal.TProgressbar")
        self.bar.pack(fill="x")
        row = self.status_row = tk.Frame(sbar, bg=BG)
        row.pack(fill="x", padx=int(16 * k), pady=(int(5 * k), int(8 * k)))
        # shown while something is generated: the first variant may be the one, no need to wait for the others
        self.stop_btn = self.button(row, "■  " + _("Stop") + "  (Esc)", self.stop_jobs, small=True)
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
        # Save and Close at the bottom, always in sight; the rest scrolls when the window is too short for it
        foot = tk.Frame(side, bg=SIDE)
        foot.pack(side="bottom", fill="x", padx=int(14 * k), pady=(int(10 * k), int(14 * k)))
        self.panel = Panel(side, k, SIDE)
        self.panel.pack(fill="both", expand=True)
        sp = tk.Frame(self.panel.inner, bg=SIDE)
        sp.pack(fill="both", expand=True, padx=int(14 * k))

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
        # Describe: every instance of what is typed (SAM 3's detector), each its own object in the selection
        drow = tk.Frame(sel, bg=CARD)
        drow.pack(fill="x", pady=(int(8 * k), 0))
        self.describe_entry = HintEntry(drow, _("Describe, in English: people, car, sign…"), font=self.f_txt, bg=BTN,
                                        fg=FG, insertbackground=FG, relief="flat", highlightthickness=1,
                                        highlightbackground=LINE, highlightcolor=ACCENT, disabledbackground=CARD,
                                        disabledforeground="#666666")
        self.describe_entry.pack(side="left", fill="x", expand=True, ipady=int(4 * k))
        self.describe_entry.bind("<Return>", lambda e: (self.describe(), "break")[1])  # not "Remove selection"
        self.describe_btn = self.button(drow, _("Select all"), self.describe, small=True)
        self.describe_btn.pack(side="left", padx=(int(6 * k), 0))
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
        self.shadow_btn = None
        self.shadow_wait, self.shadow_found, self.shadow_next = 0, [], None
        # SAM 3 (Describe "shadow") or OSOR installed: they find the objects' shadows (and reflections)
        if self.s.shadow_model() or engines.installed("sam3"):
            self.shadow_btn = self.button(sel, "☀  " + _("Include the shadow"), self.include_shadow, small=True)
            self.shadow_btn.configure(state="disabled")
            self.shadow_btn.pack(fill="x", pady=(int(6 * k), 0))

        _hdr, gen = self.section(sp, _("Generate"))
        mrow = tk.Frame(gen, bg=CARD)
        mrow.pack(fill="x")
        tk.Label(mrow, text=_("Model"), font=self.f_small, fg=DIM, bg=CARD).pack(side="left")
        # what the model is good at: one click away (the menu itself says it in a few words)
        self.info_btn = tk.Label(mrow, text="ⓘ  " + _("What it does"), font=self.f_small, fg=DIM, bg=CARD,
                                 cursor="hand2")
        self.info_btn.pack(side="right")
        self.info_btn.bind("<Button-1>", lambda e: self.toggle_model_info())
        self.model_var = tk.StringVar()
        self.picker = ModelPicker(gen, self, self.model_var)
        self.picker.pack(fill="x", pady=(int(3 * k), 0))
        wrap = self.side_w - int(56 * k)
        self.model_info = tk.Label(gen, font=self.f_small, fg=DIM, bg=CARD, justify="left", anchor="w",
                                   wraplength=wrap)
        self.info_pad = tk.Frame(gen, bg=CARD, height=int(10 * k))  # the gap when the description is hidden
        self.show_info = bool(A.setting("model_info", False))
        self.place_model_info()
        self.model_var.trace_add("write", lambda *a: self.on_model_change())  # any change, also from code
        # what the field is for depends on the model (apply_prompt_mode): the label says it
        self.prompt_lbl = tk.Label(gen, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                   wraplength=wrap)
        self.prompt_lbl.pack(fill="x")
        self.prompt = HintEntry(gen, "", font=self.f_txt, bg=BTN, fg=FG, insertbackground=FG, relief="flat",
                                highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
                                disabledbackground=CARD, disabledforeground="#666666")
        self.prompt.pack(fill="x", pady=(int(3 * k), int(10 * k)), ipady=int(5 * k))
        # Qwen-Image: what it recognised in the removal shown, which a name in the field corrects
        self.prompt_note = tk.Label(gen, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                    wraplength=wrap)
        vrow = self.vrow = tk.Frame(gen, bg=CARD)
        vrow.pack(fill="x")
        tk.Label(vrow, text=_("Variants"), font=self.f_small, fg=DIM, bg=CARD).pack(side="left")
        self.count = Stepper(vrow, int(A.setting("variants", self.args.variants or 2)), 1, 8, self,
                             on_change=lambda: (self.update_more(), self.n_variants()))  # remembered at once
        self.count.pack(side="right")
        self.gen_btn = self.button(gen, _("Remove selection") + "  ⏎", self.remove_selection, kind="accent")
        self.gen_btn.configure(state="disabled", font=self.f_bold)
        self.gen_btn.pack(fill="x", pady=(int(12 * k), 0))
        # the selection as its parts (airemove.split_selection), each a removal that waits: a model for each, then
        # "Generate" (more_btn); "Remove selection" does the same at once, with the model above for all of them
        self.split_btn = self.button(gen, "✂  " + _("Split into parts: a model for each"), self.split_selection,
                                     small=True)
        self.split_btn.configure(state="disabled")
        self.split_btn.pack(fill="x", pady=(int(6 * k), 0))
        # the same settings, for the removal shown in the panel: its first variants ("Generate", a part that waits),
        # or variants of another model, another text, added to the ones it has (its selection stays as it was)
        self.more_btn = self.button(gen, "", self.more, small=True)
        self.more_btn.configure(state="disabled")
        self.more_btn.pack(fill="x", pady=(int(6 * k), 0))
        # every part still waiting, in their order, with the model above (shown when two or more wait)
        self.all_btn = self.button(gen, "", self.generate_waiting, small=True)
        self.pending_gen = set()  # ids of the removals whose first variants are queued: no longer "waiting"
        self.refresh_models()

        self.rows_hdr, rows = self.section(sp, _("Removals"))
        self.rows = Scroll(rows, height=int((self.ROWTHUMB + 16 * k) * 3), width=self.side_w - int(60 * k))
        self.rows.pack(fill="x")
        self.rows_empty = tk.Label(self.rows.inner, font=self.f_small, fg=DIM, bg=CARD, justify="left",
                                   text=_("None yet: select something on the photo\nand press \"Remove selection\"."))
        self.rows_empty.pack(anchor="w", pady=4)
        self.fit_rows()

        self.var_title, vars_ = self.section(sp, _("Variants"), expand=True)
        self.vars = Scroll(vars_, height=int(200 * k), width=self.side_w - int(60 * k))
        self.vars.pack(fill="both", expand=True)
        vb = tk.Frame(vars_, bg=CARD)
        vb.pack(fill="x", pady=(int(8 * k), 0))
        # a long removal's variants are drawn smaller than the photo: the chosen one redrawn at its resolution
        self.hd_btn = self.button(vb, "✦  " + _("Full detail"), self.full_detail, small=True)
        self.hd_btn.configure(state="disabled")
        self.hd_btn.pack(side="left", fill="x", expand=True)
        self.del_btn = self.button(vb, _("Delete removal"), self.delete_cur, small=True)
        self.del_btn.configure(state="disabled")
        self.del_btn.pack(side="left", fill="x", expand=True, padx=(int(6 * k), 0))
        # what "Full detail" would do for the removal shown, or why it does not apply to it (refine_note)
        self.hd_note = tk.Label(vars_, text="", font=self.f_small, fg=DIM, bg=CARD, anchor="w", justify="left",
                                wraplength=self.side_w - int(56 * k))
        self.hd_note.pack(fill="x", pady=(int(5 * k), 0))

        self.save_btn = self.button(foot, self.save_label(), self.save, kind="green")
        self.save_btn.configure(state="disabled", font=self.f_bold)
        self.save_btn.pack(fill="x")
        self.button(foot, _("Close"), self.cancel, kind="ghost", small=True).pack(fill="x", pady=(int(6 * k), 0))

        # --- photo (left): header with title and view controls, the zoomable photo
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(int(16 * k), int(12 * k)), pady=(int(12 * k), 0))
        head = self.head = tk.Frame(left, bg=BG)
        head.pack(fill="x", pady=(0, int(10 * k)))
        # two groups: the photo's row (name, version, GitHub, "Open photo…", the photo's name) and the view controls,
        # at its right end or, on a narrow window, on a row of their own below (fit_header)
        self.head_l, self.head_r = tk.Frame(head, bg=BG), tk.Frame(head, bg=BG)
        self.head_r.pack(side="right")
        self.head_l.pack(side="left", fill="x", expand=True)
        self.head_one_row = True
        head = self.head_l
        self.app_lbl = tk.Label(head, text="AI Remove", font=self.font(13, True), fg=ACCENT, bg=BG)
        self.app_lbl.pack(side="left")
        # the version, quiet, on the title's baseline: what the user reports and compares with the releases page
        self.version_lbl = tk.Label(head, text=A.system.VERSION, font=self.f_small, fg=DIM, bg=BG)
        self.version_lbl.pack(side="left", anchor="s", padx=(int(6 * k), 0), pady=(0, int(2 * k)))
        # where AI Remove lives: the code, the releases and where to report a problem
        repo = self.repo_lbl = tk.Label(head, text="ⓘ  GitHub", font=self.f_small, fg=DIM, bg=BG, cursor="hand2")
        repo.pack(side="left", anchor="s", padx=(int(10 * k), 0), pady=(0, int(2 * k)))
        repo.bind("<Enter>", lambda e: repo.configure(fg=ACCENT))
        repo.bind("<Leave>", lambda e: repo.configure(fg=DIM))
        repo.bind("<Button-1>", lambda e: (webbrowser.open(f"https://github.com/{A.system.REPO}"), self.status.configure(
            text=_("AI Remove on GitHub: the code, the releases and where to report a problem"))))
        # another photo, from anywhere: AI Remove opens again on it (A.reopen), on its own or as LightCraft's photo
        self.open_btn = self.button(head, _("Open photo…"), self.open_other, small=True)
        if self.s.standalone:  # opened from LightCraft, the photo is LightCraft's: another one is chosen there
            self.open_btn.pack(side="left", padx=(int(14 * k), 0))
        self.title = tk.Label(head, text="", font=self.font(13), fg=FG, bg=BG)
        self.title.pack(side="left", padx=(int(12 * k), 0))
        self.mode_lbl = tk.Label(head, text="", font=self.f_small, fg=DIM, bg=BG)  # a photo opened on its own says so
        self.mode_lbl.pack(side="left", anchor="s", padx=(int(8 * k), 0), pady=(0, int(2 * k)))
        self.title_text = self.mode_text = ""
        # the view controls: the original held down, the zoom, and the window's language, last
        head = self.head_r
        self.orig_btn = self.button(head, "◐  " + _("Original"), None, small=True)
        self.orig_btn.pack(side="left", padx=(0, int(14 * k)))
        self.orig_btn.bind("<ButtonPress-1>", lambda e: self.set_original(True), add="+")
        self.orig_btn.bind("<ButtonRelease-1>", lambda e: self.set_original(False), add="+")
        self.button(head, _("Fit"), self.zsel_reset, small=True).pack(side="left", padx=(0, int(6 * k)))
        self.button(head, "−", lambda: self.zsel.zoom(0.8), small=True).pack(side="left")
        self.zoom_lbl = tk.Label(head, text=_("Fit"), font=self.f_small, fg=DIM, bg=BG, width=7)
        self.zoom_lbl.pack(side="left")
        self.button(head, "+", lambda: self.zsel.zoom(1.25), small=True).pack(side="left")
        # the window's language: as LightCraft's (Auto) or one of ours; it applies at the next opening
        chosen = A.setting("language", "auto")
        self.lang_code = tk.StringVar(value=chosen if chosen in i18n.LANGUAGES else "auto")
        self.lang_btn = self.button(head, i18n.language().upper() + "  ▾", self.show_lang_menu, small=True)
        self.lang_btn.pack(side="left", padx=(int(14 * k), 0))
        self.lang_menu = tk.Menu(r, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground="#1b1b1b",
                                 selectcolor=ACCENT, bd=0, relief="flat", font=self.f_small)
        self.lang_menu.add_radiobutton(label=_("Auto (as LightCraft)"), value="auto", variable=self.lang_code,
                                       command=self.on_language)
        for code, name in i18n.LANGUAGES.items():
            self.lang_menu.add_radiobutton(label=name, value=code, variable=self.lang_code, command=self.on_language)
        self.head.bind("<Configure>", lambda e: self.fit_header())
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
        r.bind("<Escape>", lambda e: self.stop_jobs())
        r.bind("<Left>", lambda e: self.step_variant(-1))
        r.bind("<Right>", lambda e: self.step_variant(1))
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
        """The menu shows each model by name, what it is for and what one variant takes on this PC (from the last
        runs); its list says what each one is best for (model_best), the details go under it (show_model_info)."""
        keys = self.model_keys()
        first = "rorem" if "rorem" in keys else keys[0]  # people and objects, none drawn back: the default
        cur = self.model_key() if self.model_var.get() else A.setting("model", first)
        cur = cur if cur in keys else first  # also a model no longer in the menu (SDXL, OSOR, ObjectClear)

        def each(key):
            return _("~{time} each", time=self.fmt_s(A.expected(key)))
        self.model_meta = {
            "lama": ("LaMa", _("Quick fill · plain backgrounds"), "~" + self.fmt_s(A.expected("lama"))),
            "rorem": ("RORem", _("People and objects · draws no one back"), each("rorem_variant")),
            "flux": ("FLUX Fill", _("Architecture · large areas"), each("flux_variant")),
            "qwen": ("Qwen-Image", _("People and objects · complex backgrounds"), each("qwen_variant")),
            "dai": ("DAI", _("Reflections in glass · whole photo or selection"),
                    "~" + self.fmt_s(A.expected("dai_variant")))}
        # one line per model (tests and the saved setting go by it): its name first
        self.model_labels = {m: f"{n} · {u} · {t}" for m, (n, u, t) in self.model_meta.items()}
        self.picker.set_models(self.model_meta, keys)
        self.model_var.set(self.model_labels[cur])
        self.show_model_info()

    def model_best(self, m):
        """When to choose the model, in the menu's list (short: the details are under the menu, "What it does")."""
        return {
            "lama": _("Small or medium objects on a wall, the sky, a lawn, tarmac. One result, in seconds, on the "
                      "processor."),
            "rorem": _("A person next to others, or with something of theirs left outside the selection: where SDXL "
                       "draws a person or an odd object back, it draws the background. Commercial use allowed."),
            "flux": _("Large or difficult areas: architecture, perspective, light."),
            "qwen": _("A person or an object in front of steps, columns, railings: it names what you selected and "
                      "redraws what is behind it."),
            "dai": _("A photo through glass — a shop window, a display case: it takes away the light the glass "
                     "reflects, over the whole photo (nothing selected) or over the selection.")}[m]


    def model_caveat(self, m):
        """What the model is not for, to choose knowing it (the menu and its list say it, in orange); "" if nothing
        stands out. Seen on this PC's photos: FLUX Fill put tourists back where tourists were in a Pompeii street."""
        return {
            "lama": _("Blurs large areas and structures (doors, windows, people in front of buildings)."),
            "rorem": _("On a long thin hole (a pole) it can leave a seam: there LaMa or FLUX Fill."),
            "flux": _("Not for people: in a street or a crowd it draws people back where they were. For people: "
                      "RORem or Qwen-Image."),
            "qwen": _("Slow: about a minute for the first variant of a removal. Non-commercial licence."),
            "dai": _("For reflections only: it fills nothing. A sharp, bright reflection (trees mirrored in a "
                     "window, the sky in a puddle) is only partly taken away.")}.get(m, "")

    def model_keys(self):
        """The menu's models installed and sensible on this computer (LaMa always), in its order."""
        if not hasattr(self, "_keys"):
            self._keys = [k for k in MENU_MODELS if k == "lama" or engines.usable(k)]
        return self._keys

    def show_model_info(self):
        """What the selected model is good at, in one or two lines under the menu."""
        flux = A.expected("flux_variant")
        info = {
            "lama": _("LaMa — on the processor, a single result in ~{time}. It continues what is around (wall, sky, "
                      "lawn, tarmac): very good for small and medium objects on plain or repetitive backgrounds. On "
                      "large areas or structures (doors, windows, people in front of buildings) it tends to blur.",
                      time=self.fmt_s(A.expected("lama"))),
            "flux": _("FLUX Fill — the most realistic: it respects light, perspective and the lines of architecture; "
                      "best for large or difficult areas. ~{time} per variant (Turbo, 8 steps). It takes almost the "
                      "whole GPU: switching to FLUX unloads RORem and SAM (~15 s the first time; SAM reloads by itself "
                      "at the next click). Non-commercial licence (FLUX.1 [dev]).",
                      time=self.fmt_s(flux)),
            "qwen": _("Qwen-Image — it first recognises what you selected (the progress bar says what), then removes "
                      "it and redraws the scene behind it: steps, columns, railings carry on. For large areas on "
                      "complex backgrounds, where FLUX invents a bush or a blob. ~{time} per variant, ~1 min more for "
                      "the first one of a removal. Select the whole object (a bag, a shadow): what is left outside "
                      "stays. If it names the object wrongly, write its name in English (e.g. \"the lamp post\"). It "
                      "takes almost the whole GPU. Non-commercial licence (Qwen Research).",
                      time=self.fmt_s(A.expected("qwen_variant"))),
            "rorem": _("RORem — SDXL retrained only to remove, ~{time} per variant, each one different. Where SDXL "
                       "draws a person or an odd object back into the hole (the other one of two people, the owner of a "
                       "bag left outside the selection), RORem draws what is behind. On a long thin hole (a pole) or up a "
                       "path it can leave a seam or a rock face: there LaMa or FLUX Fill. It uses SDXL's files. "
                       "Licence Apache-2.0 (commercial use allowed).",
                       time=self.fmt_s(A.expected("rorem_variant"))),
            "dai": _("DAI (Dereflection Any Image) — it finds the light the glass reflects over the photo (the "
                     "street in a shop window, a veil over what is behind it) and takes it away from the RAW itself: "
                     "every detail stays, nothing is redrawn. With nothing selected, the whole photo; with a "
                     "selection, there, fading out around it. ~{time}; its variants take away 75 % of it (closest to "
                     "Lightroom's Remove Reflections), 100 %, 50 %, 125 %. Licence Apache-2.0.",
                     time=self.fmt_s(A.expected("dai_variant")))}
        if hasattr(self, "model_info"):
            self.model_info.configure(text=info[self.model_key()])

    def model_key(self):
        v = self.model_var.get()
        return next((k for k, lbl in getattr(self, "model_labels", {}).items() if lbl == v), self.model_keys()[0])

    def typing(self):
        return self.root.focus_get() in (self.prompt, self.count, self.describe_entry)

    def apply_prompt_mode(self):
        """The text field for the chosen model (PROMPT_MODE): what to put there (SDXL, FLUX Fill), the name of what to
        remove (Qwen-Image), or disabled (LaMa and OSOR read no text). The two texts are kept apart, so
        a name typed for Qwen-Image never reaches SDXL as what to draw."""
        if not hasattr(self, "prompt"):
            return
        m = self.model_key()
        mode = PROMPT_MODE.get(m)
        if mode != self.prompt_mode:
            if self.prompt_mode is not None:
                self.prompt_text[self.prompt_mode] = self.prompt.get()
            self.prompt_mode = mode
            self.prompt.configure(state="normal")
            self.prompt.set_text(self.prompt_text.get(mode, "") if mode else "")
        if mode == "fill":
            self.prompt_lbl.configure(text=_("What to put there (optional)"))
            self.prompt.set_hint(_("in English, e.g. dark doorway, old plaster wall"))
        elif mode == "name":
            self.prompt_lbl.configure(text=_("What to remove (optional: Qwen-Image names it by itself)"))
            self.prompt.set_hint(_("in English, e.g. the lamp post"))
        else:
            self.prompt_lbl.configure(text=_("Text (not used by {model})", model=MODEL_NAMES[m]))
            self.prompt.set_hint(_("{model} needs no text", model=MODEL_NAMES[m]))
        self.prompt.configure(state="normal" if mode else "disabled")
        if mode:  # a model that reads no text (LaMa, RORem): no field
            if not self.prompt.winfo_manager():
                self.prompt_lbl.pack(fill="x", before=self.vrow)
                self.prompt.pack(fill="x", pady=(int(3 * self.k), int(10 * self.k)), ipady=int(5 * self.k),
                                 before=self.vrow)
        else:
            self.prompt_lbl.pack_forget()
            self.prompt.pack_forget()
        self.update_prompt_note()

    def update_prompt_note(self):
        """Under the field, for Qwen-Image: what it recognised in the removal shown (a name typed corrects it)."""
        r = self.cur
        what = self.qwen_names.get(r.id) if r is not None and not r.deleted else None
        text = (_("Recognised in #{id}: {what}. If that is wrong, write the right name above.", id=r.id, what=what)
                if self.prompt_mode == "name" and what and self.prompt.winfo_manager() else "")
        self.prompt_note.configure(text=text)
        if text:
            self.prompt_note.pack(after=self.prompt, fill="x", pady=(0, int(10 * self.k)))
        else:
            self.prompt_note.pack_forget()

    def prompt_for(self, model):
        """The text `model` reads: the field when it holds that kind of text, else the one kept for it."""
        mode = PROMPT_MODE.get(model)
        if mode is None:
            return ""
        return (self.prompt.get() if mode == self.prompt_mode else self.prompt_text.get(mode, "")).strip()

    def update_more(self):
        """The button under "Remove selection": for the removal shown in the panel, with the model, text and number
        set above, its first variants ("Generate", a part that waits: Split) or more of them, added to the ones it
        has (any model: SDXL's next to FLUX's); its selection stays as it was. Then "Generate all" for the parts
        still waiting, when two or more do."""
        if not hasattr(self, "more_btn"):
            return
        r, m = self.cur, self.model_key()
        on = r is not None and not r.deleted and not self.writing
        n = 1 if m == "lama" else int(self.count.get())
        reflect = m in A.REFLECTION_MODELS
        if on and reflect:  # its variants: one per strength, the ones it has not got yet
            n = min(n, len(engines.REFLECTION_STRENGTHS) - r.counts.get(m, 0))
        first = on and self.waiting(r)  # a part that waits for its model: its first variants, the main action
        if not on:
            text = "＋  " + _("More variants for a removal (choose one below)")
        elif r.reflects() and not reflect:  # a reflection taken away gets no fill, a fill no reflection
            text, on = _("#{id} takes a reflection away: choose DAI above for more", id=r.id), False
        elif reflect and not r.reflects():
            text, on = _("#{id} fills a selection: reflections come off a new selection or the whole photo",
                         id=r.id), False
        elif reflect and n <= 0:
            text, on = _("#{id} has a variant at every strength already", id=r.id), False
        elif first:
            text = "▶  " + _n("Generate #{id} with {model} ({n} variant)",
                              "Generate #{id} with {model} ({n} variants)", n, id=r.id, model=MODEL_NAMES[m])
        elif m == "lama" and any(c[0] == "LaMa" for c in r.candidates):
            text, on = _("#{id} has LaMa's result already: choose another model", id=r.id), False
        else:
            text = "＋  " + _n("{n} more for #{id} with {model}", "{n} more for #{id} with {model}", n, id=r.id,
                               model=MODEL_NAMES[m])
        b = self.more_btn
        b._bg, b._hi = (ACCENT, ACCENT_HI) if first else (BTN, BTN_HI)
        b.configure(text=text, state="normal" if on else "disabled", bg=b._bg, activebackground=b._hi,
                    fg="#1b1b1b" if first else FG, font=self.f_bold if first else self.f_small)
        rest = [x for x in self.s.removals if self.waiting(x)]
        if len(rest) >= 2 and not self.writing:
            self.all_btn.configure(text="▶▶  " + _("Generate all {n} waiting with {model}", n=len(rest),
                                                   model=MODEL_NAMES[m]))
            self.all_btn.pack(fill="x", pady=(int(6 * self.k), 0), after=self.more_btn)
        else:
            self.all_btn.pack_forget()

    def waiting(self, r):
        """Whether r is a part that waits for its model: split, never generated, not queued."""
        return not r.deleted and not r.candidates and not r.counts and r.id not in self.pending_gen

    def split_selection(self):
        """"Split into parts": the selection as removals that wait, one per part (airemove.split_selection), each
        with its own area; choose a model for each, then "Generate"."""
        if self.sel_mask is None or not self.sel_mask.any() or self.writing or self.s.raw is None:
            return
        self.jobs.put(("split", self.sel_mask.copy()) + self.selected())
        self.ops, self.history, self.pending = [], [], {}
        self.busy = True
        self.render_main()
        self.update_buttons()

    def on_split_done(self, ids):
        first = next((r for r in self.s.removals if r.id == ids[0]), None) if ids else None
        if first is not None:
            self.select_removal(first)
        self.autosave()
        self.next_status = _n("1 part: choose its model above, then \"Generate\"",
                              "{n} parts, numbered on the photo: select each, choose its model, \"Generate\" (or "
                              "\"Generate all\")", len(ids))

    def generate_waiting(self):
        """"Generate all": every part still waiting, in their order (each sees those before it filled), with the
        model, text and number of variants above."""
        m, n, p = self.model_key(), self.n_variants(), self.prompt_for(self.model_key())
        for r in [x for x in self.s.removals if self.waiting(x)]:
            self.jobs.put(("more", r, n, m, p))
            self.pending_gen.add(r.id)
            self.update_row(r)
        self.busy = True
        self.update_buttons()

    def refine_note(self, why):
        """What "Full detail" would do for the removal shown, or why it does not apply (Session.refine_check)."""
        r = self.cur
        label = A.label_text(r.chosen_label()) if r is not None and r.chosen is not None else ""
        model = MODEL_NAMES.get(self.s.refine_model() or "flux")
        return {
            "nosel": _("Full detail: for a long removal (a pole, a cable, a railing), the chosen variant redrawn at "
                       "the photo's resolution."),
            "ok": _("Full detail redraws {variant} at the photo's resolution with {model}: sharper all along the "
                    "removal.", variant=label, model=model),
            "none": _("Full detail: choose a variant first."),
            "done": _("{variant} is in full detail already.", variant=label),
            "model": _("Full detail needs FLUX Fill or RORem: install one of them."),
            "shape": _("Full detail is only for long removals (a pole, a cable, a railing): on a person or an object, "
                       "redrawing in squares invents things."),
            "sharp": _("Full detail: {variant} is drawn near the photo's resolution already, nothing to gain.",
                       variant=label)}[why]

    def on_qwen_name(self, data):
        rid, what = data
        self.qwen_names[rid] = what
        self.update_prompt_note()

    def update_buttons(self):
        has = self.sel_mask is not None and bool(self.sel_mask.any())
        ready = self.s.raw is not None and not self.writing
        reflect = self.model_key() in A.REFLECTION_MODELS  # the whole photo with nothing selected; never in parts
        self.gen_btn.configure(state="normal" if ((has or reflect) and ready) else "disabled",
                               text=(_("Remove reflections") if reflect else _("Remove selection")) + "  ⏎")
        self.split_btn.configure(state="normal" if (has and ready and not reflect) else "disabled")
        self.undo_btn.configure(state="normal" if self.history else "disabled")
        self.clear_btn.configure(state="normal" if self.ops else "disabled")
        live = [r for r in self.s.removals if not r.deleted]
        self.save_btn.configure(state="normal" if (ready and any(r.chosen is not None for r in live)) else "disabled",
                                text=self.save_label())
        on = self.cur is not None and not self.cur.deleted and not self.writing
        self.update_more()
        self.del_btn.configure(state="normal" if on else "disabled")
        ok, why = self.s.refine_check(self.cur) if on else (False, "nosel")
        self.hd_btn.configure(state="normal" if ok else "disabled")
        self.hd_note.configure(text=self.refine_note(why))
        if self.shadow_btn is not None:
            self.shadow_btn.configure(state="normal" if (has and ready) else "disabled")

    # ------------------------------------------------------------------------------------------ workers
    def post(self, kind, data=None):
        self.events.put((kind, data))

    def worker(self):
        s = self.s
        try:
            self.post("task", _("Reading the photo") if s.standalone else _("Reading the photo from LightCraft"))
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
            threading.Thread(target=lambda: self.post("update", A.update_available()), daemon=True).start()
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
            if job[0] != "save":
                s.stop.clear()  # a Stop pressed before this job was for the one before
            try:
                if job[0] == "new":  # a selection's parts: removals of their own, one after another
                    __, mask, units, described, n, model, prompt = job
                    # a reflection is light over all of the selection: one removal
                    parts = ([mask] if model in A.REFLECTION_MODELS else
                             A.split_selection(mask, s.base_scale, units=units))
                    if len(parts) > 1:
                        A.log(f"selection in {len(parts)} parts, each a removal in its own area")
                    for i, part in enumerate(parts):
                        self.run_job(None, part, n, model, prompt, part=(i + 1, len(parts)),
                                     hints=self.hints_for(part, described))
                elif job[0] == "split":  # the parts as removals that wait for their model (split_selection)
                    __, mask, units, described = job
                    self.post("job_start", (_("Splitting the selection"), 2.0))
                    self.post("job_part", (_("Splitting the selection"), 0.0, 2.0))
                    parts = A.split_selection(mask, s.base_scale, units=units)
                    ids = []
                    for part in parts:
                        r = s.plan_removal(part, self.hints_for(part, described))
                        ids.append(r.id)
                        self.post("removal_new", r)
                        Y0, Y1, X0, X1 = r.base_rect
                        A.log(f"  #{r.id}: area {X1 - X0}x{Y1 - Y0} px in base.png"
                              + (f", described as {', '.join(r.hints)}" if r.hints else ""))
                    A.log(f"selection split into {len(parts)} parts, waiting for their models: "
                          + ", ".join(f"#{i}" for i in ids))
                    self.post("split_done", ids)
                elif job[0] == "more":
                    __, r, n, model, prompt = job
                    if not r.deleted:
                        self.run_job(r, None, n, model, prompt)
                elif job[0] == "refine":
                    __, r, prompt = job
                    if not r.deleted and s.can_refine(r):
                        self.run_refine(r, prompt)
                elif job[0] == "shadow":  # looked for part by part, as the removals will be made
                    __, mask = job
                    model = s.shadow_model()
                    parts = A.split_selection(mask, s.base_scale)
                    secs = ((0 if s.engine_loaded(model) else A.expected(f"{model}_load"))
                            + A.expected("shadow") * len(parts))
                    self.post("job_start", (_("Looking for the shadow"), secs))
                    self.post("job_part", (_("Looking for the shadow"), 0.0, secs))
                    m = None
                    try:
                        m = s.find_shadow(mask, parts=parts)
                    finally:
                        self.post("shadow", m)  # answered even when stopped: on_shadow waits for both finders
                elif job[0] == "save":
                    self.post("job_start", (self.save_task(), A.expected("save")))
                    self.post("job_part", (_("Saving"), 0.0, A.expected("save")))
                    self.post("saved", s.write_all())
            except A.Stopped:
                self.next_status = _("Stopped: the variants already made are kept")
            except Exception as e:
                A.log("ERROR:", traceback.format_exc())
                self.post("error", str(e) if isinstance(e, A.Fail) else traceback.format_exc(limit=3))
            finally:
                self.post("job_end")

    @staticmethod
    def hints_for(part, described):
        """What Describe found in this part ("person", "bag"), once each, in the order it was described."""
        return list(dict.fromkeys(text for m, text in described if (m & part).any()))

    def selected(self):
        """The selection's objects (each Describe instance, SAM click, brush stroke: split_selection's units) and
        what Describe found, as (mask, text)."""
        units = [op["mask"] for op in self.ops if op["kind"] != "erase"]
        return units, [(op["mask"], op["describe"]) for op in self.ops if op.get("describe")]

    def run_job(self, r, mask, n, model, prompt, part=(1, 1), hints=None):
        """A new removal (r None: from mask; part: which of a split selection's parts) or more variants for r, with a
        progress plan in expected seconds."""
        s = self.s

        def variant_secs(kind):  # a long removal's variants are filled in squares: known once its area is
            m = "lama" if kind == "lama" else model
            return s.variant_seconds(r, m) if r is not None else A.expected("lama" if m == "lama" else f"{m}_variant")
        parts = []
        if r is None:
            parts.append(("area", _("Preparing the area"), A.expected("area")))
        elif s.leaks(r):  # made before an area could hold a long selection: it grows first (Session.fit_area)
            parts.append(("fit", _("Preparing the area"), 2 * A.expected("area")))
        elif not s.area_ready(r):  # a reopened removal: its area is rendered from the RAW at its first change
            parts.append(("prep", _("Preparing the area"), A.expected("area")))
        reflect = model in A.REFLECTION_MODELS  # no LaMa with it: nothing is filled
        if (r is not None and not r.candidates and not r.counts and model != "lama" and not reflect and s.thin(r)):
            parts.append(("lama", "LaMa", variant_secs("lama")))  # a part's first variants: as a new removal's
        if model == "lama":  # only the model the user picked runs
            if r is None or not any(c[0] == "LaMa" for c in r.candidates):
                parts.append(("lama", "LaMa", variant_secs("lama")))
        else:
            if not s.engine_loaded(model):
                parts.append(("load", _("Loading {model}", model=A.MODELS[model]), A.expected(f"{model}_load")))
            parts += [("variant", f"{A.MODELS[model]} {i + 1}/{n}", variant_secs("variant")) for i in range(n)]
        total = sum(p[2] for p in parts)
        new = _("New removal") if part[1] == 1 else _("New removal {i} of {n}", i=part[0], n=part[1])
        self.post("job_start", (f"#{r.id}" if r else new, total))
        done = 0.0
        i = -1
        while i + 1 < len(parts):  # parts may change once the area is known
            i += 1
            kind, label, secs = parts[i]
            if r is not None and r.deleted:
                break
            tag = f"#{r.id} · {label}" if r is not None else label
            self.post("job_part", (tag, done, secs))
            if kind in ("area", "fit"):
                if kind == "area":
                    r = s.new_removal(mask, hints, reflection=reflect)
                    self.post("removal_new", r)
                    if model != "lama" and not reflect and s.thin(r):  # a cord, a cable: LaMa in squares is the best
                        # fill, in seconds
                        A.log(f"#{r.id}: long and thin, LaMa too")
                        parts.insert(i + 1, ("lama", "LaMa", 0.0))
                else:
                    s.fit_area(r)
                    self.post("cand", r)
                parts[i + 1:] = [(k, lb, variant_secs(k) if k in ("lama", "variant") else sec)
                                 for k, lb, sec in parts[i + 1:]]
                self.post("job_total", done + secs + sum(p[2] for p in parts[i + 1:]))
            elif kind == "prep":
                s.ensure_area(r)
            elif kind == "lama":
                s.run_lama(r)
                self.post("cand", r)
            elif kind == "load":
                s.get_engine(model)
            else:
                base_done = done

                def prog(step, tot, base_done=base_done, secs=secs, tag=tag, model=model):
                    what = getattr(s.qwen, "what", None) if model == "qwen" else None  # what Qwen-Image recognised
                    task = _("{task} · removing: {what}", task=tag, what=what) if what else tag
                    self.post("job_exact", (_("{task} · step {i}/{total}", task=task, i=step, total=tot),
                                            base_done + secs * step / max(1, tot)))
                s.run_model(r, model, prompt, progress=prog)
                if model == "qwen" and not prompt:  # what it recognised by itself (a name typed is the user's)
                    what = getattr(getattr(s, "qwen", None), "what", None)
                    if what:
                        self.post("qwen_name", (r.id, what))
                self.post("cand", r)
            done += secs
        self.post("models")

    def run_refine(self, r, prompt):
        """"Full detail" on r's chosen variant, with a progress plan in expected seconds."""
        s = self.s
        model = s.refine_model()
        prep = 0.0 if s.area_ready(r) else A.expected("area")  # a reopened removal: its area first
        load = 0.0 if s.engine_loaded(model) else A.expected(f"{model}_load")
        secs = s.refine_seconds(r)  # the squares' plan needs the hole only, not the area image
        tag = f"#{r.id} · " + _("Full detail")
        self.post("job_start", (tag, prep + load + secs))  # one plan, as run_job's
        if prep:
            self.post("job_part", (f"#{r.id} · " + _("Preparing the area"), 0.0, prep))
            s.ensure_area(r)
        if load:
            self.post("job_part", (_("Loading {model}", model=A.MODELS[model]), prep, load))
            s.get_engine(model)
        base = prep + load
        self.post("job_part", (tag, base, secs))

        def prog(i, tot):
            self.post("job_exact", (_("{task} · step {i}/{total}", task=tag, i=i, total=tot),
                                    base + secs * i / max(1, tot)))
        if s.refine(r, prompt, progress=prog) is not None:
            r.user_picked = True
            self.post("cand", r)
        self.post("models")

    def sam_worker(self):
        try:
            have_sam = engines.available()["sam3"]
            if have_sam:
                self.s.load_sam()  # the model loads while the photo is prepared (~4 s, it used to wait for it)
            self.base_ready.wait()
            if getattr(self.s, "base", None) is None:
                return
            if not have_sam:
                self.post("no_sam")
                threading.Thread(target=self.preload_sdxl, daemon=True).start()
                return
            self.s.get_sam()  # analyses the photo
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
                elif job[0] == "describe":  # self.describing ends in on_desc (or on_error), on this window's thread
                    __, text = job
                    masks, scores = sam.describe(text, log=A.log)
                    best = ", ".join(f"{s:.2f}" for s in sorted(scores, reverse=True)[:8])
                    A.log(f"describe \"{text}\": {len(masks)} found (scores {best}) in {time.time() - t0:.2f}s")
                    self.post("desc", {"text": text, "masks": masks})
                elif job[0] == "shadows":  # "Include the shadow": SAM 3's shadows that touch the selection
                    __, sel = job
                    m = None
                    try:
                        masks, __ = sam.describe("shadow", log=A.log)
                        m = A.shadows_touching(masks, sel, self.s.base_scale)
                        A.log(f"shadow (SAM 3): {len(masks)} in the photo, {0 if m is None else int(m.sum())} px "
                              f"touching the selection, in {time.time() - t0:.2f}s")
                    finally:
                        self.post("shadow", m)  # answered even on an error: on_shadow waits for both finders
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
            if self.model_key() in ("rorem", "sdxl") and engines.device() != "cpu":
                self.s.get_engine(self.model_key())
        except Exception:
            A.log("ERROR loading RORem:", traceback.format_exc())

    # ------------------------------------------------------------------------------------------ events
    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                getattr(self, "on_" + kind)(data)
        except queue.Empty:
            pass
        self.update_progress()
        self.panel.fit()  # the side panel's content may have grown or shrunk (a description shown, a note...)
        self.fit_status()
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
        if label != self.save_task():  # a save is not stopped
            self.stop_btn.pack(side="left", padx=(0, int(10 * self.k)), before=self.status)
        self.update_buttons()

    def on_job_total(self, total):
        if self.job:
            self.job["total"] = total

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
            if self.pending_gen:  # a part whose generation failed or was stopped waits again
                self.pending_gen.clear()
                for r in self.s.removals:
                    self.update_row(r)
            self.stop_btn.pack_forget()
            msg, self.next_status = getattr(self, "next_status", None), None
            self.set_idle_status(msg or (_("Click something else to remove, or \"{save}\"", save=self.save_label())
                                         if self.s.removals else _("Click what you want to remove")))
        self.update_buttons()

    def on_update(self, found):
        """A newer AI Remove is out: a note in the header; a click opens its page (its installer keeps the models)."""
        if not found:
            return
        version, url = found
        lbl = tk.Label(self.head, text="↑  " + _("AI Remove {version} is out", version=version), font=self.f_small,
                       fg=ACCENT, bg=BG, cursor="hand2")
        lbl.pack(side="right", padx=(0, int(14 * self.k)))
        lbl.bind("<Button-1>", lambda e: (webbrowser.open(url), self.status.configure(text=_(
            "To update, run the new version's installer: it keeps your models and your projects"))))
        A.log(f"update available: {version}")

    def on_shadow(self, m):
        """A shadow finder's answer ("Include the shadow": SAM 3, OSOR). Once each has answered, what
        they found joins the selection (one step: Undo takes it out)."""
        self.shadow_wait = max(0, self.shadow_wait - 1)
        if m is not None:
            self.shadow_found.append(m)
        if self.shadow_next is not None:  # SAM 3 has answered: OSOR's turn
            self.jobs.put(("shadow", self.shadow_next))
            self.shadow_next = None
            self.busy = True
            self.update_buttons()
        if self.shadow_wait:
            return
        found, self.shadow_found = self.shadow_found, []
        if found and not self.ops:  # the selection was cleared in the meantime
            return
        if found:
            self.commit(self.ops + [self.new_op("add", np.logical_or.reduce(found), shadow=True)])
            msg = _("Shadow added to the selection (blue): \"Remove selection\" removes both · {mod}+Z takes it out",
                    mod=MOD)
        else:
            msg = _("No shadow or reflection found next to the selection")
        if self.busy:  # shown when the job ends
            self.next_status = msg
        else:
            self.status.configure(text=msg)

    def on_no_sam(self, _data):
        """No SAM 3 model: selection with the brush (and LightCraft's "Rimuovi" masks) only."""
        self.tool_btns["sam"].configure(state="disabled")
        self.describe_entry.configure(state="disabled")
        self.describe_btn.configure(state="disabled")
        self.set_tool("brush")
        self.set_idle_status(_("SAM 3 is not installed: select with the Brush") if self.s.standalone else
                             _("SAM 3 is not installed: select with the Brush (or with a \"Remove\" mask in LightCraft)"))

    def on_models(self, _data):
        self.refresh_models()

    def on_found(self, _data):
        self.title_text = self.s.info["file_name"]
        if self.s.standalone:  # said once, where it stays: what this photo is shown with and where it is saved
            self.mode_text = (_("on its own: LightCraft's default development · the DNG goes next to the RAW")
                              if self.s.out_format == "DNG" else
                              _("on its own · the edited copy goes next to the original"))
        self.fit_header()
        self.prompt_text["fill"] = self.s.prompt or ""  # "Remove: <text>" on a LightCraft mask: what to put there
        if self.prompt_mode == "fill":
            self.prompt.set_text(self.prompt_text["fill"])

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
        self.start_test_actions()

    def on_sam_ready(self, _data):
        if not self.task and not self.busy and not self.s.removals:  # keep "Project reopened…" if shown
            self.status.configure(text=_("Click what you want to remove"))
        self.sam_ready = True
        self.start_test_actions()

    def start_test_actions(self):
        """Tests only (run_test_actions): once the photo is shown and SAM 3 is ready, whichever comes last."""
        actions = os.environ.get("AIREMOVE_TEST_ACTIONS")
        if actions and self.sam_ready and hasattr(self, "base_ok") and not getattr(self, "_tests_started", False):
            self._tests_started = True
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

    def describe(self):
        """"Select all": every instance of the typed text, found by SAM 3 (in the worker that does the clicks)."""
        text = self.describe_entry.get().strip()
        if not text or not hasattr(self, "base_ok") or self.writing:
            return
        self.describing = True
        self.clicks.put(("describe", text))
        self.status.configure(text=_("Looking for \"{what}\"…", what=text))

    def on_desc(self, data):
        """Each instance found is its own object in the selection: a right-click drops one, and Undo takes them all
        back in one step."""
        masks, text = data["masks"], data["text"]
        self.describing = False
        if not masks:
            self.status.configure(text=_("Nothing found for \"{what}\": a plain name in English works best (person, "
                                         "car, sign)", what=text))
            return
        self.commit(self.ops + [self.new_op("add", m, describe=text) for m in masks])
        self.status.configure(text=_n("{n} found for \"{what}\": right-click it to keep it, then \"Remove selection\"",
                                      "{n} found for \"{what}\": right-click one to keep it, then \"Remove selection\"",
                                      len(masks), what=text))

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
        out, __, updated = data
        self.writing, self.dng_dirty = False, False
        if self.s.standalone:
            msg = (_("{file} updated, next to the original", file=out.name) if updated else
                   _("{file} saved next to the original", file=out.name))
        else:
            msg = (_("{file} updated in LightCraft", file=out.name) if updated else
                   _("{file} created and stacked on the original in LightCraft", file=out.name))
        self.set_idle_status(msg + " ✓")
        self.update_buttons()
        if getattr(self, "open_after_save", None) is not None:
            self.root.after(800, lambda: self.open_now(self.open_after_save))
        elif getattr(self, "quit_after_save", False):
            self.root.after(800, self.quit)

    def save_label(self):
        """The save button: into LightCraft (stacked, then updated there) or, on its own, the result next to the
        original (a DNG for a RAW, a picture in its own format)."""
        if self.s.standalone:
            fmt = self.s.out_format
            return _("Update the {format} file", format=fmt) if self.s.dng_path else _("Save as {format}", format=fmt)
        return _("Update in LightCraft") if self.s.dng_path else _("Save to LightCraft")

    def save_task(self):
        fmt = self.s.out_format
        return (_("Writing the {format} file", format=fmt) if self.s.standalone else
                _("Writing the {format} file for LightCraft", format=fmt))

    def open_other(self):
        """"Open photo…": another photo, in a new AI Remove (A.reopen); this one offers to save its changes first."""
        if self.writing or self.extracting:
            self.status.configure(text=_("One moment: finishing with this photo first"))
            return
        path = A.ask_photo(self.root)
        if path is None:
            return
        live = any(not r.deleted and r.chosen is not None for r in self.s.removals)
        if self.dng_dirty and live:
            ans = messagebox.askyesnocancel("AI Remove", _("Save the changes to this photo before opening {file}?",
                                                           file=path.name), parent=self.root)
            if ans is None:
                return
            if ans:
                self.open_after_save = path
                self.save()
                return
        self.open_now(path)

    def open_now(self, path):
        A.log(f"opening {path}")
        A.reopen(path)
        self.quit()

    def on_error(self, msg):
        self.writing = self.describing = False
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
                    a[ys, xs] = ACCENT_RGB if r is self.cur else WAITING_RGB if self.waiting(r) else WHITE
        sel = np.zeros(a.shape[:2], bool)
        shd = np.zeros(a.shape[:2], bool)  # the part "Include the shadow" added: tinted blue, not red
        for op in self.ops:
            if op["kind"] == "erase":
                sel &= ~op["mask"]
                shd &= ~op["mask"]
            else:
                sel |= op["mask"]
                if op.get("shadow"):
                    shd |= op["mask"]
        self.sel_mask = sel
        if sel.any() and not self.show_original:
            obj = sel & ~shd
            a[obj] = ((a[obj].astype(np.uint16) + np.array(RED, np.uint16)) // 2).astype(np.uint8)
            a[shd] = ((a[shd].astype(np.uint16) + np.array(SHADOW_RGB, np.uint16)) // 2).astype(np.uint8)
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
            col = "#e8c35a" if r is self.cur else WARN if self.waiting(r) else "#f0f0f0"
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
        self.fit_rows()

    def update_row(self, r):
        if r.id not in self.row_widgets:
            return
        f, th, t1, t2 = self.row_widgets[r.id]
        n = len(r.candidates)
        t1.configure(text=f"#{r.id}" + (f"  ·  {A.label_text(r.chosen_label())}" if r.chosen is not None else ""))
        t2.configure(text=_n("{n} variant", "{n} variants", n) if n else
                     _("waiting: choose a model, then Generate") if self.waiting(r) else
                     (_("generating…") if self.busy else _("no variants")))
        if r.chosen is not None:
            ph = ImageTk.PhotoImage(self.tile_image(r, r.chosen, self.ROWTHUMB, square=True))
        else:  # every variant deleted
            ph = ImageTk.PhotoImage(Image.new("RGB", (self.ROWTHUMB, self.ROWTHUMB), (44, 44, 44)))
        th.configure(image=ph)
        th.image = ph
        f.configure(highlightbackground=ACCENT if r is self.cur else CARD)

    def tile_image(self, r, idx, size, square=False):
        """Candidate idx of r on the photo around what it filled (base.png look), as a square thumbnail: the whole
        hole for an object, a piece of it a few times its width for a pole or a cord (all of a long one would be a
        thin line, and the variants would all look the same)."""
        patch, al = self.s.preview(r, idx)
        Y0, Y1, X0, X1 = r.base_rect
        base = self.s.base_arr[Y0:Y1, X0:X1].astype(np.float32)
        ph, pw = base.shape[:2]
        im = base * (1 - al[:ph, :pw, None]) + patch[:ph, :pw].astype(np.float32) * al[:ph, :pw, None]
        out = Image.fromarray(np.clip(im, 0, 255).astype(np.uint8))
        ys, xs = np.nonzero(al[:ph, :pw] > 0.02)
        if len(ys):
            hh, ww = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
            side = int(min(np.clip(3 * min(hh, ww) + 48, 160, max(hh, ww) + 48), ph, pw))
            cy, cx = (int(ys.mean()), int(xs.mean())) if max(hh, ww) > 4 * min(hh, ww) else \
                ((ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2)
            y0, x0 = int(np.clip(cy - side // 2, 0, ph - side)), int(np.clip(cx - side // 2, 0, pw - side))
            out = out.crop((x0, y0, x0 + side, y0 + side))
        else:
            s = min(out.size)
            out = out.crop(((out.width - s) // 2, (out.height - s) // 2, (out.width + s) // 2, (out.height + s) // 2))
        return out.resize((size, size), Image.LANCZOS)

    def select_removal(self, r):
        self.cur = r
        for rid, (f, *_rest) in self.row_widgets.items():
            f.configure(highlightbackground=ACCENT if rid == r.id else CARD)
        self.var_title.configure(text=_("Variants of #{id}", id=r.id).upper())
        self.fill_tiles()
        self.render_main()
        self.update_buttons()
        self.update_prompt_note()

    def fill_tiles(self):
        for w in self.vars.inner.winfo_children():
            w.destroy()
        self.tiles = []
        r = self.cur
        if r is None:
            return
        if not r.candidates:
            text = (_("Not made yet: choose a model above, then \"Generate #{id}\"", id=r.id) if self.waiting(r) else
                    _("Generating the variants…") if self.busy else
                    _("No variants: add some with \"＋ more for #{id}\" under \"Remove selection\"", id=r.id))
            tk.Label(self.vars.inner, text=text, font=self.f_small, fg=DIM, bg=CARD).pack(anchor="w")
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
                w.bind(f"<Button-{RIGHT}>", lambda e, i=i: self.variant_menu(e, i))
                if MAC:
                    w.bind("<Control-Button-1>", lambda e, i=i: self.variant_menu(e, i))
                w.bind("<Enter>", lambda e, f=f, i=i: self.on_variant_hover(f, i, True))
                w.bind("<Leave>", lambda e, f=f, i=i: self.on_variant_hover(f, i, False))
            self.tiles.append(f)

    def on_variant_hover(self, f, i, inside):
        if self.cur is None:
            return
        f.configure(highlightbackground=ACCENT if i == self.cur.chosen else ("#5a5a5a" if inside else CARD_HI))
        if inside:  # what the variant's thumbnail does, where the tools' hint is
            self.hover_hint = self.hint_lbl.cget("text")
            self.hint_lbl.configure(text=_("Click: use this variant  ·  Double-click: zoom to it  ·  Right-click: delete"))
        elif getattr(self, "hover_hint", None) is not None:
            self.hint_lbl.configure(text=self.hover_hint)
            self.hover_hint = None

    def variant_menu(self, e, i):
        """Right-click on a variant: a menu to delete it."""
        m = tk.Menu(self.root, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground="#1b1b1b", bd=0,
                    relief="flat", font=self.f_small)
        m.add_command(label=_("Delete variant"), command=lambda: self.delete_variant(i))
        m.tk_popup(e.x_root, e.y_root)

    def delete_variant(self, i):
        """The variant goes for good, from the window and from the project. A generation under way may be adding to
        the list (its indices would move): not while one runs."""
        r = self.cur
        if r is None or i >= len(r.candidates):
            return
        if self.busy or self.writing:
            self.status.configure(text=_("Wait for the generation in progress to finish, then delete the variant"))
            return
        was = r.chosen_label()
        self.s.delete_variant(r, i)
        if r.chosen_label() != was:
            self.dng_dirty = True
        self.comp_key = None
        self.update_row(r)
        self.fill_tiles()
        self.render_main()
        self.update_buttons()
        self.autosave()

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

    def step_variant(self, d):
        """← / →: the previous / next variant of the selected removal becomes the chosen one."""
        r = self.cur
        if self.typing() or r is None or r.deleted or not r.candidates:
            return
        i = int(np.clip((r.chosen if r.chosen is not None else 0) + d, 0, len(r.candidates) - 1))
        if i != r.chosen:
            self.choose(i)

    def place_model_info(self):
        if self.show_info:
            self.info_pad.pack_forget()
            self.model_info.pack(after=self.picker, fill="x", pady=(int(6 * self.k), int(10 * self.k)))
        else:
            self.model_info.pack_forget()
            self.info_pad.pack(after=self.picker, fill="x")
        self.info_btn.configure(text="ⓘ  " + (_("Hide") if self.show_info else _("What it does")))

    def toggle_model_info(self):
        self.show_info = not self.show_info
        A.remember("model_info", self.show_info)
        self.place_model_info()

    def fit_rows(self):
        """The removals list as tall as its rows, up to three (then it scrolls): an empty list takes no room from
        the variants."""
        self.rows.inner.update_idletasks()
        one = self.ROWTHUMB + int(16 * self.k)
        self.rows.canvas.configure(height=max(int(0.6 * one), min(self.rows.inner.winfo_reqheight(), 3 * one)))

    def zoom_to(self, r):
        if r is not None:
            Y0, Y1, X0, X1 = r.base_rect
            self.zsel.zoom_to(Y0, Y1, X0, X1)

    def more(self):
        r = self.cur
        if r is None or r.deleted:
            return
        if self.model_key() == "lama" and any(c[0] == "LaMa" for c in r.candidates):
            self.status.configure(text=_("LaMa always gives the same result: pick RORem or FLUX Fill for more "
                                         "variants"))
            return
        m, n = self.model_key(), self.n_variants()
        if (m in A.REFLECTION_MODELS) != r.reflects():  # update_more says why: the button is disabled
            return
        if m in A.REFLECTION_MODELS:  # the strengths it has not got yet
            n = min(n, len(engines.REFLECTION_STRENGTHS) - r.counts.get(m, 0))
            if n <= 0:
                return
        if self.waiting(r):  # a part's first variants: "Generate"
            self.pending_gen.add(r.id)
            self.update_row(r)
        self.jobs.put(("more", r, n, m, self.prompt_for(m)))
        self.busy = True
        self.update_buttons()

    def stop_jobs(self):
        """Stop (Esc): the variant under way ends at its next step and is dropped, the variants already made stay,
        and what was waiting in the queue is dropped too — but a save."""
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
        self.pending_gen.clear()  # parts queued and dropped wait again
        for r in self.s.removals:
            self.update_row(r)
        self.s.stop.set()
        if self.job:
            self.job["label"] = _("Stopping…")
        A.log("stop pressed")

    def full_detail(self):
        """"Full detail": the chosen variant of a long removal, drawn smaller than the photo, redrawn at the photo's
        resolution (Session.refine) as a new variant."""
        r = self.cur
        if r is None or r.deleted or not self.s.can_refine(r):
            return
        self.jobs.put(("refine", r, self.prompt_for(self.s.refine_model() or "flux")))
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
        self.fit_rows()
        self.outlines.pop(r.id, None)
        self.comp_key = None
        self.cur = next((x for x in reversed(self.s.removals) if not x.deleted), None)
        if self.cur:
            self.select_removal(self.cur)
        else:
            self.var_title.configure(text=_("Variants").upper())
            self.fill_tiles()
            self.rows_empty.pack(anchor="w", pady=6)
            self.fit_rows()
            self.render_main()
        self.update_buttons()
        self.update_prompt_note()

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
            self.picker.show()
            self.apply_prompt_mode()
            if hasattr(self, "hd_btn"):  # "Remove selection" / "Remove reflections" (built after the menu)
                self.update_buttons()
            else:
                self.update_more()

    def include_shadow(self):
        """"Include the shadow": SAM 3 finds the shadows that touch the selection (Describe "shadow":
        airemove.shadows_touching), OSOR what goes with each selected object — its shadow, its
        reflection, part by part — and they join the selection, in blue, to check before "Remove selection"."""
        if self.sel_mask is None or not self.sel_mask.any() or self.writing or self.s.raw is None or self.shadow_wait:
            return
        sel = self.sel_mask.copy()
        osor = self.s.shadow_model() is not None  # OSOR: what goes with each object, its reflection too
        self.shadow_wait = int(self.sam_ready) + int(osor)
        if self.sam_ready:  # SAM 3's Describe "shadow" first (a few seconds): loading FLUX for OSOR unloads SAM 3
            self.clicks.put(("shadows", sel))
            self.shadow_next = sel if osor else None  # OSOR's turn comes in on_shadow
        elif osor:
            self.jobs.put(("shadow", sel))
            self.busy = True
        if self.shadow_wait:
            self.status.configure(text=_("Looking for the shadow"))
        self.update_buttons()

    def remove_selection(self):
        """"Remove selection" — or, with DAI, "Remove reflections": from the selection, or with nothing selected from
        the whole photo."""
        m = self.model_key()
        has = self.sel_mask is not None and self.sel_mask.any()
        if not (has or m in A.REFLECTION_MODELS) or self.writing or self.s.raw is None:
            return
        n = self.n_variants()
        if m in A.REFLECTION_MODELS:  # one variant per strength
            n = min(n, len(engines.REFLECTION_STRENGTHS))
        mask = self.sel_mask.copy() if has else np.ones(self.s.base_arr.shape[:2], bool)
        self.jobs.put(("new", mask, *self.selected(), n, m, self.prompt_for(m)))
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
            self.hint_lbl.configure(text=what + "  ·  " + _("{alt}: swaps  ·  {alt}+wheel, + − or [ ]: size  ·  "
                                                            "{mod}+wheel: zoom", alt=ALT, mod=MOD))

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
        __, shift, alt = mods(e)
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
            painting = self.tool != "sam"
            if ctrl:  # Ctrl+wheel (Cmd on a Mac): zoom, whatever the tool
                self.zsel.zoom(1.25 ** steps, x, y)
            elif painting and alt:  # Brush / Eraser: Alt+wheel (Option) sets its size
                self.brush_size(1.15 ** steps)
            elif shift:
                self.zsel.pan(steps * 80 * self.k, 0)
            else:
                self.zsel.pan(0, steps * 80 * self.k)
            return "break"
        # over the side panel: its lists scroll first, then (at their end, or with nothing to scroll) the panel itself
        for sc in (self.rows, self.vars, self.panel):
            if not self.inside(w, sc):
                continue
            top, bottom = sc.canvas.yview()
            if (steps > 0 and top > 0) or (steps < 0 and bottom < 1):
                sc.canvas.yview_scroll(int(-steps) or (-1 if steps > 0 else 1), "units")
                return "break"
        return "break" if self.inside(w, self.panel) else None

    @staticmethod
    def inside(w, parent):
        """Whether widget w is parent or inside it."""
        while w is not None and w is not parent:
            w = w.master
        return w is parent

    def on_zoom_key(self, e, factor, ctrl=False):
        if not ctrl and self.typing():
            return None  # typing "+", "-" or "0" in a field
        if not ctrl and factor and self.tool != "sam":  # Brush / Eraser: + and - set its size; Ctrl + / - zoom
            self.brush_size(1.15 if factor > 1 else 1 / 1.15)
            return "break"
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
        snap:n · shadow · remove:n[,model 1 flux/2 lama/4 qwen/5 rorem/6 dai (MODEL_KEYS)] · more:n · pick:i ·
        detail · dropvar:i · waitvars:n · stop · step:±1 · info · select:id · delete · waitidle · save · quit ·
        menu (opens / closes the model list) · wheel:notches,mods (on the photo; mods 1 Ctrl/Cmd, 2 Alt/Option) ·
        describe:text (Describe's field and "Select all") · right:x,y (a right-click) · split ("Split into parts") ·
        genall ("Generate all … waiting") · geometry:w,h (the window's size, pixels) ·
        panelwheel:notches (over the side panel, negative: down)"""
        if not actions:
            return
        kind, __, arg = actions[0].partition(":")
        vals = [float(v) for v in arg.split(",")] if arg and kind != "describe" else []
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
            if self.picker.pop is not None:  # the model list stays above the window
                self.picker.pop.attributes("-topmost", True)
                self.picker.pop.lift()
            r.update()
            time.sleep(0.2)  # the screen catches up with Tk
            x, y = r.winfo_rootx(), r.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + r.winfo_width(), y + r.winfo_height())).save(
                A.ROOT / "work" / f"shot-{int(vals[0]) if vals else 0}.png")
            r.attributes("-topmost", False)
            delay = 100
        elif kind == "shadow":
            self.include_shadow()
            delay = 500
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
        elif kind == "detail":
            self.full_detail()
            delay = 500
        elif kind == "dropvar":  # as the right-click menu's "Delete variant"
            self.delete_variant(int(vals[0]))
            delay = 300
        elif kind == "waitvars":  # until the selected removal has that many variants
            if self.cur is None or len(self.cur.candidates) < int(vals[0]):
                self.root.after(500, lambda: self.run_test_actions(actions))
                return
            delay = 100
        elif kind == "stop":
            self.stop_jobs()
            delay = 200
        elif kind == "step":  # as the arrow keys
            self.step_variant(int(vals[0]))
            delay = 300
        elif kind == "info":
            self.toggle_model_info()
            delay = 200
        elif kind == "split":  # "Split into parts"
            self.split_selection()
            delay = 300
        elif kind == "genall":  # "Generate all … waiting"
            self.generate_waiting()
            delay = 300
        elif kind == "geometry":  # the window at that size (pixels), not maximized
            self.root.state("normal")
            self.root.geometry(f"{int(vals[0])}x{int(vals[1])}+0+0")
            delay = 1200
        elif kind == "panelwheel":  # notches of the wheel over the side panel (negative: down)
            p = self.panel
            e = type("E", (), {"x_root": p.winfo_rootx() + p.winfo_width() // 2,
                               "y_root": p.winfo_rooty() + p.winfo_height() // 3,
                               "delta": (4 if MAC else 120) * vals[0], "state": 0})()
            self.on_wheel(e)
            A.log(f"TEST panel wheel {vals[0]:+.0f}: view {tuple(round(v, 2) for v in p.canvas.yview())}")
            delay = 300
        elif kind == "describe":
            self.describe_entry.set_text(arg)
            self.describe()
            delay = 200
        elif kind == "right":
            self.on_right_click(ev(vals[0], vals[1]))
            delay = 200
        elif kind == "menu":
            self.picker.open()
            A.log(f"TEST model list {'open' if self.picker.pop is not None else 'closed'}")
            delay = 400
        elif kind == "wheel":
            c = self.canvas_sel
            m = int(vals[1]) if len(vals) > 1 else 0
            state = (0x4 if m & 1 else 0) | (ALT_MASK if m & 2 else 0)
            e = type("E", (), {"x_root": c.winfo_rootx() + c.winfo_width() // 2,
                               "y_root": c.winfo_rooty() + c.winfo_height() // 2,
                               "delta": (4 if MAC else 120) * vals[0], "state": state})()
            self.on_wheel(e)
            A.log(f"TEST wheel {vals[0]:+.0f} mods {m}: tool {self.tool} | brush {self.brush:.4f} | zoom {self.zsel.z:.2f}")
            delay = 200
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
            if self.busy or self.jobs.qsize() or self.describing or self.shadow_wait:
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
            self.status.configure(text=_("Saving: one moment…"))
            return
        if self.extracting and not self.s.standalone:  # LightCraft's crop/lens are neutral for a moment: wait
            self.status.configure(text=_("Waiting for LightCraft to restore the development…"))
            self.root.after(300, self.cancel)
            return
        live = any(not r.deleted and r.chosen is not None for r in self.s.removals)
        if self.dng_dirty and live:
            ask = (_("Save the {format} file with the latest changes?\n\n(The removals and variants stay saved in the "
                     "project next to the photo anyway: opening AI Remove on it brings them back.)",
                     format=self.s.out_format)
                   if self.s.standalone else
                   _("Update the photo in LightCraft with the latest changes?\n\n(The removals and variants stay "
                     "saved in the project next to the photo anyway: opening AI Remove on it brings them back.)"))
            ans = messagebox.askyesnocancel("AI Remove", ask, parent=self.root)
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
