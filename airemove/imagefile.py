"""Ordinary pictures for AI Remove (JPEG, PNG, TIFF, WebP, HEIC/HEIF, AVIF), with the same calls as rawdng.RawDNG:
the picture's own pixels are what a RAW's sensor data is, so a removal works on them in the same way.

- Read as stored: the EXIF orientation is not applied (Session finds it with match_orientation, as for a RAW). HEIC
  is the exception: pillow-heif reads it upright and sets its EXIF orientation to 1.
- render() gives an area as stored (sRGB-encoded 0..1), and fill_region() puts a fill back into exactly those values.
- write_cfa() writes the whole picture in its own format:
  - JPEG: re-encoded with the original's own quantization tables and chroma subsampling, so an untouched pixel moves
    by a level or two;
  - PNG and TIFF: lossless (a compressed TIFF as Deflate);
  - WebP: lossless when the original is, else quality 95;
  - HEIC: quality 70. On an iPhone photo: about 1.3 times the original's size, untouched pixels moving by half a level
    on average (at 90: 2.4 times the size for 0.1 level);
  - AVIF: quality 90 (its untouched pixels move by about a level at any quality, its own lossy coding's cost).
  The colour profile, the XMP and the EXIF go with it. The EXIF loses its thumbnail, which would still show what
  was removed. TIFFs keep their main tags but not their EXIF directory.
- 16-bit TIFFs and greyscale pictures stay what they are; an alpha channel is kept unchanged; a palette PNG comes
  back as RGB (or RGBA), with the same pixels.
"""
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, JpegImagePlugin, PngImagePlugin

from i18n import _

FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".jpe": "JPEG", ".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF",
           ".webp": "WebP", ".heic": "HEIC", ".heif": "HEIC", ".avif": "AVIF"}
EXTS = tuple(FORMATS)
SAVE_AS = {"JPEG": "JPEG", "PNG": "PNG", "WebP": "WEBP", "HEIC": "HEIF", "AVIF": "AVIF"}  # Pillow's format names
# TIFF tags carried over to the result, besides the ones tifffile writes itself (description, software, date,
# resolution): make, model, orientation, artist, copyright, XMP, IPTC, the colour profile
TIFF_KEEP = (271, 272, 274, 315, 33432, 700, 33723, 34675)
ORIENT = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
          5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
          8: Image.Transpose.ROTATE_90}  # EXIF orientation -> what turns the stored picture upright


class Unsupported(ValueError):
    """A picture AI Remove cannot work on, with what to do about it."""


def format_of(path):
    """'JPEG', 'PNG', 'TIFF', 'WebP', 'HEIC', 'AVIF', or None (a RAW, or something else)."""
    return FORMATS.get(Path(path).suffix.lower())


_heif = None


def heif_available():
    """Whether HEIC can be read and written (pillow-heif, registered with Pillow on first use)."""
    global _heif
    if _heif is None:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _heif = True
        except ImportError:
            _heif = False
    return _heif


def exif_without_thumbnail(data):
    """The EXIF block written again by Pillow: the same tags, without the embedded thumbnail (IFD1)."""
    if not data:
        return None
    ex = Image.Exif()
    ex.load(data)
    return ex.tobytes()


def webp_lossless(path):
    """Whether a WebP file holds a lossless (VP8L) picture."""
    data = Path(path).read_bytes()
    pos = 12
    while pos + 8 <= len(data):
        tag, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        if tag in (b"VP8 ", b"VP8L"):
            return tag == b"VP8L"
        pos += 8 + size + (size & 1)
    return False


class ImageFile:
    def __init__(self, path):
        self.path = str(path)
        self.format_name = format_of(path)
        if self.format_name is None:
            raise Unsupported(_("{file} is not a picture AI Remove can open.", file=Path(path).name))
        self.alpha, self.gray, self.meta = None, False, {}
        if self.format_name == "TIFF":
            rgb = self._read_tiff()
        else:
            rgb = self._read_pillow()
        self.cfa = np.ascontiguousarray(rgb)  # H x W x 3, uint8 or uint16: what RawDNG calls its CFA
        self.maxv = float(np.iinfo(self.cfa.dtype).max)
        self.frame = (0, 0) + self.cfa.shape[:2]

    # ---------------------------------------------------------------- reading
    def _read_pillow(self):
        name = Path(self.path).name
        if self.format_name == "HEIC" and not heif_available():
            raise Unsupported(_("{file}: HEIC pictures need pillow-heif, which this install does not have. Run the "
                                "AI Remove installer again to add it.", file=name))
        if self.format_name == "PNG" and self._png_16bit_colour():
            raise Unsupported(_("{file} is a 16-bit colour PNG, which AI Remove cannot keep at 16 bits yet: save it "
                                "as a 16-bit TIFF and open that.", file=name))
        with Image.open(self.path) as im:  # read whole, then closed: Windows would not let it be replaced while open
            if getattr(im, "n_frames", 1) > 1 and im.format not in ("MPO", "HEIF"):
                raise Unsupported(_("{file} is animated: AI Remove works on still pictures.", file=name))
            im.load()
            self._keep_meta(im)
            return self._pixels(im, name)

    def _keep_meta(self, im):
        """What the result is written with: its metadata, and how a JPEG or a WebP was coded."""
        info = im.info
        self.meta = {"exif": exif_without_thumbnail(info.get("exif")), "icc_profile": info.get("icc_profile"),
                     "xmp": info.get("xmp"), "dpi": info.get("dpi")}
        if self.format_name == "JPEG":
            self.meta.update(qtables=getattr(im, "quantization", None), subsampling=JpegImagePlugin.get_sampling(im),
                             progressive=bool(info.get("progressive")), comment=info.get("comment"))
        elif self.format_name == "PNG":
            self.meta["text"] = dict(getattr(im, "text", {}) or {})
        elif self.format_name == "WebP":
            self.meta["lossless"] = webp_lossless(self.path)

    def _pixels(self, im, name):
        """H x W x 3 pixels of a Pillow picture; its alpha channel apart, a grey one as three equal channels."""
        mode = im.mode
        if mode == "P":
            im = im.convert("RGBA" if "transparency" in im.info else "RGB")
            mode = im.mode
        if mode in ("RGBA", "LA"):
            self.alpha = np.asarray(im.getchannel("A")).copy()
            im = im.convert("RGB" if mode == "RGBA" else "L")
            mode = im.mode
        if mode == "RGB":
            return np.asarray(im)
        if mode in ("L", "I;16", "I;16B", "I;16L"):
            self.gray = True
            a = np.asarray(im).astype(np.uint16 if mode.startswith("I;16") else np.uint8)
            return np.repeat(a[..., None], 3, axis=2)
        raise Unsupported(_("{file}: its colours are stored as {mode}, which AI Remove cannot work on: save it as RGB "
                            "and open that.", file=name, mode=mode))

    def _png_16bit_colour(self):
        """PNG header: bit depth 16 with colour (Pillow would read it as 8 bits)."""
        with open(self.path, "rb") as f:
            head = f.read(26)
        return head[24] == 16 and head[25] in (2, 6)

    def _read_tiff(self):
        name = Path(self.path).name
        with tifffile.TiffFile(self.path) as tf:
            p = tf.pages[0]
            a = p.asarray()
            if p.photometric not in (1, 2) or a.dtype not in (np.uint8, np.uint16):
                raise Unsupported(_("{file}: its colours are stored as {mode}, which AI Remove cannot work on: save it "
                                    "as RGB and open that.", file=name, mode=f"{p.photometric.name} {a.dtype}"))
            if p.planarconfig == 2 and a.ndim == 3:  # one plane per channel
                a = np.moveaxis(a, 0, -1)
            self.meta = {"compressed": p.compression != 1,
                         "tags": [(c, int(p.tags[c].dtype), p.tags[c].count, p.tags[c].value)
                                  for c in TIFF_KEEP if c in p.tags],
                         "description": p.tags[270].value if 270 in p.tags else None,
                         "software": p.tags[305].value if 305 in p.tags else None,
                         "datetime": p.tags[306].value if 306 in p.tags else None,
                         "resolution": ((p.tags[282].value, p.tags[283].value) if 282 in p.tags and 283 in p.tags
                                        else None),
                         "resolutionunit": p.tags[296].value if 296 in p.tags else None,
                         "orientation": int(p.tags[274].value) if 274 in p.tags else 1}
        if a.ndim == 2:
            self.gray = True
            return np.repeat(a[..., None], 3, axis=2)
        if a.shape[2] == 2:  # grey + alpha
            self.gray, self.alpha = True, a[..., 1].copy()
            return np.repeat(a[..., :1], 3, axis=2)
        if a.shape[2] >= 4:
            self.alpha = a[..., 3].copy()
        return a[..., :3]

    @property
    def orientation(self):
        """The EXIF orientation of the stored pixels (1: upright)."""
        if self.format_name == "TIFF":
            return self.meta.get("orientation", 1)
        ex = self.meta.get("exif")
        if not ex:
            return 1
        e = Image.Exif()
        e.load(ex)
        return int(e.get(274, 1) or 1)

    def upright(self, long_edge):
        """The picture as it is shown (orientation applied), 8-bit RGB, at most long_edge pixels on its long side:
        base.png for a picture opened on its own."""
        a = self.cfa if self.cfa.dtype == np.uint8 else (self.cfa / 257.0).round().astype(np.uint8)
        im = Image.fromarray(a)
        if self.orientation in ORIENT:
            im = im.transpose(ORIENT[self.orientation])
        im.thumbnail((long_edge, long_edge), Image.LANCZOS)
        return im

    # ---------------------------------------------------------------- RawDNG's calls
    def preview_lum(self):
        """Linear luminance at half resolution, as stored (for matching the shown picture's orientation)."""
        v = self.cfa[::2, ::2].astype(np.float64) / self.maxv
        v = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
        return v.mean(axis=2)

    def global_gain(self):
        return 1.0  # the pixels are their own render space

    def cached_noise(self):
        return 0.0, 0.0

    def render(self, box, gain=None, cfa=None):
        """An area as stored, sRGB-encoded 0..1 (gain: always 1)."""
        y0, y1, x0, x1 = box
        return (self.cfa if cfa is None else cfa)[y0:y1, x0:x1].astype(np.float64) / self.maxv, 1.0

    def fill_region(self, box, filled_srgb, gain, alpha, cfa=None, rng_seed=11):
        """The area's pixels with the fill (0..1, as render gives) blended in where alpha says."""
        y0, y1, x0, x1 = box
        old = (self.cfa if cfa is None else cfa)[y0:y1, x0:x1].astype(np.float64)
        a = np.asarray(alpha, np.float64)[..., None]
        new = a * np.clip(filled_srgb, 0, 1) * self.maxv + (1 - a) * old
        return np.clip(new.round(), 0, self.maxv).astype(self.cfa.dtype)

    def subtract_region(self, box, light, gain, cfa=None):
        """The area's pixels with a reflection's light (HxWx3, linear; gain: always 1) taken away (RawDNG's), in
        linear light and back to the picture's own encoding: what it does not change stays exactly as it was."""
        from rawdng import RawDNG
        y0, y1, x0, x1 = box
        old = (self.cfa if cfa is None else cfa)[y0:y1, x0:x1].astype(np.float64)
        new = RawDNG.oetf(np.clip(RawDNG.inv_oetf(old / self.maxv) - light / gain, 0, None)) * self.maxv
        return np.clip(np.where(light > 0, new, old).round(), 0, self.maxv).astype(self.cfa.dtype)

    def write_cfa(self, out_path, cfa, boxes):
        """The whole picture with `cfa` as its pixels, in its own format, with its metadata (boxes: unused, the
        format is written whole)."""
        a = cfa
        if self.gray:  # back to one channel: the fill's luminance, an untouched pixel exactly as it was
            g = a.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
            a = np.clip(g.round(), 0, self.maxv).astype(cfa.dtype)
        if self.alpha is not None:
            a = np.dstack([a if a.ndim == 3 else a[..., None], self.alpha])
        if self.format_name == "TIFF":
            return self._write_tiff(out_path, a)
        m = self.meta
        im = Image.fromarray(a)  # a 16-bit grey PNG's uint16 comes back as mode I;16
        kw = {k: m[k] for k in ("exif", "icc_profile", "xmp", "dpi") if m.get(k)}
        fmt = self.format_name
        if fmt == "JPEG":
            if m.get("qtables"):
                kw["qtables"] = m["qtables"]
            else:
                kw["quality"] = 95
            if m.get("subsampling", -1) >= 0:
                kw["subsampling"] = m["subsampling"]
            if m.get("comment"):
                kw["comment"] = m["comment"]
            kw.update(progressive=m.get("progressive", False), optimize=True)
        elif fmt == "PNG":
            text = PngImagePlugin.PngInfo()
            for k, v in (m.get("text") or {}).items():
                text.add_itxt(k, str(v))
            kw["pnginfo"] = text
        elif fmt == "WebP":
            kw["lossless"], kw["quality"] = (True, 100) if m.get("lossless") else (False, 95)
        elif fmt == "HEIC":
            heif_available()
            kw["quality"] = 70  # see the module's notes: 90 more than doubled the file for no visible difference
        elif fmt == "AVIF":
            kw["quality"] = 90
        im.save(out_path, SAVE_AS[fmt], **kw)

    def _write_tiff(self, out_path, a):
        m = self.meta
        photometric = "minisblack" if self.gray else "rgb"
        tifffile.imwrite(out_path, a, photometric=photometric, metadata=None,
                         extrasamples=("unassalpha",) if self.alpha is not None else None,
                         compression="zlib" if m.get("compressed") else None,
                         predictor=bool(m.get("compressed")),
                         description=m.get("description"), software=m.get("software") or False,
                         datetime=m.get("datetime"), resolution=m.get("resolution"),
                         resolutionunit=m.get("resolutionunit"),
                         extratags=[(c, dt, n, v, True) for c, dt, n, v in m.get("tags", [])])

    def close(self):
        pass
