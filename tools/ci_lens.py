"""The panel's preview through the app's lens corrections (airemove.LensWarp, airemove.crop_view), for the CI runners:
tools/ci_smoke.py remove DIR runs this with the install's own Python. DIR's app code is imported.

A synthetic photo in base.png's frame (2400 x 1600, textured, its top a plain sky) and, standing for the app's export
with lens corrections, the same warped by a known lens: barrel, pincushion, a mustache (r² and r⁴ of opposite signs)
with a tangential term, each with a profile's vignetting:
  - the warp is measured within 0.25 px of the known one over the whole photo, the sky's corners included (no high
    power invented where nothing was measured), and the brightening within 2 %;
  - a patch drawn through the measured warp (crop_view) lands where the known lens puts it, through a crop turned by
    1.5° and flipped, within 0.5 px;
  - without a lens, crop_view is the crop the panel drew before (PIL: turned, cut, flipped);
  - a photo with no texture is not measured (None): the panel says so instead of drawing it off;
  - lens_moves: a profile or a manual Distortion move the photo; the other optics settings do not.
Exit status 1 at the first check that fails.

  ci_lens.py DIR
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage as ndi

H, W = 1600, 2400


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


def photo(seed=0):
    """Texture at several scales, a plain sky over the top fifth (where no tile can be measured)."""
    rng = np.random.default_rng(seed)
    a = sum(ndi.gaussian_filter(rng.random((H, W)), s) * w for s, w in ((1.5, 0.6), (6, 2.0), (25, 6.0)))
    a = (a - a.min()) / (a.max() - a.min())
    a[: H // 5] = 0.75 + 0.02 * np.linspace(0, 1, W)[None, :]
    rgb = np.stack([a, a * 0.9 + 0.05, a * 0.8 + 0.1], -1)
    return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def lens_export(A, base, coef, gain):
    """What the app exports with that lens: each corrected pixel from base at source(), brightened by gain()."""
    known = A.LensWarp(np.array(coef, float), np.array(gain, float), {})
    yy, xx = np.mgrid[0:H, 0:W] + 0.5
    sx, sy = known.source(xx, yy, W, H)
    lin = A.srgb_to_lin(base)
    out = np.stack([ndi.map_coordinates(lin[..., k], [sy - 0.5, sx - 0.5], order=1, mode="nearest") for k in range(3)],
                   -1) * known.gain(sx, sy, W, H)[..., None]
    return A.lin_to_srgb8(out), known


def main(app_dir):
    sys.path.insert(0, str(Path(app_dir) / "airemove"))
    import airemove as A

    base = photo()
    work = Path(tempfile.mkdtemp(prefix="ci_lens-"))
    Image.fromarray(base).save(work / "base.png")
    yy, xx = np.mgrid[0:H:8, 0:W:8] + 0.5
    lenses = {"barrel": ([0.935, 0.065, 0, 0, 0, 0], [0, 0.15, 0.35, 0]),
              "pincushion": ([1.0, -0.12, 0, 0, 0, 0], [0, 0.1, 0.2, 0]),
              "mustache": ([0.97, 0.09, -0.06, 0, 0.002, -0.001], [0, 0.3, 0.2, 0.1])}
    for name, (coef, gain) in lenses.items():
        Image.fromarray(lens_export(A, base, coef, gain)[0]).save(work / "lens.png")
        __, known = lens_export(A, base[:2, :2], coef, gain)  # the same lens, for its numbers
        got = A.LensWarp.measure(work / "base.png", work / "lens.png", {"lens_profile": True})
        expect(got is not None, f"{name}: measured")
        kx, ky = known.source(xx, yy, W, H)
        gx, gy = got.source(xx, yy, W, H)
        err = np.hypot(gx - kx, gy - ky)
        expect(err.max() < 0.25, f"{name}: the warp within 0.25 px everywhere, the sky's corners too "
                                 f"(at most {err.max():.3f} px)")
        gk, gg = known.gain(kx, ky, W, H), got.gain(kx, ky, W, H)
        expect(np.abs(gg / gk - 1).max() < 0.02, f"{name}: the brightening within 2 % "
                                                  f"(at most {np.abs(gg / gk - 1).max() * 100:.2f} %)")
        # a patch drawn through the measured lens, turned and flipped as a crop, against the known lens's
        rgba = np.zeros((H, W, 4), np.uint8)
        rgba[..., :3] = base
        rgba[300:1300, 300:2100, 3] = 255
        crop = {"geometry": {"angle": 1.5, "rect": {"x0": 0.08, "y0": 0.1, "x1": 0.92, "y1": 0.95}}, "flip_h": True}
        a = np.asarray(A.crop_view(rgba, crop, got), np.float32)[..., :3].mean(-1)
        b = np.asarray(A.crop_view(rgba, crop, known), np.float32)[..., :3].mean(-1)
        win = np.outer(np.hanning(64), np.hanning(64))
        sh = [np.hypot(*A.LensWarp._shift(a[y - 32:y + 32, x - 32:x + 32], b[y - 32:y + 32, x - 32:x + 32], win)[0])
              for y in range(400, 1000, 150) for x in range(300, 1700, 200)]
        expect(max(sh) < 0.5, f"{name}: drawn through the crop where the known lens puts it (at most {max(sh):.3f} px)")

    # without a lens: the crop as the panel drew it before
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., :3], rgba[..., 3] = base, 255
    for crop in ({"geometry": {"angle": -1.5, "rect": {"x0": 0.1, "y0": 0.05, "x1": 0.95, "y1": 0.8}}, "flip_v": True},
                 {"geometry": {"angle": 3.0, "rect": {"x0": 0.2, "y0": 0.15, "x1": 0.85, "y1": 0.9}}, "flip_h": True}):
        g, c = crop["geometry"], crop["geometry"]["rect"]
        im = Image.fromarray(rgba, "RGBA").rotate(-g["angle"], resample=Image.BICUBIC)
        im = im.crop((round(c["x0"] * W), round(c["y0"] * H), round(c["x1"] * W), round(c["y1"] * H)))
        im = ImageOps.mirror(im) if crop.get("flip_h") else im
        im = ImageOps.flip(im) if crop.get("flip_v") else im
        ref = np.asarray(im, np.float32)
        new = np.asarray(A.crop_view(rgba, crop), np.float32)
        diff = np.abs(ref[60:-60, 60:-60, :3] - new[60:-60, 60:-60, :3]).mean()
        expect(ref.shape == new.shape and diff < 2, f"no lens, {g['angle']}°: the crop as before ({diff:.2f} levels)")

    flat = np.full((H, W, 3), 128, np.uint8)
    Image.fromarray(flat).save(work / "base.png")
    Image.fromarray(flat).save(work / "lens.png")
    expect(A.LensWarp.measure(work / "base.png", work / "lens.png", {}) is None, "a photo with no texture: not measured")
    expect(A.lens_moves({"lens_profile": True}) and A.lens_moves({"distortion": -20}), "a profile or a Distortion move it")
    expect(not A.lens_moves({"lens_profile": False, "distortion": 0, "vignetting": 30, "remove_ca": True}),
           "manual vignetting and CA do not (base.png has them)")
    print("lens: all checks passed")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    except Failed as e:
        print("  FAILED  " + str(e))
        sys.exit(1)
