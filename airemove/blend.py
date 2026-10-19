"""Seamless blending of a fill into the photo.

1. Gradient-domain (Poisson) correction: the fill keeps its own detail, but a correction field makes it meet the
   original pixels all around the edge — no brightness step, no outline. The fill's colour drift (a smooth offset
   along the edge) is spread through the whole hole; a stretch of edge where the fill shows other content than the
   photo just outside (wall where the photo has sky) is matched only within a few pixels, so the sky's colour does
   not leak into the fill.
2. Texture match: where the fill is smoother than similar-looking surroundings (diffusion and LaMa flatten fine
   mottling), add mid-frequency texture copied from patches of the surroundings with the same colour, scaled to the
   missing amount. Areas whose surroundings have no such patches (a dark doorway next to columns and plants, sky
   next to a stone wall) get none. Pixel-level sensor noise is not touched here: rawdng.write_filled adds that in
   the raw.

Works on the area image (render space, uint8 sRGB-encoded) with the grown removal mask.
"""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu

LUMA = np.array([0.299, 0.587, 0.114], np.float32)
FOUR = ((-1, 0), (1, 0), (0, -1), (0, 1))


def _system(mask, solve, screen=0.0):
    """Sparse 5-point Laplacian (+ screen on the diagonal) over the `solve` pixels, factorized. Neighbours outside
    `mask` are boundary values (returned as (row, y, x) per direction); neighbours inside `mask` but not in `solve`
    are held at 0; the image border has no neighbour (Neumann)."""
    H, W = mask.shape
    ys, xs = np.nonzero(solve)
    n = len(ys)
    idx = -np.ones((H, W), np.int64)
    idx[ys, xs] = np.arange(n)
    diag = np.full(n, screen)
    rows, cols, vals, bnd = [], [], [], []
    for dy, dx in FOUR:
        ny, nx = ys + dy, xs + dx
        ok = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
        diag += ok
        nyc, nxc = np.clip(ny, 0, H - 1), np.clip(nx, 0, W - 1)
        r = np.nonzero(ok & solve[nyc, nxc])[0]
        rows.append(r)
        cols.append(idx[nyc[r], nxc[r]])
        vals.append(-np.ones(len(r)))
        b = np.nonzero(ok & ~mask[nyc, nxc])[0]
        bnd.append((b, nyc[b], nxc[b]))
    rows.append(np.arange(n))
    cols.append(np.arange(n))
    vals.append(diag)
    A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    return splu(A.tocsc()), bnd, ys, xs, n


def _apply(system, d):
    lu, bnd, ys, xs, n = system
    rhs = np.zeros(n)
    for b, by, bx in bnd:
        np.add.at(rhs, b, d[by, bx])
    o = np.zeros(d.shape, np.float64)
    o[ys, xs] = lu.solve(rhs)
    return o


def _box(mask, margin):
    """Slices of mask's bounding box grown by margin (clipped to the image): the filters only need that part."""
    ys, xs = np.nonzero(mask)
    H, W = mask.shape
    return (slice(max(0, ys.min() - margin), min(H, ys.max() + margin + 1)),
            slice(max(0, xs.min() - margin), min(W, xs.max() + margin + 1)))


class Membrane:
    """Correction field inside `mask` from the edge differences just outside it. Three parts, each factorized once
    per mask so every variant only costs a few back-substitutions:
    - harmonic interpolation of the fill's colour drift (the smooth offset along the edge), over the whole hole.
      Large masks are solved on a coarser grid (the field is smooth anyway) and upsampled, so a huge area does not
      take minutes;
    - a screened membrane along the edge (full resolution) for pixel-level mismatches, fading within ~REACH px;
    - the same with a short reach for stretches of edge where the fill shows something else than the photo (wall
      under the edge where the photo has sky, a doorway where it has a column): matched there, but not spread."""

    MAX_UNKNOWNS = 300_000
    REACH = (6.0, 2.5)  # px: decay length of the pixel-level part, of the "other content" part
    # "other content": the edge's colour ratio photo/fill departs from the typical one by more than this much
    # (natural log) in brightness or in hue. Exposure and white-balance drift stay well inside.
    OTHER = (0.5, 0.25)

    def __init__(self, mask):
        self.full_shape = mask.shape
        H0, W0 = mask.shape
        self.edge = ndi.binary_dilation(mask, ndi.generate_binary_structure(2, 1)) & ~mask
        self.f = int(np.ceil(np.sqrt(mask.sum() / self.MAX_UNKNOWNS))) if mask.sum() > self.MAX_UNKNOWNS else 1
        cm = mask
        if self.f > 1:
            f = self.f
            Hc, Wc = -(-H0 // f), -(-W0 // f)
            pad = np.zeros((Hc * f, Wc * f), bool)
            pad[:H0, :W0] = mask
            cm = pad.reshape(Hc, f, Wc, f).any(axis=(1, 3))
        self.mask = cm
        self.harmonic = _system(cm, cm)
        depth = ndi.distance_transform_edt(mask)
        self.local = [_system(mask, mask & (depth <= 5 * r), 1.0 / r ** 2) for r in self.REACH]  # ~0 beyond

    def solve(self, d):
        """d: HxW (only the pixels just outside the mask matter) -> HxW field, harmonic inside, 0 outside."""
        f = self.f
        if f > 1:  # boundary values on the coarse grid: block means of d
            H0, W0 = d.shape
            Hc, Wc = self.mask.shape
            pad = np.zeros((Hc * f, Wc * f))
            pad[:H0, :W0] = d
            d = pad.reshape(Hc, f, Wc, f).mean(axis=(1, 3))
        o = _apply(self.harmonic, d)
        if f > 1:
            o = ndi.zoom(o, f, order=1)[:self.full_shape[0], :self.full_shape[1]]
        return o

    def solve_local(self, d, which=0):
        """d: HxW -> HxW field equal to d at the edge, fading to 0 within a few REACH[which] inside."""
        return _apply(self.local[which], d)

    def drift(self, d, src):
        """Per edge pixel: 1 where the edge difference is the fill's colour drift, -> 0 where the fill shows other
        content than the photo there; and the smoothed difference and its typical value. d, src: HxWx3."""
        b = _box(self.edge, 20)
        edge = self.edge[b]
        e = edge.astype(np.float32)
        den = np.maximum(ndi.gaussian_filter(e, 4.0), 1e-6)[..., None]
        lo = ndi.gaussian_filter(d[b] * e[..., None], (4.0, 4.0, 0)) / den  # difference along the edge, smoothed
        ph = ndi.gaussian_filter(src[b] * e[..., None], (4.0, 4.0, 0)) / den  # the photo there, and the fill
        q = np.log((ph + 10.0) / (np.maximum(ph - lo, 0.0) + 10.0))  # colour ratio photo/fill
        q -= np.median(q[edge], axis=0)
        lum = q.mean(-1)
        hue = np.linalg.norm(q - lum[..., None], axis=-1)
        w = np.ones(d.shape[:2], np.float32)
        w[b] = 1.0 / (1.0 + ((lum / self.OTHER[0]) ** 2 + (hue / self.OTHER[1]) ** 2) ** 2)
        lo_full = np.zeros(d.shape, np.float32)
        lo_full[b] = lo
        return w, lo_full, np.median(lo[edge], axis=0)

    def field(self, d, src):
        """d: HxWx3 edge differences (photo - fill), src: HxWx3 photo -> HxWx3 correction (0 outside the mask).
        The fill's colour drift is spread over the whole hole, pixel-level differences fade within a few pixels,
        stretches of edge with other content in the fill are matched there and not spread."""
        if not self.edge.any():  # the hole is the whole area: nothing to match
            return np.zeros(d.shape, np.float32)
        w, lo, typ = self.drift(d, src)
        other = (lo - typ) * (1.0 - w)[..., None]
        smooth = lo - other
        out = np.empty(d.shape, np.float32)
        for ch in range(3):
            out[..., ch] = (self.solve(smooth[..., ch]) + self.solve_local(d[..., ch] - lo[..., ch])
                            + self.solve_local(other[..., ch], 1))
        return out


def _band(x, s1=1.2, s2=5.0):
    """Mid-frequency detail (surface mottling), above the scale of single-pixel noise."""
    return ndi.gaussian_filter(x, s1) - ndi.gaussian_filter(x, s2)


def _robust_std(v, axis=None):
    med = np.median(v, axis=axis, keepdims=True)
    return 1.4826 * np.median(np.abs(v - med), axis=axis)


def texture_field(src, out, mask, rng, block=32, nearest=12):
    """src, out: HxWx3 float (photo, blended fill). Mid-frequency luminance texture for the hole, made of patches
    from around it. Each place in the hole gets one of the `nearest` patches whose colour matches the fill there;
    the patch only lands on the pixels of that colour, scaled to the texture the fill is missing compared to it.
    Nothing where the fill already has enough, or where no patch around has its colour (a dark doorway next to a
    column and a plant, sky next to a stone wall). Patch levels are robust (median-based): a few dark gaps between
    stones do not count as texture."""
    H, W = mask.shape
    ring_w = max(24, block * 1.5)
    box = _box(mask, int(ring_w) + 2 * block)  # the ring, its patches and the filters' reach
    src, out, mask = src[box], out[box], mask[box]
    h, w = mask.shape
    ring = (ndi.distance_transform_edt(~mask) <= ring_w) & ~mask
    inner = ndi.binary_erosion(mask, iterations=4)
    if ring.sum() < 4 * block * block or inner.sum() < 200:
        return None
    s, h2 = block / 4, block // 2
    bs, bo = _band(src @ LUMA), _band(out @ LUMA)
    # source patches (on a grid, for variety): blocks fully in the ring without a colour step (door or column
    # edges, the skyline…)
    low = ndi.gaussian_filter(src, (s, s, 0))
    step = np.max([ndi.maximum_filter(low[..., ch], block) - ndi.minimum_filter(low[..., ch], block)
                   for ch in range(3)], axis=0)
    ok = ndi.binary_erosion(ring, structure=np.ones((block, block), bool)) & (step < 12 + 0.25 * (low @ LUMA))
    grid = np.zeros_like(ok)
    grid[::block // 4, ::block // 4] = True
    cy, cx = np.nonzero(ok & grid)
    if len(cy) < 8:
        return None
    patches = np.stack([bs[y - h2:y + h2, x - h2:x + h2] for y, x in zip(cy, cx)])
    p_std = np.maximum(_robust_std(patches.reshape(len(cy), -1), axis=1), 1e-3)
    p_col = low[cy, cx]
    # the fill's own colour (around a place, and per pixel) and texture level, from hole pixels only
    m = mask.astype(np.float32)

    def in_hole(a, sigma):
        den = np.maximum(ndi.gaussian_filter(m, sigma), 1e-3)
        if a.ndim == 3:
            return ndi.gaussian_filter(a * m[..., None], (sigma, sigma, 0)) / den[..., None]
        return ndi.gaussian_filter(a * m, sigma) / den

    f_col, f_pix = in_hole(out, s), in_hole(out, s / 2)
    f_lev = np.sqrt(in_hole(bo ** 2, 4.0))

    win = np.outer(np.hanning(block), np.hanning(block)).astype(np.float32) + 1e-3
    T, Wt, W2, P = (np.zeros((h, w), np.float32) for _ in range(4))
    ys, xs = np.nonzero(mask)
    for y0 in range(max(0, ys.min() - h2), ys.max() + 1, h2):
        for x0 in range(max(0, xs.min() - h2), xs.max() + 1, h2):
            cell = (slice(y0, y0 + block), slice(x0, x0 + block))  # cut at the image border
            if not mask[cell].any():
                continue
            yc, xc = min(y0 + h2, h - 1), min(x0 + h2, w - 1)
            c = f_col[yc, xc]
            tol = 8 + 0.12 * float(c @ LUMA)
            match = np.nonzero(np.sum((p_col - c) ** 2, axis=1) < tol * tol)[0]
            if not len(match):
                continue  # nothing around looks like the fill here: no texture
            near = match[np.argsort((cy[match] - yc) ** 2 + (cx[match] - xc) ** 2)[:nearest]]
            k = near[rng.integers(len(near))]
            fp = f_pix[cell]
            ch, cw = fp.shape[:2]
            gate = np.exp(-np.sum((fp - p_col[k]) ** 2, axis=-1) / (2 * tol * tol))  # only on pixels of its colour
            ww = win[:ch, :cw] * gate
            T[cell] += patches[k][:ch, :cw] / p_std[k] * ww
            Wt[cell] += ww
            W2[cell] += ww * ww
            P[cell] += ww * p_std[k]
    T = T / np.sqrt(np.maximum(W2, 1e-9))  # unit level where patches overlap (not averaged down)
    P = P / np.maximum(Wt, 1e-9)
    add = np.sqrt(np.maximum(P ** 2 - f_lev ** 2, 0.0)) * np.clip(Wt, 0, 1)
    if add[inner].max(initial=0) < 0.25:
        return None
    full = np.zeros((H, W), np.float32)
    full[box] = T * add
    return full


def seamless(cand, src, mask, membrane=None, seed=0):
    """cand, src: PIL RGB area images; mask: bool hole (the grown removal mask). Returns the blended PIL image
    (equal to src outside the mask)."""
    c = np.asarray(cand).astype(np.float32)
    s = np.asarray(src).astype(np.float32)
    membrane = membrane or Membrane(mask)
    d = ndi.gaussian_filter(s - c, (1.2, 1.2, 0))  # edge differences, lightly denoised
    out = c + membrane.field(d, s)
    out = np.where(mask[..., None], out, s)
    tex = texture_field(s, out, mask, np.random.default_rng(seed))
    if tex is not None:
        fade = ndi.gaussian_filter(mask.astype(np.float32), 2.0) * mask  # no texture step at the very edge
        out += (tex * fade)[..., None]
    return Image.fromarray(np.clip(out, 0, 255).round().astype(np.uint8))
