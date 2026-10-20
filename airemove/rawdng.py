"""Raw DNG helpers for AI Remove: read the CFA mosaic of a LightCraft raw DNG export, render a region with an
exactly invertible transform (clipped highlights white, as LightCraft shows them), put filled pixels back into the
mosaic with sensor-like noise (clipped again where they reach that white), write a new DNG.

Only uncompressed, strip-based CFA DNGs with a 2x2 pattern (what LightCraft writes with
dngCompression=uncompressed) are supported.
"""
import shutil
import numpy as np
import tifffile
from numpy.lib.stride_tricks import sliding_window_view as swv

XYZD50_TO_SRGB = np.array([[3.1338561, -1.6168667, -0.4906146],
                           [-0.9787684, 1.9161415, 0.0334540],
                           [0.0719453, -0.2289914, 1.4052427]])
CLIP_AT = 0.98  # a CFA value at or above this fraction of WhiteLevel (above black) is clipped
WHITE_RAMP = (0.90, 0.98)  # fill_region: fill pixels from this fraction of the clipped white's level up become clipped


def _rat(v):
    v = list(v)
    if len(v) and isinstance(v[0], (int, np.integer)) and len(v) % 2 == 0 and all(x != 0 for x in v[1::2]):
        return np.array([v[i] / v[i + 1] for i in range(0, len(v), 2)], float)
    return np.array(v, float)


class RawDNG:
    def __init__(self, path):
        self.path = path
        self.tf = tifffile.TiffFile(path)
        p = self.page = self.tf.pages[0]
        if p.photometric != 32803 or p.compression != 1 or p.is_tiled:
            raise ValueError("needs an uncompressed raw CFA DNG (LightCraft export with dngCompression=uncompressed)")
        tg = p.tags
        self.cfa = p.asarray()
        bl = tg[50714].value
        self.black = _rat(bl if isinstance(bl, (tuple, list)) else (bl,))
        dim = tg[50713].value if 50713 in tg else (1, 1)
        self.black = (np.resize(self.black, (2, 2)) if tuple(dim) != (2, 2) else self.black.reshape(2, 2))
        wl = tg[50717].value
        self.white = float(wl[0] if isinstance(wl, (tuple, list)) else wl)
        self.neutral = _rat(tg[50728].value)
        self.fm = _rat(tg[50964].value).reshape(3, 3) if 50964 in tg else None
        self.cm = _rat(tg[50721].value).reshape(3, 3)
        self.active = tuple(tg[50829].value) if 50829 in tg else (0, 0) + self.cfa.shape
        top, left = self.active[:2]
        o = tuple(tg[50719].value) if 50719 in tg else (0, 0)
        s = tuple(tg[50720].value) if 50720 in tg else (self.active[3] - left, self.active[2] - top)
        # visible frame (DefaultCrop inside the active area), in CFA array coordinates: y0, x0, h, w
        self.frame = (top + int(o[1]), left + int(o[0]), int(s[1]), int(s[0]))
        pat = tg[33422].value  # tifffile may give a tuple or raw bytes
        pat = list(pat) if isinstance(pat, (bytes, bytearray)) else pat
        self.pattern = np.array(pat, int).reshape(2, 2)  # 0 R, 1 G, 2 B; origin = active area corner
        self.orientation = int(tg[274].value) if 274 in tg else 1

    # ---------------------------------------------------------------- colour
    def cam_to_srgb(self):
        if self.fm is not None:
            return XYZD50_TO_SRGB @ self.fm @ np.diag(1.0 / self.neutral)
        # fall back to ColorMatrix (XYZ D65 -> camera): camera -> XYZ, white balanced
        xyz2cam = self.cm
        cam2xyz = np.linalg.inv(xyz2cam)
        m = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                      [0.0556434, -0.2040259, 1.0572252]]) @ cam2xyz
        wb = m @ self.neutral
        return m / wb[:, None] if np.all(wb > 0) else m

    def white_cap(self):
        """Camera values (0..1) of the brightest neutral the sensor records: the white-balance neutral scaled so its
        largest channel (green, normally: it clips first on grey and white things) is 1. Its render is a neutral
        white at linear level 1 / max(neutral)."""
        n = np.linalg.solve(self.cam_to_srgb(), np.ones(3))
        return n / n.max(), 1.0 / float(n.max())

    def _phase(self, yy, xx):
        top, left = self.active[:2]
        return (yy - top) % 2, (xx - left) % 2

    def _layout(self, y0, y1, x0, x1):
        """Per pixel of a region: its CFA phase (row, column) and colour channel."""
        yy, xx = np.mgrid[y0:y1, x0:x1]
        py, px = self._phase(yy, xx)
        return py, px, self.pattern[py, px]

    def _clipped(self, reg, ch, blk):
        """Pixels of a region (its raw values `reg`) whose demosaiced colour uses a clipped value of the channel that
        clips first on neutral light: blown sky, white walls in the sun. Highlights where only red or blue clip (a red
        flower) are left as they are."""
        first = int(np.argmax(self.white_cap()[0]))
        hot = (ch == first) & (reg >= blk + CLIP_AT * (self.white - blk))
        if not hot.any():
            return hot
        return swv(np.pad(hot, 1), (3, 3)).any(axis=(-1, -2))  # the 3x3 neighbourhood demosaic reads

    def saturation(self):
        """The sensor's clipped value per CFA phase: the frame's largest value where that reaches the clip level (it
        may sit a little above WhiteLevel), else WhiteLevel."""
        if getattr(self, "_sat", None) is None:
            y0, x0, h, w = self.frame
            py0, px0 = self._phase(y0, x0)
            sat = np.full((2, 2), self.white)
            for i in (0, 1):
                for j in (0, 1):
                    p, q = (py0 + i) % 2, (px0 + j) % 2
                    m = float(self.cfa[y0 + i:y0 + h:2, x0 + j:x0 + w:2].max())
                    if m >= self.black[p, q] + CLIP_AT * (self.white - self.black[p, q]):
                        sat[p, q] = m
            self._sat = sat
        return self._sat

    # ---------------------------------------------------------------- preview for orientation matching
    def preview_lum(self):
        """Luminance of the visible frame at half resolution (2x2 CFA binning), sensor orientation."""
        y0, x0, h, w = self.frame
        a = self.cfa[y0:y0 + h - h % 2, x0:x0 + w - w % 2].astype(np.float64)
        py0, px0 = self._phase(y0, x0)
        blk = np.roll(np.roll(self.black, -py0, 0), -px0, 1)
        a = a - np.tile(blk, (a.shape[0] // 2, a.shape[1] // 2))
        return np.clip(a.reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2).mean(axis=(1, 3)), 0, None)

    # ---------------------------------------------------------------- region render
    def demosaic(self, y0, y1, x0, x1, cfa=None):
        reg = (self.cfa if cfa is None else cfa)[y0:y1, x0:x1].astype(np.float64)
        py, px, ch = self._layout(y0, y1, x0, x1)
        blk = self.black[py, px]
        v = np.clip((reg - blk) / (self.white - blk), 0, None)
        out = np.zeros(reg.shape + (3,))
        k = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], float)
        for c in range(3):
            P = np.pad(np.where(ch == c, v, 0.0), 1, mode="reflect")
            Wt = np.pad((ch == c).astype(float), 1, mode="reflect")
            num = (swv(P, (3, 3)) * k).sum(axis=(-1, -2))
            den = (swv(Wt, (3, 3)) * k).sum(axis=(-1, -2))
            out[..., c] = np.where(ch == c, v, num / np.maximum(den, 1e-9))
        return out, ch, blk

    @staticmethod
    def oetf(x):
        x = np.clip(x, 0, 1)
        return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)

    @staticmethod
    def inv_oetf(y):
        y = np.clip(y, 0, 1)
        return np.where(y <= 0.04045, y / 12.92, np.power((y + 0.055) / 1.055, 2.4))

    def render(self, box, gain=None, cfa=None):
        """Region as sRGB-encoded 0..1 (exactly invertible by fill_region, but for clipped highlights). gain=None:
        from the region's median; pass one gain (global_gain) to keep several regions in the same render space.
        cfa: a working copy.
        Clipped highlights render as a neutral white, as LightCraft shows them: after white balance the channels
        that did not clip would tint them (an overcast sky clipped in all three channels comes out magenta)."""
        y0, y1, x0, x1 = box
        rgb, ch, blk = self.demosaic(y0, y1, x0, x1, cfa)
        hot = self._clipped((self.cfa if cfa is None else cfa)[y0:y1, x0:x1], ch, blk)
        if hot.any():  # no channel brighter than the one that clips first: next to a clipped sky, a dark pixel gets
            # red and blue from it through demosaicing, and would be a magenta fringe
            cap = self.white_cap()[0]
            v = rgb[hot]
            rgb[hot] = np.minimum(v, cap * np.minimum(1.0, v[:, [int(np.argmax(cap))]]))
        lin = np.einsum("ij,hwj->hwi", self.cam_to_srgb(), rgb)
        if gain is None:  # mid-tones near 0.45, but the brightest 0.5 % must not clip (detail lost in the raw)
            lum, top = np.clip(lin.mean(axis=2), 0, None), lin.max(axis=2)
            if hot.any() and (~hot).sum() > 0.05 * hot.size:
                # a clipped sky is no mid-tone, and its brightest pixels are its white, not the fringes demosaicing
                # leaves along its edges
                lum, top = lum[~hot], top[~hot]
                if hot.mean() > 0.005:
                    top = np.append(top, np.full(int(hot.sum()), self.white_cap()[1]))
            gain = min(0.45 / max(1e-6, float(np.percentile(lum, 50))),
                       0.97 / max(1e-6, float(np.percentile(top, 99.5))))
            gain = float(np.clip(gain, 0.5, 64))
        return self.oetf(lin * gain), gain

    def global_gain(self):
        """One render gain for the whole photo (median of a sparse sample of 2x2 CFA quads -> sRGB luminance)."""
        y0, x0, h, w = self.frame
        top, left = self.active[:2]
        y0 += (y0 - top) % 2
        x0 += (x0 - left) % 2
        a = self.cfa[y0:y0 + h - 2:16, x0:x0 + w - 2:16].astype(np.float64)
        q = [self.cfa[y0 + i:y0 + h - 2 + i:16, x0 + j:x0 + w - 2 + j:16].astype(np.float64) for i in (0, 1) for j in (0, 1)]
        ph = [(i, j) for i in (0, 1) for j in (0, 1)]
        rgb = np.zeros(a.shape + (3,))
        cnt = np.zeros(3)
        for (i, j), v in zip(ph, q):
            c = self.pattern[i, j]
            blk = self.black[i, j]
            rgb[..., c] += np.clip((v - blk) / (self.white - blk), 0, None)
            cnt[c] += 1
        rgb /= np.maximum(cnt, 1)
        lum = np.einsum("ij,hwj->hwi", self.cam_to_srgb(), rgb).mean(axis=2)
        return float(np.clip(0.45 / max(1e-6, float(np.median(np.clip(lum, 0, None)))), 0.5, 64))

    # ---------------------------------------------------------------- noise
    def read_noise(self):
        """Read-noise variance (DN^2) from the optical-black borders outside the active area, if the DNG has them."""
        top, left, bottom, right = self.active
        regs = []
        if left >= 24:
            regs.append(self.cfa[top:bottom, 4:left - 8])
        if top >= 24:
            regs.append(self.cfa[4:top - 8, left:right])
        vals = []
        for r in regs:
            for i in (0, 1):
                for j in (0, 1):
                    p = r[i::2, j::2].astype(np.float64)
                    med = np.median(p)
                    if abs(med - self.black.mean()) < 0.02 * (self.white - self.black.mean()):
                        vals.append((1.4826 * np.median(np.abs(p - med))) ** 2)
        return float(np.median(vals)) if vals else None

    def noise_model(self):
        """var(DN) = a*S + b. b from the optical black when available; a from the flattest 8x8 same-colour blocks
        of the frame (2% variance quantile per brightness bin, corrected for the chi-square bias of that quantile)."""
        y0, x0, h, w = self.frame
        top, left = self.active[:2]
        ys, xs = [], []
        q_bias = 61 * (1 - 2 / (9 * 61) - 2.054 * np.sqrt(2 / (9 * 61))) ** 3 / 61  # chi2(61) 2% quantile / mean
        py, px = (y0 - top) % 2, (x0 - left) % 2
        for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)):
            pl = self.cfa[y0 + i:y0 + h:2, x0 + j:x0 + w:2].astype(np.float64) - self.black[(py + i) % 2, (px + j) % 2]
            H, W = (pl.shape[0] // 8) * 8, (pl.shape[1] // 8) * 8
            blk = pl[:H, :W].reshape(H // 8, 8, W // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 64)
            m = blk.mean(1)
            gy, gx = np.mgrid[0:8, 0:8]
            A = np.stack([np.ones(64), gy.ravel(), gx.ravel()], 1)
            coef, *_ = np.linalg.lstsq(A, blk.T, rcond=None)
            v = (blk - (A @ coef).T).var(1) * 64 / 61
            for lo, hi in ((20, 80), (80, 200), (200, 450), (450, 900)):
                s = (m >= lo) & (m < hi)
                if s.sum() > 300:
                    xs.append(m[s].mean()); ys.append(np.quantile(v[s], 0.02) / q_bias)
        xs, ys = np.array(xs), np.array(ys)
        b = self.read_noise()
        if b is not None and len(xs) >= 2:
            a = float(np.sum(xs * (ys - b)) / np.sum(xs * xs))
        elif len(xs) >= 3:
            a, b = np.polyfit(xs, ys, 1)
        else:
            a, b = 0.5, 40.0
        return float(np.clip(a, 0.05, 8.0)), float(np.clip(b, 4.0, 2000.0))

    # ---------------------------------------------------------------- write back
    def cached_noise(self):
        if getattr(self, "_noise", None) is None:
            self._noise = self.noise_model()
        return self._noise

    def fill_region(self, box, filled_srgb, gain, alpha, cfa=None, rng_seed=11):
        """Raw values for a filled region: filled_srgb HxWx3 0..1 in render space (same gain as render), alpha HxW
        0..1 where to replace. Re-mosaics with sensor-like noise and blends over `cfa` (default: the original).
        Where the region has clipped highlights, fill pixels as white as they render become clipped raw values.
        Returns the uint16 region."""
        y0, y1, x0, x1 = box
        py, px, ch = self._layout(y0, y1, x0, x1)
        blk = self.black[py, px]
        lin = self.inv_oetf(filled_srgb) / gain
        cam = np.clip(np.einsum("ij,hwj->hwi", np.linalg.inv(self.cam_to_srgb()), lin), 0, None)
        newv = np.take_along_axis(cam, ch[..., None], axis=2)[..., 0]
        span = self.white - blk
        new_raw = blk + newv * span
        a, b = self.cached_noise()
        rng = np.random.default_rng(rng_seed)
        sig = np.sqrt(np.clip(a * np.clip(newv * span, 0, None) + b, 0, None))
        old = (self.cfa if cfa is None else cfa)[y0:y1, x0:x1].astype(np.float64)
        hot = self._clipped(old, ch, blk)
        t = self._into_white(filled_srgb, gain) if hot.any() else None
        if t is not None and t.any():  # clipped highlights: fill pixels as white as render shows them clip too
            up = np.minimum(blk + newv * span / np.maximum(1 - t, 1e-3), self._clipped_values(old, hot, alpha, py, px))
            new_raw = np.where(t > 0, up, new_raw)
            sig = np.where((t > 0) & (up >= blk + CLIP_AT * span), 0.0,  # clipped values carry no noise
                           np.sqrt(np.clip(a * np.clip(new_raw - blk, 0, None) + b, 0, None)))
        new_raw = new_raw + rng.normal(0, 1, new_raw.shape) * sig
        if hot.any():
            new_raw = np.minimum(new_raw, self.saturation()[py, px])
        return np.clip((alpha * new_raw + (1 - alpha) * old).round(), 0, 65535).astype(np.uint16)

    def _into_white(self, filled_srgb, gain):
        """How far each fill pixel is into the white render gives clipped highlights (0..1), or None when that white
        is beyond what render shows (a glint in a dark area: render's white is not theirs there).
        At 1, fill_region gives the pixel the raw values of the clipped pixels around the hole, so that LightCraft's
        highlight handling treats it as the sky around it. Just below, the pixel climbs towards them as a real
        highlight does: brighter along its own colour, each channel stopping where it clips."""
        lo, hi = WHITE_RAMP
        wr = gain * self.white_cap()[1]  # the clipped white's linear render level
        if wr > 1 / lo:
            return None
        return np.clip((self.inv_oetf(filled_srgb).min(axis=2) / min(wr, 1.0) - lo) / (hi - lo), 0, 1)

    def _clipped_values(self, old, hot, alpha, py, px):
        """Per pixel, the typical raw value of its CFA phase in the region's clipped highlights (`hot`) outside the
        hole: the sensor's clip level where all channels clipped, a channel's own level where it did not."""
        sel = hot & (alpha < 0.01)
        if sel.sum() < 16:
            sel = hot
        out = np.empty_like(old)
        for i in (0, 1):
            for j in (0, 1):
                ph = (py == i) & (px == j)
                v = old[ph & sel]
                out[ph] = np.median(v) if v.size else self.saturation()[i, j]
        return out

    def write_cfa(self, out_path, cfa, boxes):
        """Copy the DNG and overwrite, in place, the rows of `boxes` with the values of `cfa`."""
        shutil.copyfile(self.path, out_path)
        p = self.page
        offs = p.dataoffsets
        rps = p.tags[278].value if 278 in p.tags else p.shape[0]
        W = p.shape[1]
        dt = ("<" if self.tf.byteorder == "<" else ">") + "u2"
        with open(out_path, "r+b") as f:
            for y0, y1, x0, x1 in boxes:
                for yy in range(y0, y1):
                    s = yy // rps
                    f.seek(offs[s] + ((yy - s * rps) * W + x0) * 2)
                    f.write(cfa[yy, x0:x1].astype(dt).tobytes())

    def write_filled(self, out_path, box, filled_srgb, gain, alpha, rng_seed=11):
        """One region straight into a new DNG (kept for the headless --auto mode)."""
        y0, y1, x0, x1 = box
        work = self.cfa.copy()
        work[y0:y1, x0:x1] = self.fill_region(box, filled_srgb, gain, alpha, rng_seed=rng_seed)
        self.write_cfa(out_path, work, [box])
        return self.cached_noise(), int((work[y0:y1, x0:x1] != self.cfa[y0:y1, x0:x1]).sum())

    def close(self):
        self.tf.close()
