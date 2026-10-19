"""Seamless blending of a fill into the photo.

1. Gradient-domain (Poisson) correction: the fill keeps its own detail, but a smooth correction field (harmonic
   inside the hole) makes it meet the original pixels all around the edge — no brightness step, no outline.
2. Texture match: if the fill is smoother than its surroundings (diffusion and LaMa flatten fine mottling), add
   mid-frequency texture copied from patches of the surroundings, scaled to the missing amount. Pixel-level sensor
   noise is not touched here: rawdng.write_filled adds that in the raw.

Works on the area image (render space, uint8 sRGB-encoded) with the grown removal mask.
"""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu

LUMA = np.array([0.299, 0.587, 0.114], np.float32)


class Membrane:
    """Harmonic interpolation inside `mask` of the values just outside it. The Laplacian is factorized once per
    mask, so every variant only costs a few back-substitutions. Large masks are solved on a coarser grid (the
    correction is smooth anyway) and the result upsampled, so a huge area does not take minutes."""

    MAX_UNKNOWNS = 300_000

    def __init__(self, mask):
        self.full_shape = mask.shape
        self.f = int(np.ceil(np.sqrt(mask.sum() / self.MAX_UNKNOWNS))) if mask.sum() > self.MAX_UNKNOWNS else 1
        if self.f > 1:
            f = self.f
            H0, W0 = mask.shape
            Hc, Wc = -(-H0 // f), -(-W0 // f)
            pad = np.zeros((Hc * f, Wc * f), bool)
            pad[:H0, :W0] = mask
            mask = pad.reshape(Hc, f, Wc, f).any(axis=(1, 3))
        self.mask = mask
        H, W = mask.shape
        ys, xs = np.nonzero(mask)
        n = len(ys)
        idx = -np.ones((H, W), np.int64)
        idx[ys, xs] = np.arange(n)
        diag = np.zeros(n)
        rows, cols, vals, self.bnd = [], [], [], []
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = ys + dy, xs + dx
            ok = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)  # image border: no neighbour (Neumann)
            diag += ok
            nyc, nxc = np.clip(ny, 0, H - 1), np.clip(nx, 0, W - 1)
            inm = ok & mask[nyc, nxc]
            r = np.nonzero(inm)[0]
            rows.append(r)
            cols.append(idx[nyc[r], nxc[r]])
            vals.append(-np.ones(len(r)))
            b = np.nonzero(ok & ~mask[nyc, nxc])[0]
            self.bnd.append((b, nyc[b], nxc[b]))
        rows.append(np.arange(n))
        cols.append(np.arange(n))
        vals.append(diag)
        A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
        self.lu = splu(A.tocsc())
        self.ys, self.xs, self.n = ys, xs, n

    def solve(self, d):
        """d: HxW (only the pixels just outside the mask matter) -> HxW field, harmonic inside, 0 outside."""
        f = self.f
        if f > 1:  # boundary values on the coarse grid: block means of d
            H0, W0 = d.shape
            Hc, Wc = self.mask.shape
            pad = np.zeros((Hc * f, Wc * f))
            pad[:H0, :W0] = d
            d = pad.reshape(Hc, f, Wc, f).mean(axis=(1, 3))
        rhs = np.zeros(self.n)
        for b, by, bx in self.bnd:
            np.add.at(rhs, b, d[by, bx])
        o = np.zeros(d.shape, np.float64)
        o[self.ys, self.xs] = self.lu.solve(rhs)
        if f > 1:
            o = ndi.zoom(o, f, order=1)[:self.full_shape[0], :self.full_shape[1]]
        return o


def _band(x, s1=1.2, s2=5.0):
    """Mid-frequency detail (surface mottling), above the scale of single-pixel noise."""
    return ndi.gaussian_filter(x, s1) - ndi.gaussian_filter(x, s2)


def _robust_std(v):
    if v.size < 50:
        return 0.0
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def texture_field(src_l, out_l, mask, rng, block=32):
    """Mid-frequency texture for the hole, made of patches from around it, scaled so that the hole ends up with
    the same amount of texture as its surroundings (0 if the fill already has enough)."""
    H, W = mask.shape
    ring = (ndi.distance_transform_edt(~mask) <= max(24, block * 1.5)) & ~mask
    inner = ndi.binary_erosion(mask, iterations=4)
    if ring.sum() < 4 * block * block or inner.sum() < 200:
        return None
    bs, bo = _band(src_l), _band(out_l)
    r_std, f_std = _robust_std(bs[ring]), _robust_std(bo[inner])
    add = np.sqrt(max(r_std ** 2 - f_std ** 2, 0.0))
    if add < 0.25:
        return None
    # source patches: blocks fully in the ring and without strong structures (edges of doors, frames…)
    local = np.sqrt(ndi.uniform_filter(bs ** 2, block))
    ok = ndi.binary_erosion(ring, structure=np.ones((block, block), bool)) & (local < 1.8 * max(r_std, 1e-3))
    cy, cx = np.nonzero(ok)
    if len(cy) < 8:
        return None
    win = np.outer(np.hanning(block), np.hanning(block)).astype(np.float32) + 1e-3
    T = np.zeros((H + block, W + block), np.float32)
    Wt = np.zeros_like(T)
    ys, xs = np.nonzero(mask)
    h2 = block // 2
    for y0 in range(max(0, ys.min() - h2), min(H, ys.max() + 1), h2):
        for x0 in range(max(0, xs.min() - h2), min(W, xs.max() + 1), h2):
            k = rng.integers(len(cy))
            py, px = cy[k] - h2, cx[k] - h2
            patch = bs[py:py + block, px:px + block]
            if patch.shape != (block, block):
                continue
            T[y0:y0 + block, x0:x0 + block] += patch * win
            Wt[y0:y0 + block, x0:x0 + block] += win
    T = (T / np.maximum(Wt, 1e-3))[:H, :W]
    t_std = _robust_std(T[inner])
    if t_std < 1e-3:
        return None
    return T * (add / t_std)


def seamless(cand, src, mask, membrane=None, seed=0):
    """cand, src: PIL RGB area images; mask: bool hole (the grown removal mask). Returns the blended PIL image
    (equal to src outside the mask)."""
    c = np.asarray(cand).astype(np.float32)
    s = np.asarray(src).astype(np.float32)
    membrane = membrane or Membrane(mask)
    d = ndi.gaussian_filter(s - c, (1.2, 1.2, 0))  # edge differences, lightly denoised
    out = c.copy()
    for ch in range(3):
        out[..., ch] += membrane.solve(d[..., ch]).astype(np.float32)
    out = np.where(mask[..., None], out, s)
    tex = texture_field(s @ LUMA, out @ LUMA, mask, np.random.default_rng(seed))
    if tex is not None:
        fade = ndi.gaussian_filter(mask.astype(np.float32), 2.0) * mask  # no texture step at the very edge
        out += (tex * fade)[..., None]
    return Image.fromarray(np.clip(out, 0, 255).round().astype(np.uint8))
