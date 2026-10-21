"""Removals on ordinary pictures end to end, without LightCraft, for the CI runners: tools/ci_smoke.py remove DIR runs
this with the install's own Python. DIR is an install with LaMa; the app's code is imported from DIR.

For each format a synthetic picture is made here: a red disc on a textured ground, with a light block that makes the
orientation unambiguous.
  - JPEG: EXIF orientation 6 (shown turned), a colour profile, and a thumbnail in its EXIF;
  - PNG: with an alpha channel;
  - TIFF: 16-bit, orientation 6, a colour profile, Deflate;
  - WebP: lossless;
  - HEIC: EXIF orientation 6 (pillow-heif reads it upright);
  - AVIF: a colour profile.
Then what the window does when a picture is opened on its own: airemove.Session(None, ..., path).prepare() (base.png
is the picture as shown; the orientation found), a removal of the disc with LaMa on the processor, "Save as ..."
(Session.write_all: <stem>-AIRemove.<ext>), the project reopened in a new session and saved again.

Checks per format: the orientation found is the picture's; the result has the same format, size and bit depth; the disc
is gone (its colour is the ground's around it); outside the removal's area nothing changed (exactly for PNG, TIFF and
lossless WebP; within a level or two for JPEG, HEIC and AVIF, which are coded again); the colour profile, the EXIF
orientation and the alpha channel are kept and the EXIF's thumbnail is not; reopened, the project has the removal and
its result, and saving again rewrites the same file. Exit status 1 at the first check that fails.

  ci_pictures.py DIR [--keep FOLDER]    FOLDER: where the pictures and results are left to look at (default: a
                                        temporary folder, deleted)
"""
import argparse
import io
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageCms

H, W = 800, 1200  # stored size
DISC = (520, 760, 70)  # centre y, x and radius, stored pixels
LOSSY_MEAN = {"JPEG": 0.6, "HEIC": 2.5, "AVIF": 2.5}  # mean change allowed outside the area, 8-bit levels


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok   " + what, flush=True)


def scene():
    """The stored picture, sRGB 0..1: a greenish ground with a gradient and texture, a light block near a corner, the
    red disc."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    lum = 0.35 + 0.15 * x / W + 0.04 * np.sin(x / 23.0) * np.cos(y / 31.0)
    rgb = lum[..., None] * np.array([0.85, 1.0, 0.8]) + np.random.default_rng(2).normal(0, 0.01, (H, W, 3))
    rgb[60:220, 80:300] = (0.9, 0.88, 0.8)
    cy, cx, r = DISC
    rgb[(y - cy) ** 2 + (x - cx) ** 2 <= r * r] = (0.85, 0.08, 0.06)
    return np.clip(rgb, 0, 1)


def exif_with_thumbnail(orientation, thumbnail):
    """An EXIF block (little-endian TIFF) with Orientation in IFD0 and a JPEG thumbnail in IFD1, as cameras write."""
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHIHH", 274, 3, 1, orientation, 0) + struct.pack("<I", 26)
    ifd1 = (struct.pack("<H", 2) + struct.pack("<HHII", 0x0201, 4, 1, 56)
            + struct.pack("<HHII", 0x0202, 4, 1, len(thumbnail)) + struct.pack("<I", 0))
    return b"Exif\x00\x00" + b"II*\x00" + struct.pack("<I", 8) + ifd0 + ifd1 + thumbnail


def make(folder, fmt, rgb):
    """The picture in this format; returns its path."""
    a8 = (rgb * 255).round().astype(np.uint8)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    turned = Image.Exif()
    turned[274] = 6
    if fmt == "JPEG":
        p = folder / "pic-jpeg.jpg"
        thumb = io.BytesIO()
        Image.fromarray(a8).resize((160, 107)).save(thumb, "JPEG", quality=70)
        Image.fromarray(a8).save(p, "JPEG", quality=90, exif=exif_with_thumbnail(6, thumb.getvalue()), icc_profile=icc)
    elif fmt == "PNG":
        p = folder / "pic-png.png"
        alpha = np.full((H, W), 255, np.uint8)
        alpha[:40] = 128  # a half-transparent band along the top
        Image.fromarray(np.dstack([a8, alpha])).save(p)
    elif fmt == "TIFF":
        p = folder / "pic-tiff.tif"
        tifffile.imwrite(p, (rgb * 65535).round().astype(np.uint16), photometric="rgb", compression="zlib",
                         metadata=None, extratags=[(274, 3, 1, 6, True), (34675, 7, len(icc), icc, True)])
    elif fmt == "WebP":
        p = folder / "pic-webp.webp"
        Image.fromarray(a8).save(p, "WEBP", lossless=True)
    elif fmt == "HEIC":
        p = folder / "pic-heic.heic"
        Image.fromarray(a8).save(p, "HEIF", quality=90, exif=turned.tobytes())
    else:
        p = folder / "pic-avif.avif"
        Image.fromarray(a8).save(p, "AVIF", quality=90, icc_profile=icc)
    return p


def red(a, maxv):
    """The red disc's pixels in an H x W x 3 array."""
    v = a.astype(np.float64) / maxv
    return (v[..., 0] > 0.6) & (v[..., 1] < 0.3) & (v[..., 2] < 0.3)


def one(ar, imagefile, fmt, folder):
    from scipy import ndimage as ndi
    p = make(folder, fmt, scene())
    args = argparse.Namespace(id=None, raw=str(p), variants=None, auto=None, shadow=False)
    s = ar.Session(None, args, p)
    s.prepare()
    src = s.raw
    expect(isinstance(src, imagefile.ImageFile) and src.format_name == fmt and s.out_format == fmt,
           f"{fmt}: opened on its own as a picture")
    want = (3, False) if src.orientation == 6 else (0, False)  # turned 90 degrees clockwise / as stored
    expect(s.t == want, f"{fmt}: orientation {s.t} (EXIF orientation {src.orientation} as read)")
    orig = src.cfa.copy()
    obj = red(orig, src.maxv)
    # the user's selection: the disc as the window shows it, a few pixels larger
    sel = ndi.binary_dilation(red(np.asarray(s.base), 255), iterations=3)
    t0 = time.time()
    r = s.new_removal(sel)
    s.run_lama(r)
    out, __, updated = s.write_all()
    expect(out == p.with_name(f"{p.stem}-AIRemove{p.suffix}") and out.exists() and not updated,
           f"{fmt}: {out.name} written in {time.time() - t0:.1f}s")
    s.close()

    res = imagefile.ImageFile(out)
    expect(res.format_name == fmt and res.cfa.shape == orig.shape and res.cfa.dtype == orig.dtype,
           f"{fmt}: same format, size {res.cfa.shape[1]}x{res.cfa.shape[0]} and depth ({res.cfa.dtype})")
    y0, y1, x0, x1 = r.box
    area = np.zeros(obj.shape, bool)
    area[y0:y1, x0:x1] = True
    expect(not (obj & ~area).any(), f"{fmt}: the removal's area holds the disc")
    lv = 255.0 / src.maxv
    d = np.abs(res.cfa.astype(np.float64) - orig) * lv
    if fmt in LOSSY_MEAN:
        expect(d[~area].mean() < LOSSY_MEAN[fmt],
               f"{fmt}: outside the area, coded again: mean change {d[~area].mean():.2f} levels")
    else:
        expect(not d[~area].any(), f"{fmt}: outside the area nothing changed")
    ring = ndi.binary_dilation(obj, iterations=40) & ~ndi.binary_dilation(obj, iterations=15)
    inner = ndi.binary_erosion(obj, iterations=6)
    o, f = orig.astype(np.float64) * lv, res.cfa.astype(np.float64) * lv
    before = np.linalg.norm(o[inner].mean(0) - o[ring].mean(0))
    after = np.linalg.norm(f[inner].mean(0) - f[ring].mean(0))
    expect(after < 0.15 * before, f"{fmt}: the disc is gone: colour distance to the ground {before:.0f} -> {after:.1f}")

    with Image.open(out) as im:  # closed again: saving a second time replaces this file
        icc = im.info.get("icc_profile") or (im.tag_v2.get(34675) if fmt == "TIFF" else None)
        exif = im.info.get("exif") or b""
    if fmt in ("JPEG", "TIFF", "AVIF"):
        expect(bool(icc), f"{fmt}: colour profile kept")
    if fmt in ("JPEG", "TIFF"):
        expect(res.orientation == 6, f"{fmt}: EXIF orientation 6 kept")
    if fmt == "JPEG":
        expect(exif and b"\xff\xd8\xff" not in exif, "JPEG: the EXIF's thumbnail (it still shows the disc) is gone")
    if fmt == "PNG":
        expect(res.alpha is not None and np.array_equal(res.alpha, src.alpha), "PNG: alpha channel kept")

    s2 = ar.Session(None, args, p)
    s2.prepare()
    expect(len(s2.removals) == 1 and s2.dng_path == out, f"{fmt}: project reopened: 1 removal, result {out.name}")
    out2, __, updated2 = s2.write_all()
    expect(out2 == out and updated2 and not p.with_name(f"{p.stem}-AIRemove-2{p.suffix}").exists(),
           f"{fmt}: saved again: {out.name} updated")
    s2.close()


def run(d, out):
    sys.path.insert(0, str(d / "airemove"))
    import airemove as ar  # the installed app (its system.ROOT is d: models from d/models, log in d/work)
    import imagefile
    expect(ar.engines.available().get("lama"), f"LaMa installed in {ar.engines.mf.part_dir('lama')}")
    expect(imagefile.heif_available(), "HEIC: pillow-heif installed")
    for fmt in ("JPEG", "PNG", "TIFF", "WebP", "HEIC", "AVIF"):
        one(ar, imagefile, fmt, out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", help="install folder")
    ap.add_argument("--keep", help="leave the files in this folder")
    a = ap.parse_args()
    d = Path(a.dir).expanduser().resolve()
    out = Path(a.keep).resolve() if a.keep else Path(tempfile.mkdtemp(prefix="airemove-ci-pictures-"))
    out.mkdir(parents=True, exist_ok=True)
    print(f"pictures {d} (files in {out})", flush=True)
    try:
        run(d, out)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    finally:
        if not a.keep:
            shutil.rmtree(out, ignore_errors=True)
    print("  ok   removals on pictures end to end", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
