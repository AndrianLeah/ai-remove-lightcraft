"""AI Remove's window opening (ui.App), for the CI runners: tools/ci_smoke.py check DIR runs this with the install's own
Python. DIR's app code is imported; the Session is a stand-in (no photo yet, no models) and the workers do not start.
  - it opens as the app opens it (macOS: "wm state zoomed", which runs the event loop until the window is still; in
    1.8.0 it never returned there, the window flickering at 100 % CPU): within 60 s, with a size of its own, the top bar
    then still;
  - sized by its content (no size of its own: the window before the zoom in 1.8.0), the top bar settles: its choice (one
    row or two) changes the window's width by 1 px at most;
  - the top bar's hysteresis (fit_header, HEAD_HYSTERESIS): two rows below the width one row needs, one row again only
    HEAD_HYSTERESIS px wider; widths wavering inside that band change nothing, a width going back and forth across one
    of its edges changes it once;
  - opened from the panel (master, on_close), back to the panel and reopened (reopen): zoomed again, the top bar still;
  - the buttons (#66): Labels on macOS, in the window's colours (Aqua draws a Button its own grey), and a LabelButton
    behaves as a button on every system;
  - the symbols in the texts (#69), where Tk draws with the X server's own fonts (Linux): each drawn at every size, not
    the server's dotted box (symbols()).
One Tk for the whole test, the app's own window's (macOS's Tk does not take a second one, nor a new one after it): the
other windows are on it, as the panel's are. Exit status 1 at the first check that fails; 0 with "skipped" when there is
no display to open a window on.

  ci_window.py DIR
"""
import faulthandler
import os
import sys
import threading
import time
import traceback
import types
from pathlib import Path

STEP_S = 60  # s for each step at most (all of them take ~15 s here): a window that does not open (#52), or whose
# top bar never settles, ends the test there (Tk then never gives back control: only a thread can)


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what, flush=True)


class Stand(types.SimpleNamespace):
    """What the window reads of a Session before a photo is ready; anything else is not there yet."""

    def __getattr__(self, name):
        return None


def session():
    return Stand(app="LightCraft", standalone=False, removals=[], info={"file_name": "DSC_0042.NEF", "develop": {}},
                 out_format="DNG", prompt="", shadow_model=lambda: None, refine_model=lambda: None)


def buttons(tk, ui, app, r):
    """The window's buttons (#66): on macOS Tk's Aqua theme draws a Button as the system's own, light grey whatever
    bg says, and the window's light text could not be read on it; there they are Labels (ui.LabelButton), in the
    colours asked for. And a LabelButton behaves as a button, here on every system: its command on a click released
    over it, not on one released outside it nor when it is disabled; command set and read again, invoke()."""
    b = app.lang_btn  # one of the window's own (App.button)
    want = "Label" if ui.MAC else "Button"
    expect(b.winfo_class() == want and str(b.cget("bg")).lower() == ui.BTN.lower(),
           f"the window's buttons are {want}s, in the window's colours (bg {b.cget('bg')}, text {b.cget('fg')})")
    calls = []
    top = tk.Toplevel(r)
    lb = ui.LabelButton(top, text="Undo", command=lambda: calls.append(1), bg=ui.BTN, fg=ui.FG,
                        disabledforeground=ui.OFF, overrelief="raised", repeatdelay=0, padx=12, pady=7)
    lb.pack()
    for _ in range(300):  # shown (wait_visibility can miss its event on Windows and never return)
        top.update()
        if lb.winfo_viewable():
            break
        time.sleep(0.01)
    expect(lb.winfo_viewable() and lb.winfo_class() == "Label", "a LabelButton is shown, a Label")

    def click(x=3, y=3, rx=None):
        lb.event_generate("<ButtonPress-1>", x=x, y=y)
        lb.event_generate("<ButtonRelease-1>", x=x if rx is None else rx, y=y)
        top.update()
    click()
    expect(calls == [1], "a LabelButton runs its command on a click released over it")
    click(rx=-20)
    expect(calls == [1], "a press released outside it runs nothing")
    lb.configure(state="disabled")
    click()
    expect(calls == [1] and lb.invoke() is None and calls == [1], "disabled, it runs nothing (click or invoke)")
    lb["state"] = "normal"
    lb.configure(command=lambda: calls.append(2))
    click()
    expect(calls == [1, 2] and callable(lb.cget("command")) and lb["command"] is lb.cget("command"),
           "its command changed (configure) and read back (cget, [])")
    lb.invoke()
    expect(calls == [1, 2, 2] and lb.configure("command")[-1] is lb.cget("command")
           and lb.configure("bg")[-1].lower() == ui.BTN.lower(),
           "invoke() runs it; configure(option) answers as a Button's")
    top.destroy()


BOX = ""  # in no misc-fixed font: the X server draws its default glyph for it, the dotted box
BOLD = "›–—…"  # what the bold texts (the main action, titles, model names) have outside Latin-1


def symbols(tk, ui, app, r, begin):
    """The symbols in the texts (#69). Where Tk draws with the X server's own fonts (X11 without Xft: the Tk of uv's
    Python on Linux), a character shows only if the misc-fixed font Tk takes for its size has it, else the server's
    dotted box. There every character outside Latin-1 that the app's texts can show (its string literals and the
    catalogs, as ui.glyphs() gives them) is drawn at each size from 8 to 26 px and compared with the box (and with Tk's
    \\uXXXX, for one that no font has): none is either, nor in bold the ones bold texts have. The box is seen: the
    symbols ui.CORE_GLYPHS stands in for are boxes at some size. And no text in the window has one of those.
    Elsewhere (Windows, macOS, a Tk with Xft) the symbols stay as they are: skipped. AIREMOVE_CI_SHOTS=DIR: the window
    and the characters drawn, as PNGs there."""
    import ast
    import json
    import unicodedata
    from tkinter import font as tkfont
    try:
        fs = r.tk.call("::tk::pkgconfig", "get", "fontsystem")
    except tk.TclError:
        fs = "?"
    if not ui.CORE_FONTS:
        print(f"  --  the symbols stay as they are: Tk draws with its system's fonts ({fs})")
        return
    from PIL import Image, ImageGrab
    print(f"  Tk's font system: {fs}; the window's text: {r.tk.call('font', 'actual', app.f_txt)}")
    code = Path(ui.__file__).resolve().parent
    texts = []
    for f in sorted(code.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        doc = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)}  # docstrings: not shown
        texts += [n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc]
    for f in sorted((code / "locales").glob("*.json")):
        texts += [v for v in json.loads(f.read_text(encoding="utf-8")).values() if isinstance(v, str)]
    shown = sorted({c for t in texts for c in ui.glyphs(t)
                    if ord(c) > 0xFF and not unicodedata.category(c).startswith("C")})
    replaced = sorted({c for s in ui.CORE_GLYPHS for c in s})

    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)
    left = []
    for w in walk(r):
        try:
            t = str(w.cget("text"))
        except tk.TclError:
            continue
        if any(c in t for c in replaced):
            left.append(t)
    expect(not left, f"no text in the window has a symbol ui.CORE_GLYPHS stands in for {left[:4]}")

    top = tk.Toplevel(r, bg="#000000")
    top.overrideredirect(True)
    top.geometry("+0+0")
    lbl = tk.Label(top, text=BOX, bg="#000000", fg="#ffffff", width=8, anchor="w", padx=2, pady=2)
    lbl.pack()
    for _ in range(300):
        top.update()
        if lbl.winfo_viewable():
            break
        time.sleep(0.01)

    def shot(text):
        lbl.configure(text=text)
        top.update()
        x, y = lbl.winfo_rootx(), lbl.winfo_rooty()
        return ImageGrab.grab((x, y, x + lbl.winfo_width(), y + lbl.winfo_height()))

    boxes, rows = {}, []  # (character, weight) -> the sizes it is a box at; the pictures, for AIREMOVE_CI_SHOTS
    for weight in ("normal", "bold"):
        begin(f"the symbols, {weight}")
        for px in range(8, 27):
            f = tkfont.Font(root=r, family=app.font(10)[0], size=-px, weight=weight)
            lbl.configure(font=f)
            box = shot(BOX).tobytes()
            row = []
            for c in shown + replaced:
                im = shot(c)
                row.append(im)
                if im.tobytes() == box or f.measure(c) == f.measure(f"\\u{ord(c):04X}"):
                    boxes.setdefault((c, weight), []).append(px)
            rows.append(row)
    top.destroy()

    def sizes(c, weight):
        s = boxes.get((c, weight), [])
        return f"{c} {s[0]}-{s[-1]} px" if len(s) == s[-1] - s[0] + 1 else f"{c} {s}" if s else ""
    bad = [sizes(c, "normal") for c in shown if (c, "normal") in boxes]
    bad += [sizes(c, "bold") + " bold" for c in BOLD if (c, "bold") in boxes]
    expect(not bad, f"the {len(shown)} characters the texts can show ({''.join(shown)}) drawn at 8 to 26 px, none a "
                    f"box" + (f": boxes {bad} (xfonts-base installed?)" if bad else ""))
    seen = [sizes(c, "normal") for c in replaced if (c, "normal") in boxes]
    expect(seen, f"the box is seen: of the symbols ui.CORE_GLYPHS stands in for, boxes {', '.join(seen) or 'none'}")
    out = os.environ.get("AIREMOVE_CI_SHOTS")
    if out:  # the characters (a row per size, normal then bold; the ones stood in for on the right) and the window
        Path(out).mkdir(parents=True, exist_ok=True)
        w, h = max(i.width for row in rows for i in row), max(i.height for row in rows for i in row)
        sheet = Image.new("RGB", (w * len(rows[0]), h * len(rows)))
        for j, row in enumerate(rows):
            for i, im in enumerate(row):
                sheet.paste(im, (i * w, j * h))
        sheet.save(Path(out) / "symbols.png")
        r.update()
        ImageGrab.grab((r.winfo_rootx(), r.winfo_rooty(), r.winfo_rootx() + r.winfo_width(),
                        r.winfo_rooty() + r.winfo_height())).save(Path(out) / "window.png")
        print(f"  the characters and the window: {out}")


def main(app_dir):
    faulthandler.enable()  # a crash inside Tk: where it was, on stderr
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")  # the symbols (ci_smoke.py reads UTF-8)
    sys.path.insert(0, str(Path(app_dir) / "airemove"))
    import tkinter as tk
    import ui

    def watchdog():
        while time.time() < step["until"]:
            time.sleep(0.2)
        print(f"  FAILED  {step['what']}: not done after {STEP_S} s (fit_header {calls[0]} times, {flips[0]} changes "
              f"between one row and two)", flush=True)
        os._exit(1)

    def begin(what):
        step.update(what=what, until=time.time() + STEP_S)

    errors, calls, flips, step = [], [0], [0], {}
    begin("opening the window")
    tk.Tk.report_callback_exception = lambda self, *exc: (errors.append(exc), traceback.print_exception(*exc))
    fit = ui.App.fit_header

    def counted(self):
        before = self.head_one_row
        fit(self)
        calls[0] += 1
        flips[0] += self.head_one_row != before
    ui.App.fit_header = counted
    ui.App.worker = ui.App.poll = lambda self: None  # no Session to prepare, no events from it
    threading.Thread(target=watchdog, daemon=True).start()

    def quiet(root, still=1.0, most=8.0):
        """Events handled until fit_header has not run for `still` s: whether it did within `most` s."""
        t0 = last = time.time()
        n = calls[0]
        while time.time() - t0 < most:
            root.update()
            if calls[0] != n:
                n, last = calls[0], time.time()
            elif time.time() - last >= still:
                return True
            time.sleep(0.01)
        return False

    # --- as the app opens it
    t0 = time.time()
    try:
        app = ui.App(session(), types.SimpleNamespace(variants=3))
    except tk.TclError as e:
        if "display" not in str(e):
            raise
        print(f"skipped: no display to open a window on ({e})")
        return
    r = app.root
    opened = time.time() - t0
    sw = r.winfo_screenwidth()
    print(f"  Tk {r.tk.call('info', 'patchlevel')} ({r.tk.call('tk', 'windowingsystem')}), screen {sw} x "
          f"{r.winfo_screenheight()}, scale {app.k:.2f}")
    app.on_found(None)  # the photo's name in the top bar, as when the photo is found
    expect(quiet(r), f"opened in {opened:.1f} s, the top bar then still (fit_header {calls[0]} times)")
    expect(r.winfo_width() >= 0.85 * sw, f"the window takes the screen: {r.winfo_width()} px of {sw} "
                                         f"({r.wm_geometry()}, {r.state()})")
    expect(not app.head_l.pack_propagate() and app.head_l.winfo_height() > 1,
           f"the photo's row asks for no width, its height kept ({app.head_l.winfo_height()} px)")
    begin("the window restored")
    r.state("normal")
    if ui.X11:
        r.attributes("-zoomed", False)
    quiet(r, 0.5)
    expect(0.8 * sw <= r.winfo_width() <= 0.95 * sw,
           f"restored, it keeps a size of its own: {r.winfo_width()} px of {sw} ({r.wm_geometry()})")
    begin("the buttons")
    buttons(tk, ui, app, r)
    begin("the symbols")
    symbols(tk, ui, app, r, begin)

    # --- sized by its content from its first layout: as in 1.8.0 before the zoom (its size and the zoom left out)
    begin("a window sized by its content")
    wm = {name: getattr(tk.Wm, name) for name in ("wm_geometry", "geometry", "wm_state", "state", "wm_attributes",
                                                  "attributes")}
    tk.Wm.wm_geometry = tk.Wm.geometry = lambda self, g=None: wm["wm_geometry"](self) if g is None else ""
    tk.Wm.wm_state = tk.Wm.state = lambda self, s=None: wm["wm_state"](self) if s is None else ""
    tk.Wm.wm_attributes = tk.Wm.attributes = lambda self, *a, **kw: (
        "" if a[:1] == ("-zoomed",) else wm["wm_attributes"](self, *a, **kw))
    try:
        n, f = calls[0], flips[0]
        sized = ui.App(session(), types.SimpleNamespace(variants=3), master=r)
    finally:
        for name, fn in wm.items():
            setattr(tk.Wm, name, fn)
    expect(quiet(r, most=10), f"sized by its content: the top bar settles (fit_header {calls[0] - n} times, "
                              f"{flips[0] - f} changes), the window {sized.root.winfo_width()} px")
    sized.destroy()

    # --- the hysteresis, on widths given to fit_header (the window's own size does not matter here)
    k, band = app.k, int(ui.HEAD_HYSTERESIS * app.k)
    for title in ("", "DSC_0042.NEF", "a photo with a rather long name, from the trip to the mountains.NEF"):
        name = title or "no name"
        begin(f"the hysteresis, {name}")
        app.title_text = title
        head_w = [int(2000 * k)]
        app.head.winfo_width = lambda: head_w[0]

        def at(w):
            head_w[0] = w
            app.fit_header()
            return app.head_one_row
        w = int(2000 * k)
        expect(at(w), f"{name}: one row at {w} px")
        while at(w) and w > 0:  # narrower, to two rows
            w -= 16
        while not at(w):  # wider, 1 px at a time: one row again
            w += 1
        up = w
        while at(w):  # narrower, 1 px at a time: two rows
            w -= 1
        down = w
        expect(band <= up - down - 1 <= band + 2, f"{name}: two rows below {down + 1} px, one row again from {up} px "
                                                  f"(HEAD_HYSTERESIS {band} px)")
        f = flips[0]
        for i in range(40):  # wavering inside the band
            at(down + 1 + (up - down - 1) * (i % 10) // 10)
        expect(flips[0] == f, f"{name}: widths wavering inside the band change nothing")
        for edge in (down, up - 1):
            f = flips[0]
            for i in range(40):
                at(edge + i % 2)
            expect(flips[0] - f <= 1, f"{name}: back and forth across {edge} px by 1 px: {flips[0] - f} change")
        del app.head.winfo_width
    app.title_text = "DSC_0042.NEF"

    # --- opened from the panel (the first window's Tk stands for the panel's), back to it, reopened
    begin("the window from the panel")
    closed = []
    start = {"removal": None, "selection": None, "model": "lama", "prompts": {}, "variants": 3}
    t0, n = time.time(), calls[0]
    win = ui.App(session(), types.SimpleNamespace(variants=3), master=r, on_close=closed.append, start=dict(start))
    w = win.root
    expect(quiet(r), f"from the panel: opened in {time.time() - t0:.1f} s, the top bar then still "
                     f"(fit_header {calls[0] - n} times), the window {w.winfo_width()} px of {sw}")
    win.quit()
    quiet(r, 0.3)
    expect(closed == [win] and w.state() == "withdrawn", "back to the panel: the window kept, hidden")
    t0, n = time.time(), calls[0]
    win.reopen(dict(start))
    expect(quiet(r), f"reopened in {time.time() - t0:.1f} s, the top bar then still (fit_header {calls[0] - n} "
                     f"times), the window {w.winfo_width()} px of {sw} ({w.state()})")
    expect(w.winfo_width() >= 0.85 * sw, "reopened, it takes the screen again")
    win.destroy()
    app.destroy()
    expect(not errors, f"no error in the window's callbacks ({len(errors)})")
    print("window: all checks passed")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    except Failed as e:
        print("  FAILED  " + str(e))
        sys.exit(1)
