"""The original's EXIF in the DNG AI Remove writes (airemove/exifcopy.py), for the CI runners: tools/ci_smoke.py
remove DIR runs this with the install's own Python. DIR's app code is imported.

LightCraft's raw DNG export has no EXIF IFD, only an XMP packet; exifcopy copies the original's back. On synthetic
files (no camera raw on the runners):
  - an original as a big-endian TIFF raw (as a NEF): its EXIF (exposure, aperture, ISO, focal length, lens, the
    capture time) and GPS (latitude, longitude) and its date, artist and copyright end up in a little-endian DNG
    (as LightCraft writes it), every value in the DNG's byte order; the MakerNote and the Interoperability IFD are
    left out;
  - the DNG's own data is untouched: its image, its SubIFD's raw data and its XMP read back the same;
  - a second pass leaves the DNG as it is;
  - a Canon CR3 (its CMT1, CMT2 and CMT4 boxes) and a raw that embeds a JPEG with EXIF (as Fujifilm's RAF) are
    read too;
  - an original without EXIF: nothing copied, the DNG unchanged.
Exit status 1 at the first check that fails.

  ci_dng_exif.py DIR
"""
import io
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


def tiff(order, ifds):
    """A classic TIFF: ifds is a list of IFDs, each {tag: (type, values)}, the first one the file's; a value
    ("ifd", i) is a pointer to IFD i. ASCII values are str, UNDEFINED/BYTE bytes, others tuples of numbers."""
    o = "<" if order == "I" else ">"
    fmt = {3: "H", 4: "I", 5: "I", 13: "I"}

    def encode(typ, val, offsets):
        if isinstance(val, tuple) and val and val[0] == "ifd":
            return struct.pack(o + "I", offsets[val[1]]), 1
        if typ == 2:
            return val.encode() + b"\x00", len(val) + 1
        if typ in (1, 7):
            return bytes(val), len(val)
        return b"".join(struct.pack(o + fmt[typ], v) for v in val), len(val) // 2 if typ == 5 else len(val)

    def build(offsets):
        blob, at = bytearray(order.encode() * 2 + struct.pack(o + "HI", 42, 8)), []
        for ifd in ifds:
            at.append(len(blob))
            extra_at = len(blob) + 2 + 12 * len(ifd) + 4
            entries, values = bytearray(struct.pack(o + "H", len(ifd))), bytearray()
            for tag in sorted(ifd):
                typ, val = ifd[tag]
                data, count = encode(typ, val, offsets)
                if len(data) <= 4:
                    field = data.ljust(4, b"\x00")
                else:
                    field = struct.pack(o + "I", extra_at + len(values))
                    values += data + (b"\x00" if len(data) % 2 else b"")
                entries += struct.pack(o + "HHI", tag, typ, count) + field
            blob += entries + struct.pack(o + "I", 0) + values
        return bytes(blob), at
    __, offsets = build([0] * len(ifds))  # where each IFD lands (pointers are 4 bytes either way)
    return build(offsets)[0]


ORIGINAL_IFDS = [
    {271: (2, "TestCam"), 272: (2, "TestCam Z1"), 306: (2, "2026:05:01 10:20:30"), 315: (2, "Jane Doe"),
     33432: (2, "(c) Jane Doe"), 34665: (4, ("ifd", 1)), 34853: (4, ("ifd", 2))},
    {33434: (5, (1, 250)), 33437: (5, (28, 10)), 34855: (3, (400,)), 36867: (2, "2026:05:01 10:20:30"),
     37386: (5, (85, 1)), 42036: (2, "TEST 85mm f/1.8 S"), 37500: (7, b"MAKERNOTE-" * 8), 40965: (4, ("ifd", 3))},
    {0: (1, b"\x02\x03\x00\x00"), 1: (2, "N"), 2: (5, (45, 1, 30, 1, 1234, 100)), 3: (2, "E"),
     4: (5, (9, 1, 10, 1, 0, 1))},
    {1: (2, "R98")},
]


def dng_like(path):
    """A little-endian TIFF shaped like LightCraft's DNG export: a preview first IFD with XMP, a raw SubIFD."""
    preview = (np.arange(64 * 96 * 3) % 251).astype(np.uint8).reshape(64, 96, 3)
    raw = (np.arange(128 * 192) % 4093).astype(np.uint16).reshape(128, 192)
    with tifffile.TiffWriter(path) as tw:
        tw.write(preview, subifds=1, photometric="rgb", extratags=[(700, 1, None, b"<x:xmpmeta>XMP</x:xmpmeta>", True),
                                                                   (50706, 1, 4, b"\x01\x04\x00\x00", True)])
        tw.write(raw, photometric="minisblack")
    return preview, raw


def main(app_dir):
    sys.path.insert(0, str(Path(app_dir) / "airemove"))
    import exifcopy

    work = Path(tempfile.mkdtemp(prefix="ci_dng_exif-"))
    original = work / "original.nef"
    original.write_bytes(tiff("M", ORIGINAL_IFDS))
    dng = work / "result.dng"
    preview, raw = dng_like(dng)
    with tifffile.TiffFile(dng) as tf:
        expect("ExifTag" not in tf.pages[0].tags, "the DNG has no EXIF, as LightCraft's export")
    said = exifcopy.copy_exif(original, dng)
    expect(said.startswith("6 EXIF tags, GPS (5 tags)") and "artist" in said and "copyright" in said,
           f"copied: {said}")
    with tifffile.TiffFile(dng) as tf:
        p = tf.pages[0]
        exif, gps = p.tags["ExifTag"].value, p.tags["GPSTag"].value
        expect(exif["ExposureTime"] == (1, 250) and exif["FNumber"] == (28, 10) and exif["FocalLength"] == (85, 1),
               "exposure, aperture and focal length, in the DNG's byte order")
        expect(exif["ISOSpeedRatings"] == 400 and exif["LensModel"] == "TEST 85mm f/1.8 S"
               and exif["DateTimeOriginal"] == "2026:05:01 10:20:30", "ISO, lens and capture time")
        expect("MakerNote" not in exif and "InteroperabilityTag" not in exif, "no MakerNote, no Interoperability IFD")
        expect(gps["GPSLatitudeRef"] == "N" and tuple(gps["GPSLatitude"]) == (45, 1, 30, 1, 1234, 100)
               and gps["GPSLongitudeRef"] == "E", "GPS latitude and longitude")
        expect(p.tags["Artist"].value == "Jane Doe" and p.tags["Copyright"].value == "(c) Jane Doe"
               and p.tags["DateTime"].value == "2026:05:01 10:20:30", "date, artist and copyright in the first IFD")
        expect(np.array_equal(p.asarray(), preview), "the first IFD's image as it was")
        expect(np.array_equal(tf.pages[0].pages[0].asarray(), raw), "the raw SubIFD's data as it was")
        expect(p.tags["XMP"].value == b"<x:xmpmeta>XMP</x:xmpmeta>", "the XMP packet as it was")
    size = dng.stat().st_size
    expect(exifcopy.copy_exif(original, dng).startswith("the DNG has EXIF already") and dng.stat().st_size == size,
           "a second pass leaves it as it is")

    # a Canon CR3: ftyp crx, then moov / Canon's uuid / CMT1 (first IFD), CMT2 (EXIF), CMT4 (GPS), little-endian
    def box(kind, payload):
        return struct.pack(">I4s", 8 + len(payload), kind) + payload
    cmt1 = tiff("I", [{271: (2, "Canon"), 315: (2, "Jane Doe"), 33432: (2, "(c) Jane Doe")}])
    cmt2 = tiff("I", [ORIGINAL_IFDS[1]] + [ORIGINAL_IFDS[3]] * 3)  # its pointer to IFD 3 (Interoperability) left in
    cmt4 = tiff("I", [ORIGINAL_IFDS[2]])
    uuid = box(b"uuid", b"\x85\xc0\xb6\x87\x82\x0f\x11\xe0\x81\x11\xf4\xce\x46\x2b\x6a\x48"
               + box(b"CMT1", cmt1) + box(b"CMT2", cmt2) + box(b"CMT4", cmt4))
    cr3 = work / "original.cr3"
    cr3.write_bytes(box(b"ftyp", b"crx \x00\x00\x00\x01crx isom") + box(b"moov", uuid) + box(b"mdat", b"\x00" * 64))
    dng2 = work / "result2.dng"
    dng_like(dng2)
    said = exifcopy.copy_exif(cr3, dng2)
    with tifffile.TiffFile(dng2) as tf:
        p = tf.pages[0]
        expect(p.tags["ExifTag"].value["LensModel"] == "TEST 85mm f/1.8 S" and p.tags["GPSTag"].value["GPSLatitudeRef"]
               == "N" and p.tags["Artist"].value == "Jane Doe", f"a CR3's CMT boxes: {said}")

    # a raw that embeds a JPEG with EXIF (as a RAF): found after its own header
    exif = Image.Exif()
    exif[271] = "Fujitest"
    exif.get_ifd(0x8769)[42036] = "XF 23mm F2"
    exif.get_ifd(0x8769)[33434] = 1 / 500
    jpeg = io.BytesIO()
    Image.new("RGB", (16, 16), (90, 120, 150)).save(jpeg, "JPEG", exif=exif)
    raf = work / "original.raf"
    raf.write_bytes(b"FUJIFILMCCD-RAW 0201" + b"\x00" * 140 + jpeg.getvalue() + b"\x00" * 256)
    dng3 = work / "result3.dng"
    dng_like(dng3)
    said = exifcopy.copy_exif(raf, dng3)
    with tifffile.TiffFile(dng3) as tf:
        expect(tf.pages[0].tags["ExifTag"].value["LensModel"] == "XF 23mm F2",
               f"a raw's embedded JPEG EXIF: {said}")

    plain = work / "plain.tif"
    tifffile.imwrite(plain, np.zeros((8, 8), np.uint8))
    dng4 = work / "result4.dng"
    dng_like(dng4)
    before = dng4.read_bytes()
    said = exifcopy.copy_exif(plain, dng4)
    expect(said == "no EXIF found in the original" and dng4.read_bytes() == before, "no EXIF: the DNG unchanged")
    print("dng exif: all checks passed")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    except Failed as e:
        print("  FAILED  " + str(e))
        sys.exit(1)
