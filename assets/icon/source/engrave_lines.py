"""Engraver's hatching from a tone image: evenly spaced lines that follow the form (along the isophotes), swelling in
the shadows and breaking off in the light — like a postage stamp / banknote engraving. Clean by construction: every
mark is a line that describes shading, nothing else.

engrave_lines.py TONE.png MASK.png OUT.png [spacing_px] [solid_level] [contour_px] [nose x,y] [iso] [solid_to]
                 [flare] [strokes] [stroke_px]
  TONE  any image of the subject (a photo or a shaded drawing); MASK  white = the figure
  OUT   2048 px, exactly three colours: ink lines + solid darks + contour, paper figure, field outside
  strokes  drawn features the hatching stops against (the mouth): polylines "x,y x,y ...;x,y ..." in 0-1 coordinates,
           stroke_px wide (at 1024 px)
"""
import math
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

INK, PAPER, FIELD = (11, 11, 12), (239, 233, 220), (245, 197, 24)
tone_p, mask_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]
DSEP = float(sys.argv[4]) if len(sys.argv) > 4 else 7.0  # line spacing at 1024 px
SOLID = float(sys.argv[5]) if len(sys.argv) > 5 else 0.10  # darker than this: solid ink
CONTOUR = float(sys.argv[6]) if len(sys.argv) > 6 else 5.0
# the point fur grows away from (the nose), as fractions of the frame; lines radiate from it like fur
NOSE = tuple(float(v) for v in sys.argv[7].split(",")) if len(sys.argv) > 7 else None
ISO = float(sys.argv[8]) if len(sys.argv) > 8 else 0.35  # how much the shading's isophotes bend the fur lines
N = 1024

L = np.asarray(Image.open(tone_p).convert("L").resize((N, N), Image.LANCZOS)).astype(np.float32) / 255
fig = np.asarray(Image.open(mask_p).convert("L").resize((N, N), Image.LANCZOS)) > 127
# shoulders leave the frame at the bottom (as in the Crafting Apps portraits): columns that reach the lowest 20 %
# are filled down to the edge
for x in range(N):
    col = np.nonzero(fig[:, x])[0]
    if col.size and col.max() > 0.8 * N:
        fig[col.max():, x] = True
SOLID_TO = float(sys.argv[9]) if len(sys.argv) > 9 else 1.0  # solid ink only above this fraction of the height
FLARE = float(sys.argv[10]) if len(sys.argv) > 10 else 0.0  # shoulders widen towards the bottom by this x N
STROKES = [[tuple(float(v) * N for v in pt.split(",")) for pt in poly.split()]
           for poly in (sys.argv[11].split(";") if len(sys.argv) > 11 and sys.argv[11] else [])]
STROKE_W = float(sys.argv[12]) if len(sys.argv) > 12 else 5.0
# highlights drawn in paper on top (the shine on the nose), same format as strokes
SHINES = [[tuple(float(v) * N for v in pt.split(",")) for pt in poly.split()]
          for poly in (sys.argv[13].split(";") if len(sys.argv) > 13 and sys.argv[13] else [])]
CATCH_TO = float(sys.argv[14]) if len(sys.argv) > 14 else 1.0  # glints kept only above this height (the eyes)
# shapes filled with ink under the strokes (the nose), same format, each polygon closed
SHAPES = [[tuple(float(v) * N for v in pt.split(",")) for pt in poly.split()]
          for poly in (sys.argv[15].split(";") if len(sys.argv) > 15 and sys.argv[15] else [])]
# lines are for shadow and depth, as in the Crafting Apps icons: lighter than LIGHT stays clean paper, and the head
# turns away into shadow towards its outline (EDGE = how much darker the rim gets)
LIGHT = float(sys.argv[16]) if len(sys.argv) > 16 else 0.0
EDGE = float(sys.argv[17]) if len(sys.argv) > 17 else 0.0
GAMMA = float(sys.argv[18]) if len(sys.argv) > 18 else 1.3
if FLARE:
    y_start = int(0.66 * N)
    rows = np.nonzero(fig.any(1))[0]
    for y in range(y_start, N):
        xs = np.nonzero(fig[y])[0]
        if not xs.size:
            continue
        e = int(((y - y_start) / (N - y_start)) ** 1.4 * FLARE * N)
        fig[y, max(0, xs.min() - e):min(N, xs.max() + e + 1)] = True
    fig = ndi.binary_closing(fig, iterations=3)
_orig = np.asarray(Image.open(mask_p).convert("L").resize((N, N), Image.LANCZOS)) > 127
# where the figure was widened, the tone is the background's: borrow the nearest fur's tone instead
_, (iy, ix) = ndi.distance_transform_edt(~_orig, return_indices=True)
L = np.where(_orig, L, L[iy, ix])
lo, hi = np.percentile(L[fig], 2), np.percentile(L[fig], 98)
L = np.clip((L - lo) / max(hi - lo, 1e-3), 0, 1)
T = ndi.gaussian_filter(L, 2.0)  # tone that sets the line width
if EDGE:  # form shadow: the rim of the head and of the shoulders turns away from the light
    rim = np.clip(1 - ndi.distance_transform_edt(fig) / (0.13 * N), 0, 1) ** 1.6
    T = np.clip(T - EDGE * rim, 0, 1)

# orientation: along the isophotes (perpendicular to the smoothed gradient), from the structure tensor
G = ndi.gaussian_filter(L, 8.0)
gy, gx = np.gradient(G)
s = 22.0
jxx, jyy, jxy = (ndi.gaussian_filter(v, s) for v in (gx * gx, gy * gy, gx * gy))
phi = 0.5 * np.arctan2(2 * jxy, jxx - jyy)  # gradient direction (mod pi)
coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-9)
# where the tone is flat, wrap around the figure's centre (engravers' default for heads), else follow the isophotes
yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
cy, cx = ndi.center_of_mass(fig)
if NOSE:
    cx, cy = NOSE[0] * N, NOSE[1] * N
radial = np.arctan2(yy - cy, xx - cx)  # fur: away from the nose
w = np.clip(coh * 2, 0, 1) * ISO
vx = w * np.cos(2 * (phi + math.pi / 2)) + (1 - w) * np.cos(2 * radial)
vy = w * np.sin(2 * (phi + math.pi / 2)) + (1 - w) * np.sin(2 * radial)
theta = 0.5 * np.arctan2(ndi.gaussian_filter(vy, 10), ndi.gaussian_filter(vx, 10))  # doubled-angle averaging
DX, DY = np.cos(theta), np.sin(theta)

DTEST = 0.55 * DSEP
occ = np.zeros((N, N), bool)
R = int(math.ceil(DTEST))
disk = (np.mgrid[-R:R + 1, -R:R + 1] ** 2).sum(0) <= DTEST ** 2


def free(x, y):
    xi, yi = int(x), int(y)
    return 0 <= xi < N and 0 <= yi < N and fig[yi, xi] and not occ[yi, xi]


def direction(x, y, prev):
    xi, yi = min(max(int(x), 0), N - 1), min(max(int(y), 0), N - 1)
    dx, dy = DX[yi, xi], DY[yi, xi]
    if prev is not None and dx * prev[0] + dy * prev[1] < 0:
        dx, dy = -dx, -dy
    return dx, dy


def trace(x0, y0, step=1.0, maxlen=3000):
    out = []
    for sign in (1, -1):
        x, y, prev, pts = x0, y0, None, []
        for _ in range(maxlen):
            d = direction(x, y, prev)
            if prev is None:
                d = (d[0] * sign, d[1] * sign)
            mx, my = x + d[0] * step / 2, y + d[1] * step / 2  # RK2
            d2 = direction(mx, my, d)
            x, y = x + d2[0] * step, y + d2[1] * step
            if not free(x, y):
                break
            if prev is not None and d2[0] * prev[0] + d2[1] * prev[1] < 0.7:  # too sharp a turn
                break
            prev = d2
            pts.append((x, y))
        out = pts[::-1] + [(x0, y0)] if sign == 1 else out + pts
    return out[::-1] if False else out


def mark(pts):
    for x, y in pts[::1]:
        xi, yi = int(x), int(y)
        y0, y1, x0, x1 = yi - R, yi + R + 1, xi - R, xi + R + 1
        if y0 < 0 or x0 < 0 or y1 > N or x1 > N:
            ys, xs = np.nonzero(disk)
            ys, xs = ys + y0, xs + x0
            ok = (ys >= 0) & (ys < N) & (xs >= 0) & (xs < N)
            occ[ys[ok], xs[ok]] = True
        else:
            occ[y0:y1, x0:x1] |= disk


def densify(poly, step=1.0):
    """The points of a polyline every `step` px."""
    out = []
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
    return out + [poly[-1]]


for poly in STROKES:  # the hatching stops short of drawn features, as an engraver's lines stop at a contour
    mark(densify(poly))

lines = []
queue = deque()
seeds_grid = [(x, y) for y in np.arange(DSEP, N, DSEP * 3) for x in np.arange(DSEP, N, DSEP * 3)]
seeds_grid.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)  # start at the centre, grow outwards
gi = 0
while True:
    if queue:
        sx, sy = queue.popleft()
    elif gi < len(seeds_grid):
        sx, sy = seeds_grid[gi]
        gi += 1
    else:
        break
    if not free(sx, sy):
        continue
    pts = trace(sx, sy)
    if len(pts) < 10:
        continue
    lines.append(pts)
    mark(pts)
    for i in range(0, len(pts), max(2, int(DSEP / 2))):  # Jobard–Lefer: new seeds at dsep on both sides
        x, y = pts[i]
        dx, dy = direction(x, y, None)
        queue.append((x - dy * DSEP, y + dx * DSEP))
        queue.append((x + dy * DSEP, y - dx * DSEP))
print(f"{len(lines)} lines")

# render at 2x: tapered strokes whose width follows the darkness; solid ink in the deepest shadows; the contour
S = 2 * N
img = Image.new("RGB", (S, S), FIELD)
dr = ImageDraw.Draw(img)
figS = Image.fromarray((fig * 255).astype(np.uint8)).resize((S, S), Image.LANCZOS)
img.paste(PAPER, (0, 0), figS.point(lambda v: 255 if v > 127 else 0))
WMAX, WMIN = 0.78 * DSEP, 0.35  # even the darkest hatching keeps a gap: lines, not blots
for pts in lines:
    p = np.array(pts, np.float32)
    if len(p) < 3:
        continue
    t = T[np.clip(p[:, 1].astype(int), 0, N - 1), np.clip(p[:, 0].astype(int), 0, N - 1)]
    wid = WMAX * np.clip((1 - t - LIGHT) / (1 - LIGHT), 0, 1) ** GAMMA
    d = np.gradient(p, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-6)
    nrm = np.stack([-d[:, 1], d[:, 0]], 1)
    on = wid >= WMIN
    i = 0
    while i < len(p):  # each run of visible width is one polygon
        if not on[i]:
            i += 1
            continue
        j = i
        while j < len(p) and on[j]:
            j += 1
        if j - i >= 2:
            seg, ww, nn = p[i:j], wid[i:j, None] / 2, nrm[i:j]
            left, right = (seg + nn * ww) * 2, (seg - nn * ww) * 2
            poly = [tuple(v) for v in left] + [tuple(v) for v in right[::-1]]
            dr.polygon(poly, fill=INK)
        i = j
a = np.asarray(img).copy()
Ls = ndi.gaussian_filter(L, 1.5)
solid = ndi.binary_closing(ndi.binary_opening(Ls < SOLID, iterations=2), iterations=3) & fig
solid = ndi.binary_fill_holes(solid) & fig
solid[int(SOLID_TO * N):] = False
catch = ndi.binary_dilation(solid & (ndi.gaussian_filter(L, 1.0) > 0.55), iterations=1)  # eye glints stay paper
catch[int(CATCH_TO * N):] = False
solidS = np.asarray(Image.fromarray(solid.astype(np.uint8) * 255).resize((S, S), Image.LANCZOS)) > 127
catchS = np.asarray(Image.fromarray(catch.astype(np.uint8) * 255).resize((S, S), Image.LANCZOS)) > 127
a[solidS] = INK
a[catchS] = PAPER
figb = np.asarray(figS) > 127
ring = ndi.binary_dilation(figb, iterations=int(CONTOUR * 2)) & ~figb
a[ring] = INK
img = Image.fromarray(a)
dr = ImageDraw.Draw(img)
for poly in SHAPES:
    dr.polygon([(x * 2, y * 2) for x, y in poly], fill=INK)
for poly in STROKES:  # drawn features on top, with round ends
    pts = [(x * 2, y * 2) for x, y in densify(poly, 2.0)]
    w = STROKE_W * 2
    dr.line(pts, fill=INK, width=int(round(w)), joint="curve")
    for x, y in (pts[0], pts[-1]):
        dr.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=INK)
for poly in SHINES:
    pts = [(x * 2, y * 2) for x, y in densify(poly, 2.0)]
    w = STROKE_W * 2
    dr.line(pts, fill=PAPER, width=int(round(w)), joint="curve")
    for x, y in (pts[0], pts[-1]):
        dr.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=PAPER)
img.save(out_p)
print("saved", out_p)
