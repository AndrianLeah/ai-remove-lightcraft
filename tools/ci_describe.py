"""Describe's masks without the model, for the CI runners: tools/ci_smoke.py remove DIR runs this with the install's own
Python (SAM 3 itself is not on the runners: its licence must be accepted on Hugging Face). DIR's app code is imported.

engines.describe_masks turns SAM 3's detector output (instance logits, their scores and the semantic logits, at the
model's 288 x 288) into one mask per instance at the photo's size. On synthetic logits like SAM 3's, two people side by
side whose own masks both fade where they touch, one with a hole SAM 3 was unsure about:
  - the seam between them is selected, and each seam pixel belongs to the instance strongest there;
  - the hole is filled;
  - where only the semantic mask says yes, far from any instance (its logit below -4 there), nothing is selected;
  - an instance's own pixels stay where the semantic mask says no;
  - an instance under the score threshold is dropped; with none above it, nothing is returned;
  - masks come at the photo's size (w, h), not square.
Describe also looks in overlapping tiles (engines.describe_tiles, merge_instances), so that people far away are found:
  - the tiles cover the photo, overlap, and turn with a portrait photo;
  - an instance found again in a tile, or cut by a tile's edge, is dropped; one found only in a tile is kept, at its
    place in the photo; two people side by side stay two.
Exit status 1 at the first check that fails.

  ci_describe.py DIR
"""
import sys
from pathlib import Path

import numpy as np

S = 288


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok   " + what, flush=True)


def disc(cy, cx, r):
    y, x = np.mgrid[0:S, 0:S]
    return np.sqrt((y - cy) ** 2 + (x - cx) ** 2) - r  # signed distance: < 0 inside


def run(d):
    sys.path.insert(0, str(d / "airemove"))
    import engines
    # two people (discs) side by side, overlapping around x = 144; a third, weak instance; the semantic mask
    da, db = disc(144, 110, 40), disc(144, 178, 40)
    a = np.clip(-da * 0.5, -12, 8)
    b = np.clip(-db * 0.5, -12, 8)
    yy, xx = np.mgrid[0:S, 0:S]
    seam = (np.abs(xx - 144) <= 3) & (np.abs(yy - 144) <= 18)
    # both fade where they touch, as SAM 3's instance masks do; each is a little stronger on its own side
    a[seam] = np.where(xx[seam] < 144, -1.0, -1.5)
    b[seam] = np.where(xx[seam] < 144, -1.5, -1.0)
    hole = disc(150, 100, 6) < 0
    a[hole] = -2.0  # unsure inside
    own_only = disc(120, 90, 5) < 0  # A says yes, the semantic mask no
    weak = np.clip(-disc(40, 40, 15) * 0.5, -12, 8)
    sem = np.where((da < 2) | (db < 2), 5.0, -5.0)
    sem[own_only] = -5.0
    far = disc(240, 240, 20) < 0  # the semantic mask alone, far from every instance
    sem[far] = 5.0
    inst = np.stack([a, b, weak]).astype(np.float32)
    scores = np.array([0.9, 0.8, 0.3], np.float32)

    W, H = 600, 400  # not square: the photo's size
    masks, kept = engines.describe_masks(inst, scores, sem.astype(np.float32), (W, H))
    expect(len(masks) == 2 and np.allclose(kept, [0.9, 0.8]), "2 instances above the score (the weak one dropped)")
    expect(all(m.shape == (H, W) and m.dtype == bool for m in masks), f"masks at the photo's size ({W}x{H})")

    def at(m, yy, xx):  # a 288 grid point in the photo's frame
        return m[int((yy + 0.5) * H / S), int((xx + 0.5) * W / S)]
    union = masks[0] | masks[1]
    seam_pts = [(y, x) for y in range(128, 161, 4) for x in (142, 146)]
    own_alone = np.stack([inst[0] > 0, inst[1] > 0]).any(0)
    expect(not any(own_alone[y, x] for y, x in seam_pts), "(their own masks alone leave the seam out)")
    expect(all(at(union, y, x) for y, x in seam_pts), "the seam between the two is selected")
    expect(all(at(masks[0], y, 142) and not at(masks[1], y, 142) and at(masks[1], y, 146)
               and not at(masks[0], y, 146) for y in range(128, 161, 4)),
           "each seam pixel belongs to the instance strongest there, and only to it")
    expect(at(masks[0], 150, 100), "the hole inside the first one is filled")
    expect(at(masks[0], 120, 90), "its own pixels stay where the semantic mask says no")
    expect(not union[int(240.5 * H / S), int(240.5 * W / S)], "the semantic mask alone, far from them, is left out")
    none, kept0 = engines.describe_masks(inst, np.array([0.2, 0.1, 0.3], np.float32), sem, (W, H))
    expect(none == [] and len(kept0) == 0, "nothing above the score: nothing returned")

    # the tiles: a landscape and a portrait photo
    for size, grid in (((2400, 1600), (3, 2)), ((1600, 2400), (2, 3))):
        boxes = engines.describe_tiles(size)
        cover = np.zeros(size[::-1], np.int32)
        for x0, y0, x1, y1 in boxes[1:]:
            cover[y0:y1, x0:x1] += 1
        expect(boxes[0] == (0, 0) + size and len(boxes) == 1 + grid[0] * grid[1] and cover.min() >= 1
               and cover.max() >= 2 and boxes[1][2] - boxes[1][0] < size[0],
               f"{size[0]}x{size[1]}: the whole photo, then {grid[0]}x{grid[1]} overlapping tiles covering it")

    # merging: in a 300 x 200 photo, whole = (0, 0, 300, 200), a tile = (100, 0, 300, 200)
    def box_mask(w, h, y0, y1, x0, x1):
        m = np.zeros((h, w), bool)
        m[y0:y1, x0:x1] = True
        return m
    whole, tile = (0, 0, 300, 200), (100, 0, 300, 200)
    found = [(whole, box_mask(300, 200, 50, 150, 40, 80), 0.9),       # a person, found whole
             (tile, box_mask(200, 200, 52, 148, 0, 30), 0.8),         # ...the same, cut by the tile's left edge
             (tile, box_mask(200, 200, 60, 90, 150, 160), 0.7),       # someone far away: only the tile sees them
             (tile, box_mask(200, 200, 60, 90, 150, 160), 0.6),       # ...found twice
             (whole, box_mask(300, 200, 50, 150, 82, 120), 0.9)]      # a second person, right next to the first
    masks, scores = engines.merge_instances(found, (300, 200))
    far = box_mask(300, 200, 60, 90, 250, 260)
    expect(len(masks) == 3 and all(m.shape == (200, 300) for m in masks),
           "merged: the two people and the one far away, each once (a duplicate and a cut piece dropped)")
    expect(any((m == far).all() for m in masks), "the one found only in a tile is at its place in the photo")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    d = Path(sys.argv[1]).expanduser().resolve()
    print(f"describe {d}", flush=True)
    try:
        run(d)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    print("  ok   Describe's masks", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
