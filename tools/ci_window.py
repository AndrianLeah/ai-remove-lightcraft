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
  - opened from the panel (master, on_close), back to the panel and reopened (reopen): zoomed again, the top bar still.
Exit status 1 at the first check that fails; 0 with "skipped" when there is no display to open a window on.

  ci_window.py DIR
"""
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


def main(app_dir):
    sys.path.insert(0, str(Path(app_dir) / "airemove"))
    import tkinter as tk
    try:
        tk.Tk().destroy()
    except tk.TclError as e:
        print(f"skipped: no display to open a window on ({e})")
        return
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
    app = ui.App(session(), types.SimpleNamespace(variants=3))
    r = app.root
    opened = time.time() - t0
    app.on_found(None)  # the photo's name in the top bar, as when the photo is found
    expect(quiet(r), f"opened in {opened:.1f} s, the top bar then still (fit_header {calls[0]} times)")
    sw = r.winfo_screenwidth()
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
        sized = ui.App(session(), types.SimpleNamespace(variants=3))
    finally:
        for name, fn in wm.items():
            setattr(tk.Wm, name, fn)
    expect(quiet(sized.root, most=10), f"sized by its content: the top bar settles (fit_header {calls[0] - n} times, "
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
    app.destroy()

    # --- opened from the panel, back to it, reopened
    begin("the window from the panel")
    panel = tk.Tk()
    panel.withdraw()
    closed = []
    start = {"removal": None, "selection": None, "model": "lama", "prompts": {}, "variants": 3}
    t0, n = time.time(), calls[0]
    app = ui.App(session(), types.SimpleNamespace(variants=3), master=panel, on_close=closed.append, start=dict(start))
    r = app.root
    expect(quiet(panel), f"from the panel: opened in {time.time() - t0:.1f} s, the top bar then still "
                         f"(fit_header {calls[0] - n} times), the window {r.winfo_width()} px of {sw}")
    app.quit()
    quiet(panel, 0.3)
    expect(closed == [app] and r.state() == "withdrawn", "back to the panel: the window kept, hidden")
    t0, n = time.time(), calls[0]
    app.reopen(dict(start))
    expect(quiet(panel), f"reopened in {time.time() - t0:.1f} s, the top bar then still (fit_header {calls[0] - n} "
                         f"times), the window {r.winfo_width()} px of {sw} ({r.state()})")
    expect(r.winfo_width() >= 0.85 * sw, "reopened, it takes the screen again")
    app.destroy()
    panel.destroy()
    expect(not errors, f"no error in the window's callbacks ({len(errors)})")
    print("window: all checks passed")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    except Failed as e:
        print("  FAILED  " + str(e))
        sys.exit(1)
