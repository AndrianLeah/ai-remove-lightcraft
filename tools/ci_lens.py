"""The camera's lens correction (airemove/lens.py) without a camera, for the CI runners: tools/ci_smoke.py remove DIR
runs this with the install's own Python. DIR's app code is imported.

On a tiny TIFF made like an ARW (the table in a SubIFD, tag 0x7037, an RX100 VA's values):
  - the knots are read; a JPEG, a TIFF without the table and a table of zeros give none;
  - a point goes to the sensor and back to where it was shown (within 0.001 px), the centre stays, a corner of the
    shown frame is inside the sensor's;
  - the warp puts a dot recorded at a sensor point where the corrected frame shows it (within 1 px);
  - a result (<stem>-AIRemove.dng) gets the table of its original ARW next to it.
Exit status 1 at the first check that fails.

  ci_lens.py DIR
"""
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

KNOTS = [1265, 1218, 1083, 860, 562, 209, -179, -580, -972, -1353, -1725]


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


def arw_like(path, values):
    """A little-endian TIFF: IFD0 points (0x14A) to a SubIFD holding tag 0x7037 (signed shorts) = values."""
    sub_at, data_at = 8 + 2 + 12 + 4, 8 + 2 + 12 + 4 + 2 + 12 + 4
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHII", 0x14A, 4, 1, sub_at) + struct.pack("<I", 0)
    sub = struct.pack("<H", 1) + struct.pack("<HHII", 0x7037, 8, len(values), data_at) + struct.pack("<I", 0)
    path.write_bytes(b"II*\x00" + struct.pack("<I", 8) + ifd0 + sub + struct.pack("<" + "h" * len(values), *values))


def main(app_dir):
    sys.path.insert(0, str(Path(app_dir) / "airemove"))
    import lens

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        arw_like(t / "DSC1.ARW", [11] + KNOTS + [0] * 5)
        arw_like(t / "zero.ARW", [11] + [0] * 16)
        Image.new("RGB", (8, 8)).save(t / "pic.jpg")
        Image.new("RGB", (8, 8)).save(t / "pic.tif")
        (t / "DSC1-AIRemove.dng").write_bytes(b"II*\x00" + struct.pack("<I", 0))

        expect(lens.sony_distortion(t / "DSC1.ARW") == KNOTS, "the 11 knots are read from the SubIFD")
        expect(all(lens.sony_distortion(t / n) is None for n in ("zero.ARW", "pic.jpg", "pic.tif")),
               "a table of zeros, a JPEG and a TIFF without the table give none")

        W, H = 1600, 2400
        L = lens.for_photo(t / "DSC1.ARW", (W, H))
        expect(L is not None, "a Lens for the ARW")
        pts = np.array([[0, 0], [100, 200], [800, 1200], [1599, 2399], [1500, 40]], float)
        sx, sy = L.to_sensor(pts[:, 0], pts[:, 1])
        bx, by = L.to_shown(sx, sy)
        expect(np.abs(bx - pts[:, 0]).max() < 1e-3 and np.abs(by - pts[:, 1]).max() < 1e-3,
               "shown -> sensor -> shown comes back within 0.001 px")
        cx, cy = L.to_sensor((W - 1) / 2, (H - 1) / 2)
        expect(abs(cx - (W - 1) / 2) < 1e-9 and abs(cy - (H - 1) / 2) < 1e-9, "the centre stays")
        expect(0 < sx[0] < W and 0 < sy[0] < H,
               f"the shown frame's corner is inside the sensor's ({sx[0]:.0f}, {sy[0]:.0f})")

        p = (300.0, 500.0)  # a dot on the sensor: the corrected view must show it at to_shown(p)
        img = np.zeros((H, W), np.uint8)
        img[int(p[1]) - 2:int(p[1]) + 3, int(p[0]) - 2:int(p[0]) + 3] = 255
        out = np.asarray(L.warp(Image.fromarray(img)), float)
        ys, xs = np.nonzero(out > 64)
        want = L.to_shown(*p)
        got = (xs.mean(), ys.mean())
        expect(np.hypot(got[0] - want[0], got[1] - want[1]) < 1.0,
               f"the warp shows a sensor dot where to_shown says ({got[0]:.1f}, {got[1]:.1f} vs "
               f"{want[0]:.1f}, {want[1]:.1f})")

        R = lens.for_photo(t / "DSC1-AIRemove.dng", (W, H))
        expect(R is not None and list(R.f) == list(L.f), "a result DNG gets its original ARW's table")
        expect(lens.for_photo(t / "pic.jpg", (W, H)) is None, "a picture gets no lens")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    except Failed as e:
        print("FAILED: " + str(e))
        sys.exit(1)
    print("lens: all checks passed")
