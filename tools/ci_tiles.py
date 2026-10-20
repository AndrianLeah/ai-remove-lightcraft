"""Long removals in tiles (airemove/tiles.py), without LightCraft or a GPU, for the CI runners: tools/ci_smoke.py
remove DIR runs this after ci_removal.py with the install's own Python, and the app's code is imported from DIR.

A synthetic area (sensor orientation, as Session.new_removal makes it) the size of a photo's short side: a ground
of stone courses and a slow gradient, crossed by a long slanted cord, and the cord's hole. Checks:
- the squares cover the hole, each hole pixel has one square that keeps it, a square follows the slant;
- squares that draw the photo itself give it back (no seam, no offset), and squares whose fill is off by a different
  amount each are matched to their surroundings (blend.Membrane), so the seams between them do not show;
- Session.tile_plan: FLUX gets squares within TILE_BUDGET on the cord, none on a person-shaped hole or a small area,
  SDXL none; "Full detail" (refine) gets squares nearer the engine's size on the cord and is not offered for the
  person; the cord is long and thin, the person is not;
- LaMa through Session.run_lama fills the cord in squares at its own 512 px: the cord is gone (the fill is the
  ground's colour), the photo outside the hole is untouched.
Exit status 1 at the first check that fails.

  ci_tiles.py DIR
"""
import sys
import time
from argparse import Namespace
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

SIDE = 1800  # the area: larger than TILE_FROM x LaMa's 512 px, so LaMa is tiled too


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok   " + what, flush=True)


def ground(side=SIDE):
    """uint8 RGB: courses of stone (horizontal joints every 60 px, staggered vertical ones), a slow gradient."""
    y, x = np.mgrid[0:side, 0:side].astype(np.float64)
    lum = 120 + 40 * x / side + 8 * np.sin(x / 23.0) * np.cos(y / 31.0)
    joint = (y % 60 < 4) | (((x + 45 * ((y // 60) % 2)) % 90) < 4)
    lum = np.where(joint, lum - 45, lum)
    return np.clip(lum[..., None] * np.array([1.0, 0.93, 0.8]), 0, 255).astype(np.uint8)


def cord(side=SIDE, width=40):
    """bool: a slanted cord across the whole area (the hole: the cord and a brush's margin around it)."""
    y, x = np.mgrid[0:side, 0:side].astype(np.float64)
    return np.abs(y - (0.3 * side + 0.25 * x)) < width / 2


def person(side=SIDE):
    """bool: a person-shaped hole (an upright ellipse with a head), as wide as a person is."""
    y, x = np.mgrid[0:side, 0:side].astype(np.float64)
    body = ((x - side / 2) / (0.12 * side)) ** 2 + ((y - 0.6 * side) / (0.3 * side)) ** 2 < 1
    head = (x - side / 2) ** 2 + (y - 0.22 * side) ** 2 < (0.06 * side) ** 2
    return body | head


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    d = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(d / "airemove"))
    import airemove as A
    import blend
    import tiles

    print(f"tiles: {d / 'airemove' / 'tiles.py'}", flush=True)
    img, hole = ground(), cord()
    src = img.copy()
    src[cord(width=16)] = (40, 40, 45)  # the cord itself, inside its selection (a brush's margin around it)

    T = 512
    sq = tiles.squares(hole, T)
    own = tiles.owners(hole, sq, T)
    expect(len(sq) >= 4, f"the cord gets {len(sq)} squares of {T} px")
    expect((own[hole] >= 0).all(), "every hole pixel is kept by one square")
    off = [abs(y + T / 2 - (0.3 * SIDE + 0.25 * (x + T / 2))) for y, x in sq]  # the cord's centre line
    expect(max(off) < T / 4, f"the squares follow the slanted cord (at most {max(off):.0f} px off its centre)")

    plan = tiles.Plan(hole, T)
    truth = Image.fromarray(img)
    out = plan.fill(Image.fromarray(src), lambda im, m, k: truth.crop((plan.squares[k][1], plan.squares[k][0],
                                                                       plan.squares[k][1] + T,
                                                                       plan.squares[k][0] + T)))
    diff = np.abs(np.asarray(out).astype(np.int16) - img.astype(np.int16))
    expect(diff[hole].max() <= 2 and diff[~hole].max() == 0,
           f"squares that draw the photo give it back (largest difference {diff[hole].max()} levels)")

    def off(im, m, k):  # each square's fill off by its own amount
        y, x = plan.squares[k]
        a = np.asarray(truth.crop((x, y, x + T, y + T))).astype(np.int16) + (25 if k % 2 else -25)
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    out = np.asarray(plan.fill(Image.fromarray(src), off)).astype(np.float64)
    err = np.abs(out - img)[hole].mean()
    expect(err < 4.0, f"squares off by +-25 levels are matched to what is around them (mean error {err:.1f} levels)")

    s = A.Session(None, Namespace(id=None, raw=None, variants=None, auto=None, shadow=False))
    big = 3648
    r_cord, r_person, r_small = (A.Removal(i, None) for i in (1, 2, 3))
    r_cord.reg_mask, r_person.reg_mask, r_small.reg_mask = cord(big, 120), person(big), cord(2000, 120)
    p = s.tile_plan(r_cord, "flux")
    expect(p is not None and len(p[1]) * s.tile_seconds("flux", p[0]) <= A.TILE_BUDGET,
           f"FLUX on a {big} px cord: {len(p[1]) if p else 0} squares of {p[1].T if p else 0} px, within the budget")
    expect(s.tile_plan(r_person, "flux") is None, "FLUX on a person-shaped hole: one pass, as before")
    expect(s.tile_plan(r_small, "flux") is None, "FLUX on a 2000 px area: one pass, as before")
    expect(s.tile_plan(r_cord, "sdxl") is None, "SDXL variants: one pass (in squares it draws planks along a cord)")
    expect(A.Session.thin(r_cord) and not A.Session.thin(r_person),
           "the cord is long and thin (the window adds LaMa to it), the person is not")
    q = s.tile_plan(r_cord, "flux", refine=True)
    n, side, size = (len(q[1]), q[1].T, q[0]) if q else (0, 0, 0)
    expect(q is not None and side / size < big / 768, f"Full detail on the cord: {n} squares of {side} px at {size}")
    for r in (r_cord, r_person):
        r.candidates, r.chosen = [("FLUX 1", None)], 0
    if s.refine_model():  # an install with FLUX or SDXL (not on the CI runners: LaMa only)
        expect(s.can_refine(r_cord) and not s.can_refine(r_person),
               "Full detail is offered on the cord's variant, not on the person's")
    expect(A.Session.long(r_cord) and not A.Session.long(r_person), "the cord is long, the person is not")

    s.work = d / "work" / "ci-tiles"
    s.work.mkdir(parents=True, exist_ok=True)
    r = A.Removal(4, None)
    r.reg_mask, r.src = hole, Image.fromarray(src)
    r.mask_img = Image.fromarray((hole * 255).astype(np.uint8))
    r.membrane = blend.Membrane(hole)
    t0 = time.time()
    lplan = s.tile_plan(r, "lama")
    expect(lplan is not None, f"LaMa on a {SIDE} px cord: {len(lplan[1]) if lplan else 0} squares of "
                              f"{lplan[1].T if lplan else 0} px")
    label, im = s.run_lama(r)
    a = np.asarray(im).astype(np.float64)
    expect(np.array_equal(np.asarray(im)[~hole], src[~hole]), "outside the hole the photo is untouched")
    core = ndi.binary_erosion(hole, iterations=8)
    g = img.astype(np.float64)[core].mean(axis=0)
    f = a[core].mean(axis=0)
    expect(np.abs(f - g).max() < 20, f"the cord is gone: the fill is the ground's colour ({f.round()} vs "
                                     f"{g.round()}), LaMa tiled in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        sys.exit(1)
