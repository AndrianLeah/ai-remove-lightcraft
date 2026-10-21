"""How "Remove selection" splits a selection (airemove.split_selection), for the CI runners: tools/ci_smoke.py remove
DIR runs this with the install's own Python. DIR's app code is imported.

On synthetic selections in a portrait photo's base.png frame (1600 x 2400 for 3648 x 5472 sensor px):
  - two people far apart are two removals, in reading order;
  - two people side by side are one (each would see the other in its area); a person and their bag, given as two
    objects (units), one too;
  - a crowd shoulder to shoulder is several parts, none of whose areas is larger than PART_MOST sensor px (as one,
    its area was half the photo, drawn soft by every model);
  - four people who touch in a row, one blob: several parts when given as four objects (too wide as one), one
    without units; two that take no more room together than apart stay one;
  - a cord across the photo and a person far above it, outside its area, are two; a person just above it, one;
  - a small sign inside a big object's area, whose own area does not reach the object: the sign first, then the
    object (its area then sees the sign already filled);
  - 40 people scattered over the photo: each part's area holds no part after it, but one that sees it too (too
    large as one part);
  - every split is exact: the parts do not overlap and together are the selection; an empty selection has none.
"Include the shadow" keeps of SAM 3's shadows (airemove.shadows_touching) those of the selection: a person's long
shadow touching them, not a shadow far away, nor a building's shade the person stands in; never the selection itself.
Exit status 1 at the first check that fails.

  ci_split.py DIR
"""
import sys
from pathlib import Path

import numpy as np

H, W = 2400, 1600
SCALE = 1600 / 3648


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


def blob(m, cy, cx, h, w):
    m[cy - h // 2:cy + h // 2, cx - w // 2:cx + w // 2] = True


def centres(parts):
    return [tuple(int(v) for v in np.argwhere(p).mean(0)) for p in parts]


def main(app_dir):
    sys.path.insert(0, str(Path(app_dir) / "airemove"))
    import airemove as A

    def split(m, what, units=None):
        parts = A.split_selection(m, SCALE, units=units)
        union = np.zeros_like(m)
        for p in parts:
            if (union & p).any():
                raise Failed(f"{what}: parts overlap")
            union |= p
        if not (union == m).all():
            raise Failed(f"{what}: the parts are not the selection")
        return parts

    m = np.zeros((H, W), bool)
    blob(m, 1800, 1300, 300, 100)
    blob(m, 600, 300, 300, 100)
    parts = split(m, "two far")
    expect(len(parts) == 2 and centres(parts)[0][0] < centres(parts)[1][0],
           "two people far apart: two removals, the upper one first")

    m = np.zeros((H, W), bool)
    blob(m, 600, 300, 300, 100)
    blob(m, 600, 420, 300, 100)
    expect(len(split(m, "two close")) == 1, "two people side by side: one removal")

    person, bag = np.zeros((H, W), bool), np.zeros((H, W), bool)
    blob(person, 600, 300, 300, 100)
    blob(bag, 650, 360, 60, 40)  # against the person's side, overlapping it
    parts = split(person | bag, "person and bag", units=[person, bag])
    expect(len(parts) == 1, "a person and their bag, two objects: one removal")

    m = np.zeros((H, W), bool)
    for i in range(10):
        blob(m, 1500, 300 + 110 * i, 260, 70)
    parts = split(m, "crowd")
    cap = A.PART_MOST * SCALE
    sides = []
    for p in parts:
        ys, xs = np.nonzero(p)
        sides.append(max(ys.max() - ys.min(), xs.max() - xs.min()) * 1.35)
    expect(len(parts) > 1 and max(sides) <= cap + 1,
           f"a crowd shoulder to shoulder: {len(parts)} parts, each area at most {max(sides):.0f} px of {cap:.0f}")

    row = []  # four people in a row, each touching the next: one blob 600 px wide, 300 tall
    for i in range(4):
        u = np.zeros((H, W), bool)
        blob(u, 1200, 500 + 150 * i, 300, 150)
        row.append(u)
    blob_ = np.logical_or.reduce(row)
    parts = split(blob_, "touching row, units", units=row)
    expect(len(parts) > 1, f"four people who touch, given as four objects: {len(parts)} removals (too wide as one)")
    expect(len(split(blob_, "touching row, no units")) == 1, "the same blob without units: one removal")

    m = np.zeros((H, W), bool)
    m[1700:1712, :] = True
    blob(m, 400, 800, 200, 80)
    expect(len(split(m, "cord, person far")) == 2, "a cord across the photo and a person outside its area: two")
    m = np.zeros((H, W), bool)
    m[1700:1712, :] = True
    blob(m, 1600, 800, 200, 80)
    expect(len(split(m, "cord, person near")) == 1, "a cord and a person just above it: one")

    m = np.zeros((H, W), bool)
    blob(m, 1200, 800, 900, 600)
    blob(m, 1200, 1250, 40, 40)
    parts = split(m, "big and small")
    expect(len(parts) == 2 and parts[0].sum() < parts[1].sum(),
           "a small sign inside a big object's area: two, the sign first")

    rng = np.random.default_rng(0)
    m = np.zeros((H, W), bool)
    for __ in range(40):
        blob(m, int(rng.uniform(200, 2200)), int(rng.uniform(100, 1500)), 120, 40)
    parts = split(m, "scattered")
    # each part's area (as plan_region makes it, these are compact) holds no pixel of a later part, but where the two
    # see each other (kept apart: too large as one part, so neither could come first)
    g = max(6 * SCALE, 0.004 * max(H, W))

    def sq(p):
        ys, xs = np.nonzero(p)
        by0, by1, bx0, bx1 = ys.min() - g, ys.max() + 1 + g, xs.min() - g, xs.max() + 1 + g
        side = min(max(max(by1 - by0, bx1 - bx0) * 1.35, 384 * SCALE), min(H, W))
        y0 = int(np.clip((by0 + by1 - side) / 2, 0, H - side))
        x0 = int(np.clip((bx0 + bx1 - side) / 2, 0, W - side))
        return slice(y0, int(np.ceil(y0 + side))), slice(x0, int(np.ceil(x0 + side)))
    one_way = mutual = 0
    for i, p in enumerate(parts):
        for q in parts[i + 1:]:
            if q[sq(p)].any():
                if p[sq(q)].any():
                    mutual += 1
                else:
                    one_way += 1
    expect(1 < len(parts) < 40 and not one_way,
           f"40 scattered people: {len(parts)} removals; none sees a part still to remove but {mutual} pairs that see "
           f"each other, too large as one")

    expect(split(np.zeros((H, W), bool), "empty") == [], "an empty selection: nothing")

    person = np.zeros((H, W), bool)
    blob(person, 1500, 800, 300, 80)  # rows 1350-1650, columns 760-840
    long_shadow = np.zeros((H, W), bool)
    long_shadow[1640:1660, 840:1100] = True  # from the feet to the right, at a low sun
    far_shadow = np.zeros((H, W), bool)
    far_shadow[400:420, 200:400] = True
    shade = np.zeros((H, W), bool)
    shade[1200:2400, 500:1600] = True  # a building's shade the person stands in
    got = A.shadows_touching([long_shadow, far_shadow, shade], person, SCALE)
    expect(got is not None and got[1650, 1000] and not got[410, 300] and not got[2300, 1500]
           and not (got & person).any(),
           "SAM 3's shadows: the long one at the feet kept; one far away and a building's shade not; never the person")
    expect(A.shadows_touching([far_shadow], person, SCALE) is None, "no shadow touching: none")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    except Failed as e:
        print("FAILED: " + str(e))
        sys.exit(1)
    print("split: all checks passed")
