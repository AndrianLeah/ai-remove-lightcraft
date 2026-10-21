"""The camera's own lens-distortion correction, for showing a photo as the camera (and its JPEG) does.

AI Remove works on the photo as the sensor records it: base.png comes from LightCraft without lens corrections, and
the removals go back into the RAW's own pixels, so LightCraft's lens correction applies to them as to the rest. Many
compact and mirrorless cameras rely on the RAW's correction tables instead of a lens profile, and LightCraft applies
them for few models (Sony: the A7R VI only), so the window would show those photos with the lens's barrel
distortion. Lens maps between the two frames: the window shows the corrected one and turns clicks and strokes back.

Sony (ARW, tag 0x7037 DistortionCorrParams): the number of knots n, then one value per knot. A point shown at radius r
(1 = half the diagonal, about the frame's centre) is on the sensor at r * f(r), f = 1 + value / 2**14 interpolated
between the knots at r = i / (n - 1). Checked against an RX100 VA's own JPEGs: within 1 px at 1600 x 2400 everywhere.
"""
import re
import struct
from pathlib import Path

import numpy as np
from PIL import Image

SONY_DISTORTION = 0x7037
MESH = 32  # px: the warp is exact at the corners of squares this big, bilinear inside (error far below a pixel)


def sony_distortion(path):
    """The knots of a Sony RAW's distortion table, or None (not a TIFF-based RAW, no table, a table of zeros)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8 or head[:2] not in (b"II", b"MM"):
                return None
            end = "<" if head[:2] == b"II" else ">"
            if struct.unpack(end + "H", head[2:4])[0] != 42:
                return None
            size = Path(path).stat().st_size
            todo, seen = [struct.unpack(end + "I", head[4:8])[0]], set()
            while todo and len(seen) < 32:
                off = todo.pop(0)
                if off in seen or not 8 <= off < size - 2:
                    continue
                seen.add(off)
                f.seek(off)
                n = struct.unpack(end + "H", f.read(2))[0]
                if n > 1000:
                    continue
                entries = [struct.unpack(end + "HHI4s", f.read(12)) for _ in range(n)]
                todo.append(struct.unpack(end + "I", f.read(4))[0])
                for tag, typ, cnt, val in entries:
                    if tag == 0x14A and typ in (4, 13) and 0 < cnt <= 16:  # SubIFDs: Sony keeps the tables there
                        if cnt == 1:
                            todo.append(struct.unpack(end + "I", val)[0])
                        else:
                            f.seek(struct.unpack(end + "I", val)[0])
                            todo += struct.unpack(end + "I" * cnt, f.read(4 * cnt))
                    elif tag == SONY_DISTORTION and typ == 8 and 3 <= cnt <= 64:  # signed shorts
                        f.seek(struct.unpack(end + "I", val)[0])
                        vals = struct.unpack(end + "h" * cnt, f.read(2 * cnt))
                        k = vals[0]
                        if 2 <= k <= cnt - 1 and any(vals[1:k + 1]):
                            return list(vals[1:k + 1])
    except (OSError, struct.error):
        return None
    return None


def for_photo(path, size):
    """A Lens for the photo at `path` whose base.png is `size` (width, height), or None. A result
    (<stem>-AIRemove.dng) has no tables of its own: its original RAW next to it has them."""
    path = Path(path)
    knots = sony_distortion(path)
    m = re.match(r"(.+)-AIRemove(?:-\d+)?$", path.stem)
    if knots is None and m and path.parent.is_dir():
        for p in sorted(path.parent.glob(m.group(1) + ".*")):
            if p != path and p.suffix.lower() == ".arw" and (knots := sony_distortion(p)):
                break
    try:
        return Lens(knots, size) if knots else None
    except ValueError:  # a table that does not map one radius to one radius: shown as recorded
        return None


class Lens:
    """Between the sensor's frame (base.png's pixels: "sensor") and the corrected one ("shown"), same size."""

    def __init__(self, knots, size):
        self.W, self.H = size
        self.f = 1 + np.asarray(knots, float) / 2 ** 14
        self.rk = np.linspace(0, 1, len(self.f))
        self.cx, self.cy = (self.W - 1) / 2, (self.H - 1) / 2
        self.R = float(np.hypot(self.cx, self.cy))
        rr = np.linspace(0, 1.5, 6001)
        g = rr * np.interp(rr, self.rk, self.f)  # shown radius -> sensor radius
        if not np.all(np.diff(g) > 0):
            raise ValueError("not monotonic")
        self._rr, self._g = rr, g
        self._mesh = None

    def to_sensor(self, x, y):
        """A point of the shown (corrected) frame on the sensor."""
        dx, dy = x - self.cx, y - self.cy
        s = np.interp(np.hypot(dx, dy) / self.R, self.rk, self.f)
        return self.cx + dx * s, self.cy + dy * s

    def to_shown(self, x, y):
        """A point of the sensor where the corrected frame shows it."""
        dx, dy = x - self.cx, y - self.cy
        r = np.hypot(dx, dy) / self.R
        s = np.interp(r, self._g, self._rr) / np.maximum(r, 1e-9)
        return self.cx + dx * s, self.cy + dy * s

    def warp(self, img):
        """img (the sensor's frame, base.png's size) as the camera shows it."""
        if self._mesh is None:
            mesh = []
            for y0 in range(0, self.H, MESH):
                y1 = min(y0 + MESH, self.H)
                for x0 in range(0, self.W, MESH):
                    x1 = min(x0 + MESH, self.W)
                    quad = []
                    for x, y in ((x0, y0), (x0, y1), (x1, y1), (x1, y0)):  # PIL: NW, SW, SE, NE
                        quad += self.to_sensor(x, y)
                    mesh.append(((x0, y0, x1, y1), tuple(float(v) for v in quad)))
            self._mesh = mesh
        return img.transform(img.size, Image.MESH, self._mesh, Image.BILINEAR)
