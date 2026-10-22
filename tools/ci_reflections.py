""""Remove reflections" end to end, without LightCraft and without DAI, for the CI runners: tools/ci_smoke.py remove
DIR runs this after ci_removal.py, with the install's own Python (DIR: an install with LaMa only).

The photo is ci_removal.py's synthetic raw DNG with a reflection over it: a broad bluish glow of light added in linear
light over its left part (a street reflected in a shop window, out of focus), so the same photo without it is known.
A stand-in for DAI is put where the session keeps the engine — engines.DAI's remove(): the area seen at 1024 px
without the glow, what a perfect model would draw — and the rest is the app's own code: a removal of the whole photo
("Remove reflections" with nothing selected), its variants at each strength, the reflection's light taken off the raw
values themselves (RawDNG.subtract_region) by "Save in LightCraft", the window's preview, the project reopened.

Checks: the variants are labelled by their strength (DAI 75 %, DAI 100 %); saved at 100 %, the raw values are the
photo's without the glow within a few DN where the glow added up to hundreds, with the sensor's own noise (none is
added); where there is no glow they are untouched, and the blown sky keeps its clipped values; saved at 75 %, a
quarter of the glow is left; the first strength stays the one chosen; the preview darkens where the glow was and
nowhere else; the project keeps the reflection's light instead of the variants' pictures; reopened, the removal is a
reflection removal again and rebuilds the same sensor data. Exit status 1 at the first check that fails.

  ci_reflections.py DIR [--keep FOLDER]    FOLDER: where the photos, base.png, the DNG and the project are left
"""
import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_removal as cr  # noqa: E402  (its synthetic raw, base.png, stand-in LightCraft, Session and checks)
from ci_removal import CROP, H, W, Failed, expect  # noqa: E402

GLOW = (480, 420, 260, 0.09)  # the reflection: centre y, x and sigma in frame pixels, its peak (linear light)
GLOW_RGB = np.array([0.8, 0.95, 1.25])  # bluish, as a reflected sky or street


def glow():
    """The reflection's light over the active area (frame coordinates, as ci_removal.scene)."""
    y, x = np.mgrid[-CROP:H + CROP, -CROP:W + CROP].astype(np.float64)
    cy, cx, s, peak = GLOW
    return peak * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * s * s))[..., None] * GLOW_RGB


class StandInDAI:
    """engines.DAI's remove(): the area it is given (upright, as floats) without the glow, at 1024 px on its long side
    — what a perfect model would draw. As DAI does (its decoder gets the photo's own detail), the picture keeps the
    photo's own noise: the glow, which renders as itself times the area's gain (the scene's linear light), is taken
    off the photo given, at that size, in linear light."""

    def __init__(self, s, ar):
        self.s, self.ar, self.calls = s, ar, 0

    def remove(self, src, progress=None):
        self.calls += 1
        r = self.s.removals[-1]
        h, w = src.shape[:2]
        expect(src.dtype == np.float32 and self.s._up(np.zeros(r.reg_mask.shape, bool)).shape == (h, w),
               f"the stand-in sees the area upright, {w}x{h}, as floats (not rounded to 8 bits)")
        k = min(1.0, 1024 / max(w, h))
        size = (round(w * k), round(h * k))
        RawDNG, small = self.ar.RawDNG, self.ar.engines._resized
        g = self.s._up((glow()[CROP:CROP + H, CROP:CROP + W] * r.gain).astype(np.float32))
        lin = small(RawDNG.inv_oetf(src), size, Image.BOX) - small(g, size, Image.BOX)
        return RawDNG.oetf(lin).astype(np.float32), k

    def unload(self):
        pass


def read_cfa(ar, path):
    """A DNG's sensor data, the file closed again (it is written over next)."""
    raw = ar.RawDNG(str(path))
    cfa = raw.cfa.copy()
    raw.close()
    return cfa


def neighbour_noise(cfa, sl):
    """The sensor noise in a region: the spread of differences between same-colour neighbours (two columns apart)."""
    a = cfa[sl].astype(np.float64)
    return float(np.std(a[:, 2:] - a[:, :-2]) / np.sqrt(2))


def run(d, out):
    sys.path.insert(0, str(d / "airemove"))
    import airemove as ar
    import project
    from rawdng import XYZD50_TO_SRGB

    photos, work = out / "photos", out / "work"
    photos.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    photo, export, base_png = photos / "CI-0002.dng", work / "source.dng", work / "base.png"
    clean_rgb = cr.scene()
    cfa_clean = cr.write_raw(work / "without-glow.dng", clean_rgb, XYZD50_TO_SRGB)
    cfa0 = cr.write_raw(photo, clean_rgb + glow(), XYZD50_TO_SRGB)
    shutil.copyfile(photo, export)
    cr.develop(clean_rgb + glow()).save(base_png)
    lc = cr.StandIn(ar.LC)
    s = cr.session(ar, lc.lc, photo, export, base_png, work / "s1")
    y0, x0 = s.raw.frame[:2]
    frame = (slice(y0, y0 + H), slice(x0, x0 + W))
    added = (cfa0.astype(np.float64) - cfa_clean)[frame]
    g = glow()[CROP:CROP + H, CROP:CROP + W].mean(axis=2)
    strong, none = g > 0.5 * GLOW[3] * GLOW_RGB.mean(), g < 1e-5
    print(f"  info the glow adds {added[strong].mean():.0f} DN where it is strong", flush=True)

    # "Remove reflections" with nothing selected: the whole photo, one removal
    r = s.new_removal(np.ones(s.base_arr.shape[:2], bool), reflection=True)
    expect(r.reflects() and r.box == (y0, y0 + H, x0, x0 + W), f"one removal over the whole photo ({r.box})")
    s.dai = StandInDAI(s, ar)
    s.run_model(r, "dai", "")
    s.run_model(r, "dai", "")
    labels = [label for label, __ in r.candidates]
    shown = [ar.label_text(label) for label in labels]
    expect(labels == ["DAI 1", "DAI 2"] and shown == ["DAI 75 %", "DAI 100 %"] and s.dai.calls == 1,
           f"two variants, by strength: {shown}, the model run once")
    expect(r.chosen == 0, f"the first strength stays the one chosen ({r.chosen_label()})")
    expect(s.refine_check(r) == (False, "sharp"), "\"Full detail\" has nothing to redraw")

    # saved at 100 %: the photo without the glow, its own noise
    r.chosen, r.user_picked = 1, True
    dng, __, __ = s.write_all()
    cfa1 = read_cfa(ar, dng)
    left = (cfa1.astype(np.float64) - cfa_clean)[frame]
    expect(np.abs(left[strong].mean()) < 0.03 * added[strong].mean(),
           f"at 100 % the glow is gone: {left[strong].mean():+.1f} DN left of {added[strong].mean():.0f}")
    rows = slice(y0 + 300, y0 + 600)
    cols = slice(x0 + 300, x0 + 560)
    n0, n1 = neighbour_noise(cfa0, (rows, cols)), neighbour_noise(cfa1, (rows, cols))
    expect(abs(n1 / n0 - 1) < 0.03, f"with the sensor's own noise: {n1:.2f} DN, it was {n0:.2f} (none added)")
    moved = np.abs(cfa1.astype(np.float64) - cfa0)[frame][none]
    print(f"  info where there was no glow: mean change {moved.mean():.3f} DN, max {moved.max():.0f} DN, "
          f"{(moved > 0).mean():.2%} of the values changed", flush=True)
    same = (cfa1 == cfa0)[frame]
    expect(same[none].mean() > 0.99, f"where there was no glow, {same[none].mean():.1%} of the values untouched")
    sky = (cfa0 == cr.SAT)
    expect(np.array_equal(cfa1[sky], cfa0[sky]), f"the blown sky keeps its clipped values ({int(sky.sum())})")

    # the window's preview: base.png, darker only where the glow was
    shown_now = s.composite().astype(np.float64).mean(axis=2) - s.base_arr.astype(np.float64).mean(axis=2)
    gb = np.asarray(cr.upright_half(Image.fromarray((g / g.max() * 255).astype(np.uint8)))) / 255.0
    expect(shown_now[gb > 0.5].mean() < -3 and abs(shown_now[gb < 0.01].mean()) < 0.5,
           f"the preview darkens where the glow was ({shown_now[gb > 0.5].mean():.1f} levels) and not elsewhere "
           f"({shown_now[gb < 0.01].mean():+.2f})")

    # saved at 75 %: a quarter of it left
    r.chosen = 0
    dng, __, __ = s.write_all()
    cfa75 = read_cfa(ar, dng)
    rest = (cfa75.astype(np.float64) - cfa_clean)[frame][strong].mean() / added[strong].mean()
    expect(0.22 < rest < 0.28, f"at 75 % a quarter of the glow is left ({rest:.1%})")
    s.close()

    # the project keeps the reflection's light, not the variants' pictures
    with zipfile.ZipFile(project.path_for(photo)) as z:
        names = z.namelist()
    size = project.path_for(photo).stat().st_size / 2 ** 20
    expect(f"r{r.id}/light.npz" in names and not any(n.endswith(("/00.png", "/01.png")) for n in names),
           f"the project keeps the reflection's light, not its variants' pictures ({size:.1f} MB)")

    # reopened: a reflection removal again, the same sensor data
    s2 = cr.session(ar, lc.lc, photo, export, base_png, work / "s2")
    r2 = s2.removals[0] if s2.removals else None
    expect(r2 is not None and r2.reflects() and r2.chosen_label() == "DAI 1",
           f"reopened: the reflection removal, {r2.chosen_label() if r2 else None} chosen")
    expect(np.array_equal(s2.working_cfa(), cfa75), "it rebuilds exactly the DNG's sensor data")
    s2.composite()  # its preview, from the area rendered again (a reflection variant differs all over its area)
    expect(r2._src is not None, "its area rendered for the preview")
    s2.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", help="install folder")
    ap.add_argument("--keep", help="leave the files in this folder")
    a = ap.parse_args()
    d = Path(a.dir).expanduser().resolve()
    out = Path(a.keep).resolve() if a.keep else Path(tempfile.mkdtemp(prefix="airemove-ci-"))
    print(f"reflections {d} (files in {out})", flush=True)
    try:
        run(d, out)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    finally:
        if not a.keep:
            shutil.rmtree(out, ignore_errors=True)
    print("  ok   \"Remove reflections\" end to end", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
