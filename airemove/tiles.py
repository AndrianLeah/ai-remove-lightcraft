"""Long removals in tiles, so that each engine works at (or near) the size it was made for.

A removal's area is a square 1.35 times the object's extent. For a pole as tall as the photo that is 3648 px, which
FLUX sees at 768 px: every pixel it draws becomes 4.75 photo pixels — a soft fill, with the ornament behind the pole
invented from a blurred view of it. Here the hole is filled in overlapping squares that follow it, each only a few
times (at best one time) the engine's own size, one after the other: each square sees the photo around it, and the
fill of the squares before it, at its own resolution. The squares meet in a cross-faded band, and each one's fill is
matched to what it sees around its hole (blend.Membrane), so the area comes out as one fill and is blended as one.
Only for long, thin holes, whose squares all see the photo across them (when to use it: Session.tile_plan).
"""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

import blend

BAND = 32  # px of the earlier squares' fill that a square draws again, cross-faded into theirs


def _starts(lo, hi, side, T, m):
    """Square starts along one axis covering [lo, hi) of a `side` long area: each square's own part keeps m px of
    context before and after it, but at the area's border (nothing there to see)."""
    if hi - lo <= T - 2 * m or side <= T:
        return [int(np.clip((lo + hi) // 2 - T // 2, 0, max(0, side - T)))]
    out = []
    a = int(np.clip(lo - m, 0, side - T))
    while True:
        out.append(a)
        own_end = a + T - (m if a + T < side else 0)
        if own_end >= hi or a >= side - T:
            return out
        a = int(min(own_end - m, side - T))


def squares(hole, T, margin=None):
    """Origins (y, x) of the T x T squares that cover every pixel of `hole` (bool, the area's), in the order they are
    filled: along the hole's long axis first, then across it only where the hole is (a slanted pole or cord gets
    squares that follow it)."""
    margin = T // 6 if margin is None else margin
    ys, xs = np.nonzero(hole)
    along_x = (xs.max() - xs.min()) >= (ys.max() - ys.min())
    h = hole if along_x else hole.T
    cols = np.nonzero(h.any(axis=0))[0]
    out = []
    for a in _starts(cols.min(), cols.max() + 1, h.shape[1], T, margin):
        rows = np.nonzero(h[:, a:a + T].any(axis=1))[0]
        for c in (_starts(rows.min(), rows.max() + 1, h.shape[0], T, margin) if len(rows) else []):
            if h[c:c + T, a:a + T].any():
                out.append((c, a) if along_x else (a, c))
    return out


def owners(hole, sq, T):
    """Per hole pixel, the square it is deepest inside (its index; -1 outside the hole): that square's fill is kept
    there. The area's border does not count as an edge."""
    H, W = hole.shape
    best = np.full((H, W), -1.0)
    own = np.full((H, W), -1, np.int32)
    yy, xx = np.arange(H)[:, None], np.arange(W)[None, :]
    far = 10 ** 6
    for k, (ty, tx) in enumerate(sq):
        dy = np.minimum(yy - ty if ty > 0 else far, ty + T - 1 - yy if ty + T < H else far)
        dx = np.minimum(xx - tx if tx > 0 else far, tx + T - 1 - xx if tx + T < W else far)
        inside = (yy >= ty) & (yy < ty + T) & (xx >= tx) & (xx < tx + T)
        d = np.where(inside, np.minimum(dy, dx), -1.0)
        better = hole & (d > best)
        own[better] = k
        best[better] = d[better]
    return own


def shape(hole):
    """(width, length) of a hole, px: a band w wide has a mean distance to its edge of w / 4, and its area / w is
    its length along whatever curve it follows. A pole or a cord is 10-100 times longer than wide, a person 3-5."""
    if not hole.any():
        return 0.0, 0.0
    w = 4.0 * float(ndi.distance_transform_edt(hole)[hole].mean())
    return w, float(hole.sum()) / max(w, 1.0)


class Plan:
    """The squares of one removal's hole at side T, with what each one draws and keeps. The same for every variant
    (and for the refinement of one), so it is made once per removal and size."""

    def __init__(self, hole, T, band=BAND):
        self.T, self.hole = T, hole
        self.squares = squares(hole, T)
        own = owners(hole, self.squares, T)
        done = ~hole
        self.steps = []  # per square: (slices, mask, alpha), or None when it has nothing left to draw
        for k, (ty, tx) in enumerate(self.squares):
            sl = (slice(ty, ty + T), slice(tx, tx + T))
            todo = hole[sl] & ~done[sl]
            if not todo.any():
                self.steps.append(None)
                continue
            mine = own[sl] == k
            dn = ndi.distance_transform_edt(~mine)
            redo = hole[sl] & done[sl] & (dn <= band)  # the earlier squares' fill next to this one's own pixels
            alpha = np.where(mine & todo, 1.0, np.where(redo, np.clip(1 - dn / band, 0, 1), 0.0)).astype(np.float32)
            self.steps.append((sl, todo | redo, alpha))
            done[sl] |= mine
        self._membranes = {}

    def __len__(self):
        return sum(s is not None for s in self.steps)

    def membrane(self, k):
        if k not in self._membranes:
            self._membranes[k] = blend.Membrane(self.steps[k][1])
        return self._membranes[k]

    def fill(self, src, fill_one, progress=None):
        """The area's raw fill, square by square. src: PIL area image (for a refinement, with the chosen fill in the
        hole); fill_one(image, mask, k) -> PIL image of the same size: the engine on square k. progress(done,
        total) after each square. Returns a PIL image (the photo outside the hole)."""
        state = np.asarray(src.convert("RGB")).astype(np.float32)
        n, done = len(self), 0
        for k, step in enumerate(self.steps):
            if step is None:
                continue
            sl, mask, alpha = step
            sub = np.clip(state[sl], 0, 255).round().astype(np.uint8)
            out = np.asarray(fill_one(Image.fromarray(sub), Image.fromarray(mask.astype(np.uint8) * 255), k)
                             .convert("RGB")).astype(np.float32)
            # matched to what the square sees around its hole (the photo, the squares filled before it): the edge
            # differences lightly denoised from outside the hole only (inside it is still the object)
            s = sub.astype(np.float32)
            w = (~mask).astype(np.float32)
            d = ndi.gaussian_filter((s - out) * w[..., None], (1.2, 1.2, 0))
            d /= np.maximum(ndi.gaussian_filter(w, 1.2), 1e-3)[..., None]
            out = out + self.membrane(k).field(d, s)
            a = alpha[..., None]
            state[sl] = np.where(mask[..., None], a * out + (1 - a) * state[sl], state[sl])
            done += 1
            if progress:
                progress(done, n)
        return Image.fromarray(np.clip(state, 0, 255).round().astype(np.uint8))
