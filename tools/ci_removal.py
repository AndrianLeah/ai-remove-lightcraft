"""One removal end to end, without LightCraft, for the CI runners: tools/ci_smoke.py remove DIR runs this with the
install's own Python. DIR is an install with LaMa (installer/bootstrap.(ps1|sh) --models lama --no-lightcraft); the
app's code is imported from DIR, so its models are DIR's.

The photo is synthetic, made here: a raw DNG laid out like LightCraft's export (dngCompression=uncompressed: one
16-bit CFA image in strips, optical-black borders, 2x2 black levels, ForwardMatrix, a DefaultCrop, Orientation 6 = a
portrait photo) with a red disc on a gently textured ground and a corner of blown sky. base.png is that photo as
LightCraft would develop and export it (upright, half size, its own tone curve), and the selection is the disc in that
frame. Then what the window does, with the app's own code: airemove.Session as offline scripts use it (orientation
matching, the removal's area, LaMa on the processor, the blend, the fill put back into the mosaic with sensor-like
noise), "Save in LightCraft" (Session.write_all: <stem>-AIRemove.dng, imported and stacked through a stand-in for
LightCraft's control channel) and the .airemove project; then the project reopened in a new session and saved again.

Checks: the orientation is found; the blown sky renders neutral white (not the magenta its unequal channel clips
give after white balance) and, filled with that white, goes back as the sensor's clipped values; the DNG reads back
with the export's tags; every sensor value of the disc changed and the disc is gone (its colour is the ground's around
it, with sensor-like noise); nothing changed outside the removal's area or farther than a few pixels from the disc; the
project lists the removal; reopened, it rebuilds the same sensor data, and saving again rewrites the same file. A part
of a split selection waiting for its model (Session.plan_removal): its area is not rendered until its first variant,
and it still waits once the project is reopened, where LaMa then makes it. Exit status 1 at the first check that
fails.

  ci_removal.py DIR [--keep FOLDER]    FOLDER: where the photo, base.png, the DNG and the project are left to look
                                       at (default: a temporary folder, deleted)
"""
import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

H, W = 1024, 1536  # the visible frame (DefaultCropSize), sensor orientation
CROP = 8  # DefaultCropOrigin inside the active area
TOP, LEFT, BOTTOM, RIGHT = 32, 48, 4, 8  # sensor rows / columns around the active area (optical black: read_noise)
BLACK = np.array([[1022.5, 1024.0], [1023.5, 1025.0]])  # BlackLevel per CFA position (RGGB)
WHITE = 15600
SAT = WHITE + 40  # the sensor clips a little above WhiteLevel, as Canon's do
NEUTRAL = np.array([0.52, 1.0, 0.61])  # AsShotNeutral
FORWARD = np.array([[0.60, 0.15, 0.2142], [0.25, 0.70, 0.05], [0.02, 0.10, 0.7049]])  # rows sum to D50 white
NOISE = (0.6, 9.0)  # the sensor's noise: variance = a * signal (DN) + b
DISC = (620, 1040, 64)  # the object: centre y, x and radius in frame pixels (sensor orientation)
SKY = (900, 1300)  # the blown sky: frame pixels below and right of this corner (y, x), far from the disc
PID, LABEL = 1001, "LaMa"  # the photo's id in the stand-in LightCraft; the variant LaMa makes


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok   " + what, flush=True)


def rat(values, den=10000):
    """(S)RATIONAL tag values: numerator, denominator pairs."""
    return tuple(v for x in np.ravel(values) for v in (int(round(float(x) * den)), den))


def frame_grid():
    return np.mgrid[0:H, 0:W].astype(np.float64)


def disc(grow=0.0):
    """The disc (frame, sensor orientation), grown by `grow` pixels."""
    y, x = frame_grid()
    cy, cx, r = DISC
    return (y - cy) ** 2 + (x - cx) ** 2 <= (r + grow) ** 2


def scene():
    """Linear sRGB of the active area: a greenish-grey ground with a slow gradient and texture, a band of shadow
    along the top (from black to dim: rawdng.noise_model measures the sensor's noise in the shadows) and a light
    block, both far from the disc (they also make the orientation unambiguous), a corner of overcast sky far too
    bright for the sensor (clipped in all three channels), the red disc."""
    y, x = np.mgrid[-CROP:H + CROP, -CROP:W + CROP].astype(np.float64)  # frame coordinates
    lum = 0.15 + 0.05 * x / W + 0.025 * np.sin(x / 41.0) * np.cos(y / 57.0)
    lum = np.where(y < 330, lum * (0.01 + 0.4 * np.clip(x, 0, W) / W), lum)
    rgb = lum[..., None] * np.array([0.9, 1.0, 0.82])
    rgb[(y >= 760) & (y < 940) & (x >= 200) & (x < 420)] = (0.6, 0.58, 0.5)
    rgb[(y >= SKY[0]) & (x >= SKY[1])] = (5.6, 6.0, 6.6)
    cy, cx, r = DISC
    rgb[(y - cy) ** 2 + (x - cx) ** 2 <= r * r] = (0.5, 0.05, 0.035)
    return rgb


def write_raw(path, rgb, srgb_from_xyz):
    """The scene through a sensor (RGGB mosaic, black levels, noise) into a DNG laid out like LightCraft's export."""
    ah, aw = rgb.shape[:2]
    cam = np.einsum("ij,hwj->hwi", np.linalg.inv(srgb_from_xyz @ FORWARD), rgb) * NEUTRAL  # before white balance
    rows, cols = TOP + ah + BOTTOM, LEFT + aw + RIGHT
    yy, xx = np.mgrid[0:rows, 0:cols]
    py, px = (yy - TOP) % 2, (xx - LEFT) % 2
    black = BLACK[py, px]
    ch = np.array([[0, 1], [1, 2]])[py, px]
    signal = np.zeros((rows, cols))
    act = (slice(TOP, TOP + ah), slice(LEFT, LEFT + aw))
    signal[act] = np.clip(np.take_along_axis(cam, ch[act][..., None], axis=2)[..., 0], 0, None) * (WHITE - black[act])
    noise = np.random.default_rng(1).normal(0, 1, (rows, cols)) * np.sqrt(NOISE[0] * signal + NOISE[1])
    cfa = np.clip(np.round(black + signal + noise), 0, SAT).astype(np.uint16)
    cm = np.diag(NEUTRAL) @ np.linalg.inv(FORWARD)  # XYZ -> camera (rawdng only uses it without a ForwardMatrix)
    tags = [(274, 3, 1, 6, True),  # Orientation: shown turned 90 degrees clockwise
            (33421, 3, 2, (2, 2), True), (33422, 1, 4, (0, 1, 1, 2), True),  # CFA: RGGB
            (50706, 1, 4, (1, 4, 0, 0), True), (50707, 1, 4, (1, 3, 0, 0), True),
            (50708, "s", 0, "AI Remove CI", True), (50710, 1, 3, (0, 1, 2), True), (50711, 3, 1, 1, True),
            (50713, 3, 2, (2, 2), True), (50714, 5, 4, rat(BLACK), True), (50717, 4, 1, WHITE, True),
            (50719, 4, 2, (CROP, CROP), True), (50720, 4, 2, (W, H), True),
            (50721, 10, 9, rat(cm), True), (50728, 5, 3, rat(NEUTRAL, 1000000), True), (50778, 3, 1, 21, True),
            (50829, 4, 4, (TOP, LEFT, TOP + ah, LEFT + aw), True), (50964, 10, 9, rat(FORWARD), True)]
    tifffile.imwrite(path, cfa, photometric=32803, rowsperstrip=6, compression=None, extratags=tags, metadata=None,
                     software="AI Remove ci_removal.py")
    return cfa


def upright_half(im):
    """Frame-sized image -> LightCraft's export frame: turned 90 degrees clockwise (Orientation 6), half size."""
    return im.transpose(Image.Transpose.ROTATE_270).resize((H // 2, W // 2), Image.LANCZOS)


def develop(rgb):
    """base.png: the frame as LightCraft would develop and export it (exposure, a soft shoulder, sRGB)."""
    f = rgb[CROP:CROP + H, CROP:CROP + W] * 2.2
    f = f / (f + 0.35) * 1.35
    s = np.where(f <= 0.0031308, 12.92 * f, 1.055 * np.power(np.clip(f, 0.0031308, None), 1 / 2.4) - 0.055)
    return upright_half(Image.fromarray(np.clip(s * 255 + 0.5, 0, 255).astype(np.uint8)))


class StandIn:
    """LightCraft's control channel, answered here (airemove.LC with _request replaced): every command is recorded;
    library.import gives a file an id, photo.inspect describes it (with a "Remove" mask, which the import deletes)."""

    def __init__(self, lc_class):
        self.lc = lc_class(port=1)
        self.lc._request = self.request
        self.calls, self.ids = [], {}

    def request(self, method, params):
        cmd, p = params["command"], params.get("params") or {}
        self.calls.append((cmd, p))
        if cmd == "library.import":
            for path in p["paths"]:
                self.ids.setdefault(str(Path(path).resolve()), 2001 + len(self.ids))
            return {"ok": True, "result": {"imported": [{"id": self.ids[str(Path(q).resolve())]} for q in p["paths"]]}}
        if cmd == "photo.inspect":
            path = next((k for k, v in self.ids.items() if v == p["id"]), None)
            return {"ok": True, "result": {"id": p["id"], "kind": "raw", "source": {"path": path},
                                           "develop": {"masks": [{"id": 77, "name": "Remove"}]}}}
        return {"ok": True, "result": {}}

    def commands(self):
        out = [c for c, __ in self.calls]
        self.calls = []
        return out


def session(ar, lc, photo, export, base_png, work):
    """A Session on the photo as Session.prepare() leaves it (extract() is LightCraft's part: done above)."""
    s = ar.Session(lc, argparse.Namespace(id=PID, raw=None, variants=None, auto=None, shadow=False))
    s.pid, s.targets, s.prompt = PID, [], ""
    s.info = {"id": PID, "kind": "raw", "file_name": photo.name, "source": {"path": str(photo)},
              "stack": {"photos": [PID]}, "albums": [], "develop": {"masks": []}}
    s.src_path, s.work, s.init_mask = photo, work, None
    work.mkdir(parents=True, exist_ok=True)
    s.base = Image.open(base_png).convert("RGB")
    s.base_arr = np.asarray(s.base)
    lum = np.asarray(Image.open(base_png).convert("L")).astype(np.float64) / 255.0  # as extract() does
    s.lum_e = np.where(lum <= 0.04045, lum / 12.92, ((lum + 0.055) / 1.055) ** 2.4)
    s.raw = ar.RawDNG(str(export))
    s.t, s.corr = ar.match_orientation(s.raw.preview_lum(), s.lum_e)
    s.gain = s.raw.global_gain()
    __, __, h, w = s.raw.frame
    s.base_scale = s.base.width / ar.apply_t(np.zeros((h, w), bool), s.t).shape[1]
    s.restore()
    return s


def tags(path):
    with tifffile.TiffFile(path) as tf:
        return {t.code: (t.value.tobytes() if isinstance(t.value, np.ndarray) else t.value)
                for t in tf.pages[0].tags.values()}


def clipped_sky(raw, cfa0):
    """An area across the blown sky's corner: the sky renders neutral white; that render written back as the fill
    gives the sky the sensor's own clipped values again, and the ground its values within the noise."""
    y0, x0 = raw.frame[:2]
    box = (y0 + SKY[0] - 64, y0 + SKY[0] + 64, x0 + SKY[1] - 64, x0 + SKY[1] + 64)
    srgb, gain = raw.render(box)
    sky = np.zeros((128, 128), bool)
    sky[64 + 3:, 64 + 3:] = True  # away from the edge, where demosaicing mixes sky and ground
    ground = np.zeros((128, 128), bool)
    ground[:64 - 3, :64 - 3] = True
    c = np.median(srgb[sky], axis=0) * 255
    expect(np.ptp(srgb[sky], axis=-1).max() * 255 < 0.5 and c[0] > 240,
           f"the blown sky renders neutral white: {c.round(1)} (gain {gain:.2f})")
    back = raw.fill_region(box, srgb, gain, np.ones((128, 128)))
    region = cfa0[box[0]:box[1], box[2]:box[3]]
    d = np.abs(back.astype(np.float64) - region)[ground]
    expect(np.array_equal(back[sky], region[sky]) and (region[sky] == SAT).all(),
           f"written back, the sky has the sensor's clipped values again ({SAT})")
    sigma = np.sqrt(NOISE[0] * np.median(region[ground] - BLACK.mean()) + NOISE[1])
    expect(d.mean() < 3 * sigma, f"and the ground its values within the noise: {d.mean():.1f} DN (sigma {sigma:.1f})")


def run(d, out):
    sys.path.insert(0, str(d / "airemove"))
    import airemove as ar  # the installed app (its system.ROOT is d: models from d/models, log in d/work)
    import project
    from rawdng import XYZD50_TO_SRGB
    expect(ar.engines.available().get("lama"), f"LaMa installed in {ar.engines.mf.part_dir('lama')}")

    photos, work = out / "photos", out / "work"
    photos.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    photo, export, base_png = photos / "CI-0001.dng", work / "source.dng", work / "base.png"
    rgb = scene()
    cfa0 = write_raw(photo, rgb, XYZD50_TO_SRGB)
    shutil.copyfile(photo, export)  # LightCraft's app.export (dngCompression=uncompressed) of the raw
    develop(rgb).save(base_png)
    sel = np.asarray(upright_half(Image.fromarray(disc(3).astype(np.uint8) * 255))) > 127  # the user's selection
    print(f"  info raw {cfa0.shape[1]}x{cfa0.shape[0]}, base.png {Image.open(base_png).size}, "
          f"selection {int(sel.sum())} px", flush=True)

    lc = StandIn(ar.LC)
    s = session(ar, lc.lc, photo, export, base_png, work / "s1")
    expect(s.t == (3, False) and s.corr > 0.9,
           f"orientation of the export found: {s.t} (90 degrees clockwise), correlation {s.corr:.2f}")
    expect(not s.removals, "no project yet")
    expect(s.raw.frame == (TOP + CROP, LEFT + CROP, H, W), f"visible frame {s.raw.frame}")
    a, b = s.raw.cached_noise()
    expect(0.3 < a < 1.2 and 4 < b < 30, f"sensor noise measured: variance {a:.2f} * signal + {b:.1f} "
                                          f"(made with {NOISE[0]} * signal + {NOISE[1]})")
    clipped_sky(s.raw, cfa0)

    t0 = time.time()
    r = s.new_removal(sel)
    y0, x0 = s.raw.frame[:2]
    by0, by1, bx0, bx1 = r.box
    obj = np.zeros(cfa0.shape, bool)
    obj[y0:y0 + H, x0:x0 + W] = disc()
    hole = np.zeros(cfa0.shape, bool)
    hole[by0:by1, bx0:bx1] = r.reg_mask
    expect(not (obj & ~hole).any(), f"the removal's hole covers the disc on the sensor (area {r.box})")
    s.run_lama(r)
    expect(r.chosen_label() == LABEL, f"variant {r.chosen_label()} made and chosen in {time.time() - t0:.1f}s")
    s.save_project()

    dng, nid, updated = s.write_all()
    expect(dng == photos / "CI-0001-AIRemove.dng" and dng.exists() and not updated
           and nid == lc.ids.get(str(dng.resolve())), f"written {dng.name}, imported as photo {nid}")
    cmds = lc.commands()
    expect("stack.group" in cmds and "develop.paste" in cmds and "mask.delete" in cmds,
           "stacked with the original, its development pasted, the Remove mask deleted")
    s.close()

    # the DNG
    t_src, t_out = tags(export), tags(dng)
    expect(t_out == t_src and dng.stat().st_size == export.stat().st_size, f"same tags as the export ({len(t_out)})")
    out_raw = ar.RawDNG(str(dng))
    cfa1 = out_raw.cfa
    expect(cfa1.shape == cfa0.shape and cfa1.dtype == np.uint16, "the DNG reads back (RawDNG)")
    changed = cfa1 != cfa0
    expect(changed[obj].mean() > 0.98, f"{changed[obj].mean():.1%} of the disc's sensor values changed")
    box = np.zeros(cfa0.shape, bool)
    box[by0:by1, bx0:bx1] = True
    expect(not (changed & ~box).any(), f"nothing changed outside the removal's area ({changed.sum()} values changed)")
    cy, cx = y0 + DISC[0], x0 + DISC[1]
    reach = np.sqrt(((np.argwhere(changed) - [cy, cx]) ** 2).sum(1)).max() - DISC[2]
    expect(reach <= 32, f"nothing changed farther than 32 px from the disc (the changes reach {reach:.0f} px)")

    # the disc is gone: its colour is the ground's around it (demosaiced camera values), with sensor-like noise
    inner = disc(-6)[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]
    ring = (disc(80) & ~disc(40))[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]
    cam_src, __, ___ = out_raw.demosaic(by0, by1, bx0, bx1, cfa=cfa0)
    cam_out, __, ___ = out_raw.demosaic(by0, by1, bx0, bx1)
    before = np.linalg.norm(cam_src[inner].mean(0) - cam_src[ring].mean(0))
    after = np.linalg.norm(cam_out[inner].mean(0) - cam_out[ring].mean(0))
    expect(after < 0.15 * before, f"the disc is gone: colour distance to the ground {before:.4f} -> {after:.4f}")
    i0, j0 = (by0 - TOP) % 2, (bx0 - LEFT + 1) % 2  # the green photosites on red rows (RGGB: G at (0, 1))
    green = cfa1[by0:by1, bx0:bx1][i0::2, j0::2].astype(np.float64)
    hp = green - (np.roll(green, 1, 0) + np.roll(green, -1, 0) + np.roll(green, 1, 1) + np.roll(green, -1, 1)) / 4
    n_in, n_ring = hp[inner[i0::2, j0::2]].std(), hp[ring[i0::2, j0::2]].std()
    expect(0.5 < n_in / n_ring < 2, f"sensor noise in the fill {n_in:.1f} DN, around it {n_ring:.1f} DN")
    out_raw.close()

    # the project
    meta, items = project.load(photo, print)
    e = meta["removals"][0] if meta.get("removals") else {}
    expect(len(items) == 1 and [v[0] for v in items[0][3]] == [LABEL] and e.get("chosen") == 0,
           f"project {project.path_for(photo).name}: 1 removal, variant {LABEL} chosen")
    expect(Path(meta["dng"]["path"]) == dng and meta["dng"]["id"] == nid, "the project knows its DNG")

    # reopened in a new session: the same sensor data; saved again: the same file, reloaded in LightCraft
    s2 = session(ar, lc.lc, photo, export, base_png, work / "s2")
    expect(len(s2.removals) == 1 and s2.removals[0].box == r.box and s2.removals[0].chosen_label() == LABEL,
           "project reopened: the removal, its area and its variant")
    expect(np.array_equal(s2.working_cfa(), cfa1), "reopened, it rebuilds exactly the DNG's sensor data")
    before = dng.read_bytes()
    dng2, nid2, updated2 = s2.write_all()
    cmds = lc.commands()
    expect(dng2 == dng and nid2 == nid and updated2 and "photo.reload" in cmds and "library.import" not in cmds,
           f"saved again: {dng2.name} updated and reloaded (photo {nid2})")
    expect(dng.read_bytes() == before, "the same file, byte for byte")

    # a part that waits for its model ("Split into parts"): its area planned, rendered only at its first variant;
    # it waits in the project too, and is made after reopening
    spot = np.zeros_like(sel)
    sh, sw = sel.shape
    spot[int(0.75 * sh):int(0.75 * sh) + 24, int(0.2 * sw):int(0.2 * sw) + 24] = True
    p = s2.plan_removal(spot)
    expect(not s2.area_ready(p) and not p.candidates and p.chosen is None,
           f"a part planned as #{p.id}: its area {p.box} not rendered yet, no variant")
    s2.save_project()
    s2.close()
    s3 = session(ar, lc.lc, photo, export, base_png, work / "s3")
    p3 = next((x for x in s3.removals if x.id == p.id), None)
    expect(p3 is not None and not p3.candidates and tuple(p3.box) == tuple(p.box),
           "reopened: the part still waits, with its area")
    s3.ensure_area(p3)
    s3.run_lama(p3)
    expect(p3.chosen_label() == LABEL, f"its first variant made after reopening: {p3.chosen_label()}")
    s3.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", help="install folder")
    ap.add_argument("--keep", help="leave the files in this folder")
    a = ap.parse_args()
    d = Path(a.dir).expanduser().resolve()
    out = Path(a.keep).resolve() if a.keep else Path(tempfile.mkdtemp(prefix="airemove-ci-"))
    print(f"remove {d} (files in {out})", flush=True)
    try:
        run(d, out)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    finally:
        if not a.keep:
            shutil.rmtree(out, ignore_errors=True)
    print("  ok   removal end to end", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
