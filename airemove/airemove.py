"""AI Remove for LightCraft — remove objects with LaMa / SDXL / FLUX and write the result into the RAW (DNG).

How to use:
  1. In LightCraft select a raw photo and press Ctrl+Shift+X (Cmd+Shift+X on a Mac) = Photo > Edit In > "Open Original
     in Other Editor (RAW, no copy)": the installer makes AI Remove LightCraft's external editor. AI Remove can also
     be started on its own (Start menu, Applications, app menu): it always works on LightCraft's active photo.
  2. The AI Remove window (ui.py) shows the whole photo: select what to remove (SAM 3 clicks on the GPU, refine
     with Alt/Shift+click, brush/eraser). Masks named "Rimuovi..." made in LightCraft start the selection.
  3. "Rimuovi selezione" makes a removal (like a Lightroom Generative Remove spot) with its own area and variants
     (LaMa + SDXL or FLUX; optional prompt IN ENGLISH). Each removal can get more variants, a different choice or
     be deleted without touching the others; fills are blended seamlessly (blend.py).
     The object's shadow and reflection: "Includi l'ombra" adds what OSOR removes with the object to the selection
     (Session.find_shadow), or OSOR / ObjectClear variants remove it by themselves (their hole grows with it).
     A long, thin object across a large area (a pole as tall as the photo, a cable) is filled in squares along it,
     near the engine's own size (tiles.py, Session.tile_plan); "Dettaglio pieno" redraws such a removal's chosen
     variant that way at the photo's resolution (Session.refine).
  4. Everything is kept in ONE project file next to the raw (<raw name>.airemove, see project.py), saved after every
     change; reopening AI Remove on the photo (or on its -AIRemove.dng) brings all removals back.
     "Salva in LightCraft" writes the chosen fills into <name>-AIRemove.dng — created and stacked the first time,
     then always the same file, rewritten and reloaded in LightCraft. The raw is never modified.

It talks to the running LightCraft through LightCraft's control channel (JSON lines on 127.0.0.1, see system.py):
LightCraft must be started with it on — the installer sets LIGHTCRAFT_CONTROL_PORT for it on every OS.

usage: airemove.py [RAW] [--id PHOTO_ID] [--variants N]
       airemove.py --auto lama|sdxl|flux|osor|objectclear|qwen[N] [--shadow] [--id PHOTO_ID]
                                                             no window: one removal from the "Rimuovi" masks with
                                                             that model, variant N used, written into the DNG;
                                                             --shadow: the object's shadow too (as the button)
       airemove.py --check                                   JSON report: GPU, models, LightCraft connection
"""
import argparse, base64, json, os, re, socket, sys, threading, time, traceback, zlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from rawdng import RawDNG  # noqa: E402
import engines  # noqa: E402
import blend  # noqa: E402
import tiles  # noqa: E402
import project  # noqa: E402
import system  # noqa: E402
from i18n import _  # noqa: E402

SHORTCUT = "Cmd+Shift+X" if system.system() == "macos" else "Ctrl+Shift+X"
MASK_PREFIXES = ("rimuovi", "remove")
ALL_GROUPS = ["profile", "treatment", "whiteBalance", "light", "toneCurve", "color", "colorMixer", "colorGrading",
              "effects", "vignette", "grain", "detail", "optics", "geometry", "crop", "masks", "spots", "redEye",
              "lensBlur", "calibration"]
# SDXL starts from pure noise (strength 1.0) on the photo with the hole masked out: nothing of the removed object can
# leak in, so it needs no LaMa pre-fill (below 1.0 the object shows through as a ghost)
SDXL_STRENGTH = 1.0
# SDXL sees the area upright, as the photo is seen. Sideways (sensor orientation, which a portrait photo has) it took
# the sky for ground — a mound or a rock where a hat stood against the sky — and filled a person-shaped hole with
# posts. Upright it fills a hole in the shape of a person with a person if something of theirs is left outside the
# selection (a bag at their side: 3 variants in 4); with the bag selected too, none.
SDXL_UPRIGHT = True
SHADOW_MARGIN = 1.35  # "Includi l'ombra" looks for the shadow in an area this many times the object's extent
# Long removals (tiles.py). When one pass would enlarge an engine's fill more than TILE_FROM times and the hole is
# long and thin (a pole, a cord, a railing — at least TILE_LONG times longer than wide, measured in the area: a pole
# 21, cords 22, a person 5-7, a person with their shadow 10) so that squares along it see the photo across it (its
# width at most TILE_WIDE of a square's side), each variant is filled in squares as small as TILE_BUDGET seconds per
# variant allow on this PC. "Full detail" redraws such a removal's chosen variant in squares as near the engine's own
# size as REFINE_BUDGET allows, at REFINE_STRENGTH: sharp, and what the variant shows stays where it is.
# Not for a person or a car: squares through such a hole each drew a piece of something (a wall, a giant bush), and
# redrawn in squares an invented bush became a felt blob or a dark silhouette, at every strength and size tried.
TILE_FROM = 3.2
TILE_LONG = 12.0
TILE_WIDE = 0.5
TILE_BUDGET = 60.0
REFINE_BUDGET = 150.0
REFINE_STRENGTH = 0.75  # on the pole: 0.5 kept the variant's blur in places (a grid of strokes on a plain wall)
TILE_SIZES = {"flux": engines.FLUX_SIZES, "sdxl": (engines.SDXL.S,), "lama": (512,), "osor": engines.FLUX_SIZES,
              "objectclear": (engines.ObjectClear.S,), "qwen": (engines.QWEN_SIZE,)}
# SDXL fills a long, thin hole with a long, thin thing (a plank where a cord was, a rod where a pole was), in one pass
# and more so in squares, measured: its variants stay in one pass. It still redraws for "Full detail" without FLUX.
TILED_VARIANTS = ("flux", "lama")
# A cord, a cable, a wire, a pole selected closely: a long hole at most THIN px wide. LaMa, in squares at its own
# size, continues what is behind it best and in seconds (railing cords in front of columns, a doorway, a sign: FLUX
# redrew a column's base, SDXL drew planks): the window adds a LaMa variant to the generative ones.
THIN = 128
TILE_SCALES = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)  # square side / engine size tried, smallest first
REFINED = " HD"  # label suffix of a variant redrawn by "Full detail"
NEUTRAL_GEOMETRY = {"upright": "off", "vertical": 0, "horizontal": 0, "rotate": 0, "aspect": 0, "scale": 100,
                    "offset_x": 0, "offset_y": 0}


LOG_FILE = Path(os.environ.get("AIREMOVE_LOG") or ROOT / "work" / "last-run.log")  # tests use their own


def log(*a):
    line = " ".join([time.strftime("%H:%M:%S")] + [str(x) for x in a])
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Fail(Exception):
    pass


class Stopped(Exception):
    """The window's Stop: the variant under way was dropped, between two of its steps (Session.stop)."""


class LC:
    """The running LightCraft, through its control channel: one JSON request per line on 127.0.0.1:<port>, one reply
    per line (LightCraft docs/control-protocol.md). Commands go through engine.execute; replies are
    {"ok": true, "result": ...} or {"ok": false, "error": ...}. One connection, one request at a time (the window's
    threads share it)."""

    def __init__(self, port=None):
        self.port = port or system.control_port()
        self._lock = threading.Lock()
        self._sock, self._buf, self._id = None, b"", 0

    def _not_running(self, e):
        return Fail(_("LightCraft does not answer on port {port} ({error}).\n\nOpen LightCraft. If it is open "
                      "already, close it and open it again: AI Remove talks to it through its control channel, which "
                      "the installation turns on (LIGHTCRAFT_CONTROL_PORT) but only for LightCraft started after it. "
                      "On Linux with Wayland LightCraft's window must be visible.",
                      port=self.port, error=type(e).__name__))

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock, self._buf = None, b""

    def _request(self, method, params):
        """One request -> its reply. A connection found closed is reopened once (the request never reached the
        app then); a timeout is not retried (the app may still be running it)."""
        for attempt in (0, 1):
            sent = False
            try:
                if self._sock is None:
                    self._sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
                    self._sock.settimeout(180)  # LightCraft gives a request up to 60 s; exports of big raws included
                self._id += 1
                self._sock.sendall((json.dumps({"id": self._id, "method": method, "params": params}) + "\n").encode())
                sent = True
                while b"\n" not in self._buf:
                    chunk = self._sock.recv(1 << 20)
                    if not chunk:
                        raise ConnectionResetError("connection closed by LightCraft")
                    self._buf += chunk
                line, self._buf = self._buf.split(b"\n", 1)
                return json.loads(line.decode("utf-8").lstrip("﻿"))
            except socket.timeout as e:
                self.close()
                raise Fail(_("LightCraft did not answer {command} in time",
                             command=params.get("command", method))) from e
            except (OSError, ValueError) as e:
                self.close()
                if attempt or (sent and not isinstance(e, (ConnectionResetError, BrokenPipeError))):
                    raise self._not_running(e) from e

    def run(self, cmds):
        """Run commands in order; every reply is returned (a failed one does not stop the rest)."""
        with self._lock:
            return [self._request("engine.execute", {"command": c["command"], "params": c.get("params") or {}})
                    for c in cmds]

    def one(self, cid, params=None):
        r = self.run([{"command": cid, "params": params or {}}])[0]
        if not r.get("ok"):
            raise Fail(f"{cid}: {r.get('error')}")
        return r.get("result")

    def state(self):
        return self.one("library.state")


# ------------------------------------------------------------------------------------------------ geometry helpers
def transforms():
    for flip in (False, True):
        for k in range(4):
            yield (k, flip)


def apply_t(a, t):
    k, flip = t
    return np.rot90(np.fliplr(a) if flip else a, k)


def invert_t(b, t):
    k, flip = t
    a = np.rot90(b, -k)
    return np.fliplr(a) if flip else a


def small(a, w=192):
    h = max(8, int(round(w * a.shape[0] / a.shape[1])))
    im = Image.fromarray(a.astype(np.float32), mode="F").resize((w, h), Image.BILINEAR)
    x = np.log1p(np.asarray(im) * 50.0)
    return (x - x.mean()) / (x.std() + 1e-9)


def match_orientation(sensor_lum, export_lum):
    """Which rotation/flip turns the sensor frame into LightCraft's (uncropped) export frame."""
    ex_aspect = export_lum.shape[1] / export_lum.shape[0]
    best = None
    for t in transforms():
        c = apply_t(sensor_lum, t)
        if abs(c.shape[1] / c.shape[0] - ex_aspect) > 0.03 * ex_aspect:
            continue
        score = float((small(c) * small(export_lum)).mean())
        if best is None or score > best[0]:
            best = (score, t)
    if best is None or best[0] < 0.5:
        raise Fail(_("cannot align the export with the sensor (correlation {score})",
                       score=f"{best[0]:.2f}" if best else "n/a"))
    return best[1], best[0]


def grow(mask_bool, px):
    """Round dilation by px pixels."""
    return ndi.distance_transform_edt(~mask_bool) <= px


def srgb_to_lin(x8):
    x = x8.astype(np.float64) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def mask_from_renders(base_png, dim_png):
    """Binary mask from a normal render and one with the Rimuovi masks at exposure -4.
    Only pixels the mask darkens strongly count (weight ~> 0.5); the faint soft fringe of LightCraft masks
    and colour-only changes (no saturation trick: it lit up every orange berry) stay out."""
    a8 = np.asarray(Image.open(base_png).convert("RGB")).astype(np.int16)
    b8 = np.asarray(Image.open(dim_png).convert("RGB")).astype(np.int16)
    wl = np.array([0.2126, 0.7152, 0.0722])
    la, lb = srgb_to_lin(a8) @ wl, srgb_to_lin(b8) @ wl
    drop8 = (a8 - b8).max(axis=2)
    m = (lb < 0.55 * la) & (drop8 >= 4)
    m = ndi.binary_closing(m, structure=np.ones((3, 3)), iterations=2)
    m = ndi.binary_fill_holes(m)
    lab, n = ndi.label(m)
    if n:
        sizes = ndi.sum(m, lab, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= 12
        m = keep[lab]
    return m


def _seg_logits(d, size):
    """A stored SAM 3 segmentation (raw-deflate int8 logits, side x side) resized to size=(w, h)."""
    s = int(d["side"])
    a = np.frombuffer(zlib.decompress(base64.b64decode(d["data"]), -15), np.int8).reshape(s, s).astype(np.float32)
    return np.array(Image.fromarray(a, mode="F").resize(size, Image.BILINEAR))


def sam_mask(targets, w, h):
    """The Rimuovi masks straight from LightCraft's SAM 3 selections (Object / Describe components), in the
    uncropped image frame, at w x h. None if a component is something else (brush, gradient...)."""
    total = np.zeros((h, w), bool)
    for m in targets:
        acc = None
        for c in m.get("components", []):
            sh = c.get("shape", {})
            if sh.get("kind") not in ("object", "prompt") or not isinstance(sh.get("seg"), dict):
                return None
            lg = _seg_logits(sh["seg"], (w, h))
            for d in sh.get("detail") or []:  # zoomed-in refinement passes
                x0, y0, x1, y1 = d["rect"]
                px0, py0 = int(round(x0 * w)), int(round(y0 * h))
                px1, py1 = int(round(x1 * w)), int(round(y1 * h))
                if px1 - px0 > 1 and py1 - py0 > 1:
                    lg[py0:py1, px0:px1] = _seg_logits(d, (px1 - px0, py1 - py0))
            sel = (lg > 0) ^ bool(c.get("invert"))
            op = c.get("op", "add")
            if acc is None:
                acc = sel if op != "subtract" else np.zeros_like(sel)
            elif op == "add":
                acc |= sel
            elif op == "subtract":
                acc &= ~sel
            elif op == "intersect":
                acc &= sel
        if acc is not None:
            total |= acc ^ bool(m.get("invert"))
    return total


def harmonize(cand, src, mask, sigma=None):
    """Remove the low-frequency colour/brightness offset between a fill and the photo around the mask edge
    (SDXL's VAE shifts tones a little), so the patch does not show as a lighter/darker block."""
    c = np.asarray(cand).astype(np.float64)
    s = np.asarray(src).astype(np.float64)
    sigma = sigma or max(12.0, 0.03 * mask.shape[0])
    ring = (grow(mask, int(sigma)) & ~mask).astype(np.float64)
    w = ndi.gaussian_filter(ring, sigma)
    off = np.stack([ndi.gaussian_filter((s[..., i] - c[..., i]) * ring, sigma) for i in range(3)], -1)
    off = off / np.maximum(w, 1e-4)[..., None]
    out = np.where(mask[..., None], c + off, c)
    return Image.fromarray(np.clip(out, 0, 255).round().astype(np.uint8))


# ------------------------------------------------------------------------------------------------ main steps
def find_photo(lc, args):
    pid = args.id
    raw_arg = getattr(args, "raw", None)
    if raw_arg and Path(raw_arg).suffix.lower() in (".tif", ".tiff", ".psd"):
        raise Fail(_("LightCraft passed a TIFF/PSD copy: for AI Remove use\nPhoto > Edit In > \"Open Original in "
                     "Other Editor (RAW, no copy)\".\n(The copy {file} can be deleted from the library.)",
                     file=Path(raw_arg).name))
    if pid is None:
        sel = lc.state().get("selection") or {}
        cands = [sel.get("active")] + [i for i in (sel.get("ids") or []) if i != sel.get("active")]
        cands = [i for i in cands if i]
        pid = cands[0] if cands else None
        if raw_arg and len(cands) > 1:  # launched by LightCraft on a file: take the selected photo with that path
            want = os.path.normcase(os.path.abspath(raw_arg))
            for i in cands[:50]:
                p = (lc.one("photo.inspect", {"id": i}).get("source") or {}).get("path", "")
                if p and os.path.normcase(os.path.abspath(p)) == want:
                    pid = i
                    break
    if not pid:
        raise Fail(_("No active photo in LightCraft: select a RAW photo and press {shortcut} again.",
                     shortcut=SHORTCUT))
    info = lc.one("photo.inspect", {"id": pid})
    src = Path((info.get("source") or {}).get("path", ""))
    m = re.match(r"(.+)-AIRemove(?:-\d+)?$", src.stem)
    if m and src.suffix.lower() == ".dng":  # launched on a result: work on its original (the project lives there)
        found = None
        for i in ((info.get("stack") or {}).get("photos") or []):
            if i == pid:
                continue
            oi = lc.one("photo.inspect", {"id": i})
            op = Path((oi.get("source") or {}).get("path", ""))
            if op.stem == m.group(1) and oi.get("kind") == "raw":
                found = (i, oi)
                break
        if found is None:
            raise Fail(_("{file} is an AI Remove result but its stack has no original ({stem}): open AI Remove "
                         "on the original photo.", file=src.name, stem=m.group(1)))
        log(f"{src.name} is an AI Remove result: opening its original {found[1].get('file_name')}")
        pid, info = found
    if info.get("kind") != "raw":
        raise Fail(_("{file} is not a RAW: AI Remove works on raw files only.", file=info.get("file_name")))
    # optional: masks named "Remove..." (or "Rimuovi...") made in LightCraft become the starting selection
    targets = [m for m in info["develop"]["masks"] if m.get("name", "").strip().lower().startswith(MASK_PREFIXES)]
    prompt = ""
    for m in targets:
        if ":" in m["name"]:
            prompt = m["name"].split(":", 1)[1].strip()
    return pid, info, targets, prompt


def wait_sam(lc):
    for _ in range(90):
        st = lc.one("segment.model.status")
        if not st.get("busy") and not st.get("analyzing"):
            return
        time.sleep(2)


def extract(lc, pid, info, targets, work):
    """base.png = the whole uncropped photo as developed (selection happens on it; it is also the frame LightCraft's
    masks live in), the raw DNG export, and — if there are Rimuovi masks — their union in that frame (else None)."""
    dev = info["develop"]
    saved = {"crop": dev["crop"], "optics": dev["optics"], "geometry": dev["geometry"]}
    sel = {"command": "library.select", "params": {"ids": [pid], "active": pid}}
    base_png, mask_png, dng = str(work / "base.png"), str(work / "masked.png"), str(work / "source.dng")
    use_sam = not targets or sam_mask(targets, 4, 4) is not None  # SAM 3 selections are read, not rendered
    try:
        r = lc.run([sel,
                    {"command": "crop.set", "params": {"rect": [0, 0, 1, 1], "angle": 0}},
                    {"command": "develop.merge", "params": {"settings": {"optics": {"lens_profile": False, "distortion": 0},
                                                                        "geometry": NEUTRAL_GEOMETRY}, "label": "AI Remove (temporaneo)"}},
                    {"command": "app.export", "params": {"path": base_png, "longEdge": 2400}}]
                   + ([] if use_sam else
                      [{"command": "mask.adjust", "params": {"id": m["id"], "values": {"exposure": -4}}} for m in targets]
                      + [{"command": "app.export", "params": {"path": mask_png, "longEdge": 2400}}]))
        bad = [x for x in r if not x.get("ok")]
        if bad:
            raise Fail("LightCraft: " + str(bad[0].get("error")))
    finally:
        restore = [sel] + [{"command": "mask.adjust", "params": {"id": m["id"], "values": {k: v for k, v in m["adjust"].items()}}}
                           for m in targets]
        restore += [{"command": "develop.merge", "params": {"settings": saved, "label": "AI Remove (ripristino)"}},
                    {"command": "mask.select", "params": {"id": None}}]
        lc.run(restore)
    r = lc.run([sel, {"command": "app.export", "params": {"path": dng, "dngCompression": "uncompressed"}}])
    if not r[-1].get("ok"):
        raise Fail("export DNG: " + str(r[-1].get("error")))
    mask_e = None
    if targets and use_sam:
        bw, bh = Image.open(base_png).size
        mask_e = sam_mask(targets, bw, bh)
        log("starting mask: LightCraft's SAM 3 selection")
    elif targets:
        mask_e = mask_from_renders(base_png, mask_png)
        log("starting mask: from the renders (brush/gradient)")
    if mask_e is not None and mask_e.sum() < 20:
        mask_e = None
    lum_e = np.asarray(Image.open(base_png).convert("L")).astype(np.float64) / 255.0
    lum_e = np.where(lum_e <= 0.04045, lum_e / 12.92, ((lum_e + 0.055) / 1.055) ** 2.4)
    return mask_e, lum_e, dng


def plan_region(raw, mask_e, lum_e, t=None, margin=1.35, square=True, box=None):
    """The sensor area around mask_e (side = margin x the object's extent) and the object's hole in it: a square, at
    most the photo's short side. square=False: an object longer than that (a pole as tall as a portrait photo, from
    its lamp to its base) gets an area as long as it needs along that axis — in a square its ends were left out, and
    never removed. Such an area is filled in squares (Session.tile_plan). box: the hole in that area instead."""
    score = 1.0
    if t is None:
        t, score = match_orientation(raw.preview_lum(), lum_e)
    y0, x0, h, w = raw.frame
    oriented_shape = apply_t(np.zeros((h, w), bool), t).shape
    m = Image.fromarray((mask_e * 255).astype(np.uint8)).resize((oriented_shape[1], oriented_shape[0]), Image.BILINEAR)
    sensor = invert_t(np.asarray(m) > 64, t)
    ys, xs = np.nonzero(sensor)
    long_edge = max(h, w)
    g = max(6, int(round(0.004 * long_edge)))  # cover the object's soft edge pixels, nothing more
    by0, by1, bx0, bx1 = ys.min() - g, ys.max() + g, xs.min() - g, xs.max() + g
    side = int(max(by1 - by0, bx1 - bx0) * margin)
    side = int(np.clip(max(side, 384), 0, min(h, w)))
    side -= side % 2
    H = W = side
    if not square:  # longer than the square can be: as long as it needs (and the photo allows) along that axis
        if by1 - by0 > side:
            H = int(np.clip((by1 - by0) * margin, side, h)) // 2 * 2
        if bx1 - bx0 > side:
            W = int(np.clip((bx1 - bx0) * margin, side, w)) // 2 * 2
    cy, cx = (by0 + by1) // 2, (bx0 + bx1) // 2
    ry0 = int(np.clip(cy - H // 2, 0, h - H)); rx0 = int(np.clip(cx - W // 2, 0, w - W))
    ry0 -= ry0 % 2; rx0 -= rx0 % 2
    if box is not None:
        ry0, rx0, H, W = box[0] - y0, box[2] - x0, box[1] - box[0], box[3] - box[2]
    reg_mask = grow(sensor[ry0:ry0 + H, rx0:rx0 + W], g)
    box = (y0 + ry0, y0 + ry0 + H, x0 + rx0, x0 + rx0 + W)
    log(f"area {W}x{H} px | mask {int(reg_mask.sum())} px")
    return t, box, reg_mask


# ------------------------------------------------------------------------------------------------ import into LightCraft
def import_stacked(lc, pid, info, out_path):
    res = lc.one("library.import", {"paths": [str(out_path)], "mode": "add"})
    # a file at a path that was deleted from the library before comes back from Recently Deleted as "restored"
    ids = (res.get("imported") or []) + (res.get("restored") or []) + (res.get("duplicates") or [])
    ids = [(i.get("id") or i.get("existing")) if isinstance(i, dict) else i for i in ids]
    if not ids:
        raise Fail(_("import failed: {result}", result=res))
    nid = ids[0]
    steps = [{"command": "photo.reload", "params": {"ids": [nid]}},
             {"command": "library.select", "params": {"ids": [pid], "active": pid}},
             {"command": "develop.copy", "params": {"groups": ALL_GROUPS}},
             {"command": "library.select", "params": {"ids": [nid], "active": nid}},
             {"command": "develop.paste", "params": {}}]
    lc.run(steps)
    new = lc.one("photo.inspect", {"id": nid})
    dels = [{"command": "mask.delete", "params": {"id": m["id"]}} for m in new["develop"]["masks"]
            if m.get("name", "").strip().lower().startswith(MASK_PREFIXES)]
    # same albums as the original, so the new version shows up where the user is looking (smart albums refuse
    # additions and fill themselves; --keep-going lets those fail quietly)
    meta = [{"command": "album.addPhotos", "params": {"id": a, "ids": [nid]}} for a in info.get("albums") or []]
    if info.get("rating"):
        meta.append({"command": "photo.rate", "params": {"rating": info["rating"], "ids": [nid]}})
    if info.get("flag") == "pick":
        meta.append({"command": "photo.pick", "params": {"ids": [nid]}})
    lc.run([{"command": "library.select", "params": {"ids": [nid], "active": nid}}] + dels + meta +
           [{"command": "stack.group", "params": {"ids": [pid, nid], "top": nid, "collapsed": False}},
            {"command": "library.select", "params": {"ids": [nid], "active": nid}}])
    return nid


def unique_path(p):
    p = Path(p)
    if not p.exists():
        return p
    for n in range(2, 100):
        q = p.with_name(f"{p.stem}-{n}{p.suffix}")
        if not q.exists():
            return q
    raise Fail(_("too many AIRemove files for this photo"))


# ------------------------------------------------------------------------------------------------ timings
TIMINGS = ROOT / "work" / "timings.json"
DEFAULT_TIMES = {"lama": 16, "sdxl_load": 25, "sdxl_variant": 8, "flux_load": 20, "flux_variant": 90,
                 "osor_load": 25, "osor_variant": 8, "objectclear_load": 20, "objectclear_variant": 5, "shadow": 12,
                 "qwen_load": 15, "qwen_variant": 50,
                 "area": 3, "save": 6,
                 # one square of a tiled fill (tiles.py), one redrawn by "Full detail", the blend of the area after
                 "flux_tile512": 13, "flux_tile768": 22, "sdxl_tile1024": 7.5, "lama_tile512": 2,
                 "flux_refine512": 12, "flux_refine768": 21, "sdxl_refine1024": 7, "tiled_blend": 5,
                 "qwen_tile1024": 60}


def expected(key):
    """Seconds an operation took recently on this PC (for the progress bar)."""
    try:
        return float(json.loads(TIMINGS.read_text(encoding="utf-8-sig")).get(key, DEFAULT_TIMES.get(key, 10)))
    except (OSError, ValueError):
        return float(DEFAULT_TIMES.get(key, 10))


def measured(key, seconds):
    try:
        d = json.loads(TIMINGS.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        d = {}
    old = d.get(key)
    d[key] = round(seconds if old is None else 0.5 * old + 0.5 * seconds, 1)
    try:
        TIMINGS.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass


SETTINGS = ROOT / "work" / "settings.json"


def setting(key, default=None):
    """Window choices remembered between runs (last model, number of variants)."""
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8-sig")).get(key, default)
    except (OSError, ValueError):
        return default


def remember(key, value):
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        d = {}
    if d.get(key) != value:
        d[key] = value
        try:
            SETTINGS.write_text(json.dumps(d, indent=1), encoding="utf-8")
        except OSError:
            pass


UPDATE_EVERY = 24 * 3600  # s: GitHub is asked about a new version at most this often


def update_available():
    """(version, release page) when GitHub has a newer AI Remove than this one, else None. Asked at most once a day
    (the answer is remembered in work/settings.json); off with "update_check": false there, or AIREMOVE_NO_UPDATE_CHECK
    in the environment."""
    if os.environ.get("AIREMOVE_NO_UPDATE_CHECK") or setting("update_check", True) is False:
        return None
    seen = setting("update_seen") or {}
    if time.time() - float(seen.get("t", 0)) > UPDATE_EVERY:
        got = system.latest_release()
        seen = {"t": time.time(), "version": got[0], "url": got[1]} if got else dict(seen, t=time.time())
        remember("update_seen", seen)
    v = seen.get("version")
    if v and system.version_tuple(v) > system.version_tuple(system.VERSION):
        return v, seen.get("url") or system.RELEASES
    return None


def rect_t(r, shape, t):
    """Rectangle (y0, y1, x0, x1) of an array with `shape` -> the same rectangle after apply_t(array, t)."""
    y0, y1, x0, x1 = r
    H, W = shape
    k, flip = t
    if flip:
        x0, x1 = W - x1, W - x0
    for _ in range(k % 4):  # np.rot90: out[i, j] = a[j, W-1-i]
        y0, y1, x0, x1 = W - x1, W - x0, y0, y1
        H, W = W, H
    return y0, y1, x0, x1


MODELS = {"sdxl": "SDXL", "flux": "FLUX", "lama": "LaMa", "osor": "OSOR", "objectclear": "ObjectClear",
          "qwen": "Qwen"}
LABEL_MODELS = {v: k for k, v in MODELS.items()}  # a variant label's first word -> its model


# ------------------------------------------------------------------------------------------------ removals
class Removal:
    """One removal, like a Lightroom Generative Remove spot: its own area of the photo, its own variants and the
    chosen one. Removals are applied in order; each sees the chosen fills of the earlier ones."""

    def __init__(self, rid, mask_e):
        self.id, self.mask_e = rid, mask_e
        self.candidates = []  # (label, PIL area image, already blended into the photo)
        self.chosen = None  # index into candidates
        self.user_picked = False
        self.counts = {}  # model -> variants made so far
        self.prefill = None
        self.deleted = False
        self.preview = {}  # label -> (patch uint8 HxWx3, alpha float HxW) in base.png's look and frame
        self.png = {}  # encoded images for the project file (label / "selection" / "area" -> PNG bytes)
        self.gain = None  # render gain of this area (set once, stored in the project: variants depend on it)
        # label -> bool hole of a variant that also removed the object's shadow/reflection (OSOR, ObjectClear):
        # the area's own hole grown by what the model changed. Other variants use reg_mask.
        self.holes = {}
        self.hole_cache = {}  # label -> (mask image, alpha, alpha in base.png's frame)
        self.flat = False  # (region, colours) of the sky its hole continues (blend.flat_region), None: none, False: not yet
        self.plans = {}  # (model, refine?, variant whose hole it is or None) -> (engine size, tiles.Plan) or None
        self.shape = None  # (width, length) of its hole (tiles.shape), once
        self.scale = {}  # label -> how enlarged that variant's fill is (Session.enlarged), for those made here

    def chosen_label(self):
        return None if self.chosen is None else self.candidates[self.chosen][0]


def label_text(label):
    """A variant's label as shown: model names stay, the old result's is translated (projects made before the
    translation say "Precedente")."""
    return _("Previous") if label in ("Previous", "Precedente") else label


class Session:
    """Everything for one photo: the export from LightCraft, the removals, the engines, writing the DNG."""

    def __init__(self, lc, args):
        self.lc, self.args = lc, args
        self.raw = self.info = self.sam = self.sdxl = self.flux = self.objectclear = self.qwen = None
        self.removals, self.next_id = [], 1
        self.seed = int(time.time()) % 100000
        self._engine_lock = threading.RLock()
        self.stop = threading.Event()  # set by the window's Stop: generations end at their next step (Stopped)
        self._proj_lock = threading.Lock()
        self._work_cfa, self._work_key = None, None
        self.dng_path, self.dng_id, self.restored = None, None, None

    # -------------------------------------------------------------- photo
    def find(self):
        """Which photo (and any "Rimuovi" masks made in LightCraft). Quick; fails early with a clear message."""
        self.pid, self.info, self.targets, self.prompt = find_photo(self.lc, self.args)
        self.src_path = Path(self.info["source"]["path"])
        log(f"{self.info['file_name']} (id {self.pid}) | maschere: {', '.join(m['name'] for m in self.targets)}"
            + (f" | prompt: {self.prompt}" if self.prompt else ""))

    def prepare(self):
        """From LightCraft: base.png (whole uncropped photo as developed: what the window shows and where the
        selection is made), the raw DNG, the Rimuovi masks if any (self.init_mask)."""
        lc = self.lc
        if self.info is None:
            self.find()
        self.work = ROOT / "work" / f"{self.src_path.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.work.mkdir(parents=True, exist_ok=True)
        if self.targets:
            wait_sam(lc)
        self.init_mask, self.lum_e, dng = extract(lc, self.pid, self.info, self.targets, self.work)
        self.base = Image.open(self.work / "base.png").convert("RGB")
        self.base_arr = np.asarray(self.base)
        self.raw = RawDNG(dng)
        self.t, score = match_orientation(self.raw.preview_lum(), self.lum_e)
        self.gain = self.raw.global_gain()  # one render space for every removal
        y0, x0, h, w = self.raw.frame
        oh, ow = apply_t(np.zeros((h, w), bool), self.t).shape
        self.base_scale = self.base.width / ow
        log(f"orientation {self.t} (corr {score:.2f}) | gain {self.gain:.2f}")
        self.restore()

    # -------------------------------------------------------------- project file (all patches, next to the raw)
    def restore(self):
        """Reopen the photo's project: every removal with its variants and choice, as it was left. Without a project,
        a result made before projects existed (<stem>-AIRemove*.dng) is adopted."""
        res = project.load(self.src_path, log)
        if res is None:
            self.adopt_legacy()
            return
        meta, items = res
        bw, bh = self.base.size
        for e, sel, area, variants in items:
            if sel.shape != (bh, bw):  # base.png came out at another size: same frame, rescale the selection
                sel = np.asarray(Image.fromarray(sel.astype(np.uint8) * 255).resize((bw, bh), Image.NEAREST)) > 127
            r = Removal(e["id"], sel)
            r.box, r.reg_mask = tuple(e["box"]), area
            r.counts, r.user_picked = dict(e.get("counts") or {}), bool(e.get("user_picked"))
            r.gain = e.get("gain") or self.gain
            for label, im, data, hole in variants:
                r.candidates.append((label, im))
                r.png[label] = data
                if hole is not None and hole.shape == area.shape:
                    r.holes[label] = hole
            r.chosen = e.get("chosen") if variants else None
            if r.chosen is not None and not 0 <= r.chosen < len(r.candidates):
                r.chosen = len(r.candidates) - 1
            self._init_area(r)  # rendered with the earlier removals applied, as when it was made
            self.removals.append(r)
        self.next_id = max([meta.get("next_id", 1)] + [r.id + 1 for r in self.removals])
        d = meta.get("dng") or {}
        if d.get("path") and Path(d["path"]).exists():
            self.dng_path, self.dng_id = Path(d["path"]), d.get("id")
        self.restored = meta
        log(f"project reopened: {len(self.removals)} removals, saved {meta.get('saved')}"
            + (f", DNG {self.dng_path.name}" if self.dng_path else ""))

    # -------------------------------------------------------------- results made before projects existed
    def adopt_legacy(self):
        """The newest <stem>-AIRemove*.dng next to the raw becomes this project's result: each changed area of its
        sensor data becomes a removal. Its variants are recovered from the work folder when they are still there
        (and the chosen one recognised), otherwise the area as saved in the DNG is the variant "Previous"."""
        cands = sorted(self.src_path.parent.glob(f"{self.src_path.stem}-AIRemove*.dng"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        cands = [p for p in cands if re.fullmatch(rf"{re.escape(self.src_path.stem)}-AIRemove(-\d+)?", p.stem)]
        if not cands:
            return
        path = cands[0]
        try:
            old = RawDNG(str(path))
        except Exception as e:
            log(f"{path.name}: unreadable ({e}), not adopted")
            return
        try:
            if old.cfa.shape != self.raw.cfa.shape:
                return
            y0, x0, h, w = self.raw.frame
            diff = np.zeros(self.raw.cfa.shape, bool)
            diff[y0:y0 + h, x0:x0 + w] = old.cfa[y0:y0 + h, x0:x0 + w] != self.raw.cfa[y0:y0 + h, x0:x0 + w]
            if diff.sum() < 50 or diff.sum() > 0.2 * h * w:  # nothing changed / not a result of this photo
                return
            # one removal per group of changes: parts closer than ~60 px (one old area) stay together
            f = 8
            H0, W0 = diff.shape
            small = np.zeros((-(-H0 // f), -(-W0 // f)), bool)
            pad = np.zeros((small.shape[0] * f, small.shape[1] * f), bool)
            pad[:H0, :W0] = diff
            small = pad.reshape(small.shape[0], f, small.shape[1], f).any(axis=(1, 3))
            lab_s, n = ndi.label(ndi.binary_dilation(small, iterations=8))
            lab = np.repeat(np.repeat(lab_s, f, axis=0), f, axis=1)[:H0, :W0]
            work_areas = self._work_areas()
            for k in range(1, n + 1):
                part = diff & (lab == k)
                if part.sum() < 50:
                    continue
                r = self._adopt_area(part, old, work_areas)
                self.removals.append(r)
                self._work_cfa, self._work_key = None, None
        finally:
            old.close()
        if not self.removals:
            return
        self.dng_path, self.dng_id = path, self._photo_id(path)
        self.save_project()
        log(f"adopted {path.name}: {len(self.removals)} removals ("
            + ", ".join(f"#{r.id} {len(r.candidates)} variant(s)"
                        for r in self.removals) + ")")

    def _work_areas(self):
        """Areas saved by earlier runs on this photo: (src path, mask path, [(label, variant path)])."""
        out = []
        for d in sorted((ROOT / "work").glob(f"{self.src_path.stem}-*"), key=lambda p: p.stat().st_mtime, reverse=True):
            for srcp in sorted(d.glob("r*_src.png")):
                rid = srcp.name.split("_")[0]
                maskp = d / f"{rid}_mask.png"
                vs = []
                for f in sorted(d.glob(f"{rid}_*.png"), key=lambda p: p.stat().st_mtime):
                    tag = f.stem.split("_", 1)[1]
                    if tag in ("src", "mask", "chosen"):
                        continue
                    m = re.fullmatch(r"(LaMa|SDXL|FLUX)(\d*)", tag)
                    if m:
                        vs.append((m.group(1) + (f" {m.group(2)}" if m.group(2) else ""), f))
                if maskp.exists() and vs:
                    out.append((srcp, maskp, vs))
        return out

    def _adopt_area(self, part, old, work_areas):
        """A removal for the changed sensor pixels `part` of the old result."""
        y0, x0, h, w = self.raw.frame
        ys, xs = np.nonzero(part)
        cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
        for srcp, maskp, vs in work_areas:  # the exact area of an earlier run, found by matching its image
            src = np.asarray(Image.open(srcp).convert("RGB")).astype(np.int16)
            side = src.shape[0]
            if side < ys.max() - ys.min() or side < xs.max() - xs.min():
                continue
            pad = 16
            by0 = int(np.clip(cy - side // 2 - pad, y0, y0 + h - side - 2 * pad)) // 2 * 2
            bx0 = int(np.clip(cx - side // 2 - pad, x0, x0 + w - side - 2 * pad)) // 2 * 2
            big, _ = self.raw.render((by0, by0 + side + 2 * pad, bx0, bx0 + side + 2 * pad), self.gain)
            big = (big * 255).round().astype(np.int16)
            area = np.asarray(Image.open(maskp).convert("L")) > 127
            keep = ~ndi.binary_dilation(area, iterations=6)
            best = None
            for dy in range(0, 2 * pad + 1, 2):
                for dx in range(0, 2 * pad + 1, 2):
                    pt = big[dy:dy + side:6, dx:dx + side:6]
                    k = keep[::6, ::6]
                    mad = float(np.abs(pt - src[::6, ::6])[k].mean())
                    if best is None or mad < best[0]:
                        best = (mad, dy, dx)
            if best is None or best[0] > 3.0:
                continue
            box = (by0 + best[1], by0 + best[1] + side, bx0 + best[2], bx0 + best[2] + side)
            # the old DNG must be one of this run's variants (same place is not enough: another run may have
            # worked on the same object); compared lightly blurred, past the sensor noise
            saved, _ = old.render(box, self.gain)
            saved = ndi.gaussian_filter((saved * 255).astype(np.float32), (1.5, 1.5, 0))
            src_im = Image.fromarray(src.astype(np.uint8))
            mask_im = Image.fromarray((area * 255).astype(np.uint8))
            ims = [Image.open(fp).convert("RGB") for _, fp in vs]
            errs = [float(np.abs(ndi.gaussian_filter(np.asarray(Image.composite(im, src_im, mask_im), np.float32),
                                                     (1.5, 1.5, 0)) - saved)[area].mean()) for im in ims]
            if min(errs) > 4.0:
                continue
            r = Removal(self.next_id, self._sensor_to_base(part))
            self.next_id += 1
            r.box, r.reg_mask, r.gain = box, area, self.gain  # those runs rendered with the global gain
            for (label, _), im in zip(vs, ims):
                r.candidates.append((label, im))
                kind = label.split()[0].lower()
                if len(label.split()) > 1:
                    r.counts[kind] = max(r.counts.get(kind, 0), int(label.split()[1]))
            r.chosen, r.user_picked = int(np.argmin(errs)), True
            self._init_area(r)
            log(f"  #{r.id}: area found in {srcp.parent.name} ({len(vs)} variants, chosen {r.chosen_label()}, "
                f"error {min(errs):.1f})")
            return r
        # no earlier area: the result itself is the only variant
        r = Removal(self.next_id, self._sensor_to_base(ndi.binary_dilation(part, iterations=2)))
        self.next_id += 1
        _, r.box, r.reg_mask = plan_region(self.raw, r.mask_e, self.lum_e, self.t)
        _, r.gain = self.raw.render(r.box)  # this area's own gain (no clipped highlights)
        saved, _ = old.render(r.box, r.gain)
        r.candidates.append(("Previous", Image.fromarray((saved * 255).round().astype(np.uint8))))
        r.chosen, r.user_picked = 0, True
        self._init_area(r)
        log(f"  #{r.id}: previous result (its variants are gone)")
        return r

    def _sensor_to_base(self, m):
        """Bool mask over the CFA array -> the same pixels in base.png."""
        y0, x0, h, w = self.raw.frame
        o = apply_t(m[y0:y0 + h, x0:x0 + w], self.t)
        im = Image.fromarray(np.ascontiguousarray(o).astype(np.uint8) * 255).resize(self.base.size, Image.BILINEAR)
        return np.asarray(im) > 64

    def _photo_id(self, path):
        """LightCraft's id for a file: looked for in the original's stack."""
        for i in ((self.info.get("stack") or {}).get("photos") or []):
            try:
                p = self.lc.one("photo.inspect", {"id": i}).get("source", {}).get("path", "")
            except Fail:
                continue
            if p and os.path.normcase(os.path.abspath(p)) == os.path.normcase(str(path.resolve())):
                return i
        return None

    def save_project(self):
        with self._proj_lock:
            try:
                project.save(self)
            except OSError as e:
                log(f"ERROR saving the project: {e}")

    # -------------------------------------------------------------- removals
    def working_cfa(self, upto=None):
        """The sensor data with the chosen fills of the removals before `upto` (all if None) applied."""
        rs = self.removals
        if upto is not None and upto in rs:
            rs = rs[:rs.index(upto)]
        rs = [r for r in rs if not r.deleted and r.chosen is not None]
        key = tuple((r.id, r.chosen_label(), tuple(r.box)) for r in rs)
        if key != self._work_key:
            cfa = self.raw.cfa.copy()
            for r in rs:
                y0, y1, x0, x1 = r.box
                cfa[y0:y1, x0:x1] = self.raw.fill_region(r.box, r.filled(), r.gain, self.hole(r)[1], cfa=cfa,
                                                         rng_seed=r.id)
            self._work_cfa, self._work_key = cfa, key
        return self._work_cfa

    @staticmethod
    def leaks(r):
        """Whether part of r's selection lies outside its area (fit_area)."""
        Y0, Y1, X0, X1 = r.base_rect
        inside = np.zeros(r.mask_e.shape, bool)
        inside[Y0:Y1, X0:X1] = True
        return (r.mask_e & ~inside).sum() >= 20

    def fit_area(self, r):
        """A removal whose area leaves part of its selection out — made before areas could be longer than the photo's
        short side: those parts were never removed (a pole's base). Its area grows to hold all of the selection; its
        variants stay as they were (each keeps the old hole, in the larger area), new ones fill all of it. Returns
        whether it grew."""
        if not self.leaks(r):
            return False
        __, box, __ = plan_region(self.raw, r.mask_e, self.lum_e, self.t, square=False)
        oy0, oy1, ox0, ox1 = r.box
        box = (min(box[0], oy0), max(box[1], oy1), min(box[2], ox0), max(box[3], ox1))
        if box == tuple(r.box):
            return False
        __, __, reg = plan_region(self.raw, r.mask_e, self.lum_e, self.t, box=box)
        old_reg, old_cands = r.reg_mask, list(r.candidates)
        dy, dx = oy0 - box[0], ox0 - box[2]
        h, w = old_reg.shape

        def placed(a):  # an old area's bool array in the new area
            out = np.zeros(reg.shape, bool)
            out[dy:dy + h, dx:dx + w] = a
            return out
        old_holes = {label: placed(r.holes.get(label, old_reg)) for label, __ in old_cands}
        r.box, r.reg_mask = box, reg | placed(old_reg)
        self._init_area(r, upto=r)
        r.candidates = []
        for label, im in old_cands:
            a = np.asarray(r.src).copy()
            a[dy:dy + h, dx:dx + w] = np.asarray(im.convert("RGB"))
            r.candidates.append((label, Image.fromarray(a)))
            r.holes[label] = old_holes[label]
        r.png.clear()  # images, holes and the area changed: encoded again at the next save
        r.preview, r.hole_cache, r.plans, r.shape, r.flat = {}, {}, {}, None, False
        self._work_cfa, self._work_key = None, None
        log(f"#{r.id}: area grown to hold its whole selection, {box[3] - box[2]}x{box[1] - box[0]} px"
            f" ({len(old_cands)} variants kept)")
        return True

    def new_removal(self, mask_e):
        """A removal for mask_e (bool, base.png frame): its area, rendered from the photo as it is now (earlier
        removals applied)."""
        t0 = time.time()
        r = Removal(self.next_id, mask_e)
        self.next_id += 1
        _, r.box, r.reg_mask = plan_region(self.raw, mask_e, self.lum_e, self.t, square=False)
        self._init_area(r)
        self.removals.append(r)
        measured("area", time.time() - t0)
        return r

    def _init_area(self, r, upto=None):
        """The area image (photo with the earlier removals applied: those before `upto`, else all), its masks,
        blending and preview placement."""
        srgb, r.gain = self.raw.render(r.box, r.gain, cfa=self.working_cfa(upto))  # gain None: from this area
        r.src = Image.fromarray((srgb * 255).round().astype(np.uint8))
        r.mask_img = Image.fromarray((r.reg_mask * 255).astype(np.uint8))
        r.alpha = np.asarray(r.mask_img.filter(ImageFilter.GaussianBlur(3))).astype(np.float64) / 255.0
        r.membrane = blend.Membrane(r.reg_mask)
        r.hole_cache = {}
        r.flat = False
        r.filled = lambda r=r: np.asarray(Image.composite(r.candidates[r.chosen][1], r.src, self.hole(r)[0])
                                          ).astype(np.float64) / 255.0
        self._place(r)
        r.src.save(self.work / f"r{r.id}_src.png")
        r.mask_img.save(self.work / f"r{r.id}_mask.png")

    def _place(self, r):
        """Where the removal's area lands in base.png, and a per-channel tone curve from the render space to
        base.png's developed look (fitted on the pixels around the hole), for the window's preview."""
        y0, x0, h, w = self.raw.frame
        by0, by1, bx0, bx1 = r.box
        Y0, Y1, X0, X1 = rect_t((by0 - y0, by1 - y0, bx0 - x0, bx1 - x0), (h, w), self.t)
        s = self.base_scale
        Y0, Y1, X0, X1 = (int(round(v * s)) for v in (Y0, Y1, X0, X1))
        Y1, X1 = min(Y1, self.base.height), min(X1, self.base.width)
        r.base_rect = (Y0, Y1, X0, X1)
        size = (max(1, X1 - X0), max(1, Y1 - Y0))
        r.base_alpha = self._base_alpha(r, r.alpha)
        src_o = np.asarray(Image.fromarray(np.ascontiguousarray(apply_t(np.asarray(r.src), self.t))).resize(
            size, Image.BILINEAR))
        base_c = self.base_arr[Y0:Y1, X0:X1]
        keep = r.base_alpha < 0.01
        r.lut = []
        for c in range(3):
            xs, ys = src_o[..., c][keep], base_c[..., c][keep]
            if xs.size < 500:
                r.lut.append(np.arange(256, dtype=np.uint8))
                continue
            known, vals = [], []
            for v in range(256):
                sel = ys[xs == v]
                if sel.size >= 4:
                    known.append(v)
                    vals.append(float(np.median(sel)))
            if len(known) < 8:
                r.lut.append(np.arange(256, dtype=np.uint8))
                continue
            lut = np.interp(np.arange(256), known, vals)
            lut = np.convolve(np.pad(lut, 3, mode="edge"), np.ones(7) / 7, mode="valid")
            r.lut.append(np.clip(np.maximum.accumulate(lut), 0, 255).astype(np.uint8))

    def _base_alpha(self, r, alpha):
        """An area alpha (render space) in base.png's frame, over r.base_rect."""
        Y0, Y1, X0, X1 = r.base_rect
        return np.asarray(Image.fromarray(np.ascontiguousarray(apply_t((alpha * 255).astype(np.uint8), self.t))).resize(
            (max(1, X1 - X0), max(1, Y1 - Y0)), Image.BILINEAR)).astype(np.float32) / 255.0

    def hole(self, r, label=None):
        """(mask image, alpha, alpha in base.png) of a variant (default: the chosen one): the area's hole, or for a
        variant that also removed the object's shadow, that hole grown by what the model changed."""
        label = r.chosen_label() if label is None else label
        m = r.holes.get(label)
        if m is None:
            return r.mask_img, r.alpha, r.base_alpha
        if label not in r.hole_cache:
            mi = Image.fromarray((m * 255).astype(np.uint8))
            al = np.asarray(mi.filter(ImageFilter.GaussianBlur(3))).astype(np.float64) / 255.0
            r.hole_cache[label] = (mi, al, self._base_alpha(r, al))
        return r.hole_cache[label]

    def preview(self, r, idx=None):
        """(patch, alpha) of candidate idx (default: chosen) in base.png's frame and look."""
        idx = r.chosen if idx is None else idx
        label, im = r.candidates[idx]
        if label not in r.preview:
            mi, _al, base_al = self.hole(r, label)
            a = np.asarray(Image.composite(im, r.src, mi))
            a = np.stack([r.lut[c][a[..., c]] for c in range(3)], -1)
            Y0, Y1, X0, X1 = r.base_rect
            patch = np.asarray(Image.fromarray(np.ascontiguousarray(apply_t(a, self.t))).resize(
                (max(1, X1 - X0), max(1, Y1 - Y0)), Image.LANCZOS))
            r.preview[label] = (patch, base_al)
        return r.preview[label]

    def composite(self, only=None):
        """base.png with the chosen fill of every removal (only=[removals] to limit), as uint8 HxWx3."""
        out = self.base_arr.astype(np.float32)
        for r in self.removals:
            if r.deleted or r.chosen is None or (only is not None and r not in only):
                continue
            patch, al = self.preview(r)
            Y0, Y1, X0, X1 = r.base_rect
            sub = out[Y0:Y1, X0:X1]
            ph, pw = sub.shape[:2]
            sub[:] = sub * (1 - al[:ph, :pw, None]) + patch[:ph, :pw].astype(np.float32) * al[:ph, :pw, None]
        return np.clip(out, 0, 255).astype(np.uint8)

    def add_candidate(self, r, label, im):
        r.candidates.append((label, im))
        try:
            im.save(self.work / f"r{r.id}_{label.replace(' ', '')}.png")  # for comparing / debugging
        except OSError:
            pass
        if not r.user_picked:
            r.chosen = len(r.candidates) - 1

    def delete_variant(self, r, idx):
        """Drop variant idx of r for good (the project keeps no copy of it). If it was the chosen one, the variant
        before it is chosen (none if it was the last). New variants keep counting (FLUX 5 after FLUX 4, even if FLUX
        4 was deleted): a label is never reused. Returns the label."""
        label = r.candidates[idx][0]
        del r.candidates[idx]
        for d in (r.png, r.preview, r.holes, r.hole_cache, r.scale):
            d.pop(label, None)
        r.png.pop(label + "#hole", None)
        if r.chosen is not None and r.chosen >= idx:
            r.chosen = max(0, r.chosen - 1) if r.candidates else None
        log(f"#{r.id}: deleted variant {label}" + (f", chosen {r.chosen_label()}" if r.chosen is not None else ""))
        return label

    # -------------------------------------------------------------- engines
    def get_sam(self):
        """SAM 3 with the photo analysed; reloaded if FLUX pushed it off the GPU."""
        with self._engine_lock:
            if self.sam is None:
                t0 = time.time()
                self.sam = engines.SAM3(log)
                log(f"SAM 3 loaded in {time.time() - t0:.0f}s")
            if getattr(self.sam, "img", None) is None and getattr(self, "base", None) is not None:
                t0 = time.time()
                self.sam.set_image(self.base)
                log(f"SAM 3: photo analysed in {time.time() - t0:.1f}s")
            return self.sam

    def engine_loaded(self, model):
        if model == "osor":
            return self.flux is not None and self.flux.osor_loaded()
        return getattr(self, model, None) is not None

    def get_engine(self, model):
        """SDXL, FLUX, ObjectClear or Qwen-Image on the GPU — one at a time (16 GB): switching unloads the others,
        and SAM 3 for FLUX and Qwen-Image. OSOR is FLUX's engine with OSOR's adapter (loaded the first time)."""
        with self._engine_lock:
            name = "flux" if model == "osor" else model
            for other in ("sdxl", "flux", "objectclear", "qwen"):
                if other != name and getattr(self, other) is not None:
                    getattr(self, other).unload()
                    setattr(self, other, None)
            if name in ("flux", "qwen") and self.sam is not None:
                self.sam.unload()
                self.sam = None
            t0 = time.time()
            if getattr(self, name) is None:
                setattr(self, name, {"sdxl": engines.SDXL, "flux": engines.FLUX, "objectclear": engines.ObjectClear,
                                     "qwen": engines.Qwen}[name](log))
            if model == "osor" and not self.flux.osor_loaded():
                self.flux.load_osor(log)
            if time.time() - t0 > 1:
                measured(f"{model}_load", time.time() - t0)
            return getattr(self, name)

    def load_sdxl(self):  # the window preloads the default engine
        return self.get_engine("sdxl")

    # -------------------------------------------------------------- generation
    def run_lama(self, r):
        t0 = time.time()
        self.check_stop()
        plan = self.tile_plan(r, "lama")
        raw = (engines.lama(r.src, r.mask_img) if plan is None else
               self._tiled(r, "lama", None, plan, "", r.id, progress=self.check_stop))
        im = blend.seamless(raw, r.src, r.reg_mask, r.membrane, seed=r.id, texture=self.texture(r, "lama", plan))
        r.prefill = Image.composite(im, r.src, r.mask_img)  # diffusion starts from this, not from the object
        r.scale["LaMa"] = self.enlarged(r, "lama", plan)
        self.add_candidate(r, "LaMa", im)
        if plan is None:
            measured("lama", time.time() - t0)
        log(f"#{r.id} LaMa in {time.time() - t0:.1f}s")
        return "LaMa", im

    def check_stop(self, *__):
        """Raise Stopped when the window's Stop was pressed (called at every step and square)."""
        if self.stop.is_set():
            raise Stopped()

    def run_model(self, r, model, prompt, progress=None):
        """One variant of `model` for r: (label, image). Session.stop ends it at its next step: Stopped, and nothing
        is added (its number is used again by the next one)."""
        k = r.counts.get(model, 0)

        def step(i, total):
            self.check_stop()
            if progress:
                progress(i, total)
        try:
            self.check_stop()
            return self._run_model(r, model, prompt, step)
        except Stopped:
            r.counts[model] = k
            r.holes.pop(f"{MODELS[model]} {k + 1}", None)
            engines._free_gpu()
            log(f"#{r.id}: stopped, {MODELS[model]} {k + 1} dropped")
            raise

    def _run_model(self, r, model, prompt, progress):
        eng = self.get_engine(model)
        k = r.counts.get(model, 0) + 1
        r.counts[model] = k
        seed = self.seed + 97 * r.id + {"flux": 1000, "osor": 2000, "objectclear": 3000, "qwen": 4000}.get(model, 0) + k
        if model == "flux":  # the text is encoded once per prompt (CPU, slow): not part of a variant's time
            eng.embeddings(f"{prompt}, {engines.DEFAULT_PROMPT}" if prompt else engines.DEFAULT_PROMPT, log)
        elif model == "osor":
            eng.embeddings(engines.OSOR_PROMPT, log, tokens=512)
        t0 = time.time()
        label = f"{MODELS[model]} {k}"
        plan = self.tile_plan(r, model)
        if plan is not None and model in ("osor", "objectclear"):  # an oblong area: in squares, effects joined
            effect = np.zeros(r.reg_mask.shape, np.uint8)
            raw_fill = self._tiled(r, model, eng, plan, prompt, seed, progress, effect=effect)
            hole = self._effect_hole(r, Image.fromarray(effect))
            if hole is not None:
                r.holes[label] = hole
        elif plan is not None:  # a long removal: in squares along the hole (tiles.py)
            raw_fill = self._tiled(r, model, eng, plan, prompt, seed, progress)
        elif model == "sdxl":
            # upright (SDXL_UPRIGHT); the sky the hole continues is held for the first steps (its colour is fixed
            # after the blend)
            up, down = (self._up, self._down) if SDXL_UPRIGHT else (lambda a: a, lambda a: a)
            flat = self.flat(r)
            hold = None if flat is None else (up(Image.fromarray(flat[1])), up(flat[0]))
            raw_fill = down(eng.fill(up(r.src), up(r.mask_img), prompt, seed, strength=SDXL_STRENGTH,
                                     progress=progress, hold=hold))
        elif model == "flux":
            # FLUX sees the area as the sensor stores it (a portrait photo on its side), unlike SDXL: sideways it keeps
            # skies clean, and upright it fills a standing, person-shaped hole with something standing — a signboard
            # on a path (4 variants in 8), a flag on a tower's edge (2 in 8), a new woman holding the bag left outside
            # the selection (6 in 8). Sideways: no signboards or flags, and a person once (legs, upside down).
            raw_fill = eng.fill(r.src, r.mask_img, prompt, seed, progress=progress, log=log)
        elif model == "qwen":
            raw_fill = self._qwen(eng, r.src, r.mask_img, prompt, seed, progress)
        else:  # OSOR / ObjectClear: no prompt; they also say how far the object's shadow and reflection go
            raw_fill, effect = self._effect_fill(model, eng, r.src, r.reg_mask, seed, progress)
            hole = self._effect_hole(r, effect)
            if hole is not None:
                r.holes[label] = hole
        hole = r.holes.get(label)
        texture = self.texture(r, model, plan)
        if hole is None:
            im = blend.seamless(raw_fill, r.src, r.reg_mask, r.membrane, seed=seed, texture=texture)
        else:
            im = blend.seamless(raw_fill, r.src, hole, seed=seed, texture=texture)
        if model == "sdxl" and r.flat is not None:
            im = blend.match_flat(im, r.flat[1], r.flat[0])
        r.scale[label] = self.enlarged(r, model, plan)
        self.add_candidate(r, label, im)
        if plan is None:  # a tiled variant's time is the squares' (measured each)
            measured(f"{model}_variant", time.time() - t0)
        log(f"#{r.id} {label} in {time.time() - t0:.0f}s"
            + (f" ({len(plan[1])} squares of {plan[1].T} px at {plan[0]})" if plan is not None else "")
            + (f" (prompt: {prompt or 'default'})" if model in ("sdxl", "flux") else "")
            + (f" (removing: {eng.what})" if model == "qwen" and eng.what else "")
            + (f" | shadow/reflection: +{int((hole & ~r.reg_mask).sum())} px" if hole is not None else ""))
        return label, im

    def _qwen(self, eng, src, mask, prompt, seed, progress=None):
        """Qwen-Image sees the area upright, as the photo is seen: it names the selection first, and on its side a
        pole across columns was named "the overhead cable" and stayed (upright: "the floor lamp", removed)."""
        return self._down(eng.fill(self._up(src), self._up(mask), prompt, seed, progress=progress, log=log))

    def _up(self, a):
        """An area image or array (sensor orientation) as the photo is seen; PIL in, PIL out."""
        o = np.ascontiguousarray(apply_t(np.asarray(a), self.t))
        return Image.fromarray(o) if isinstance(a, Image.Image) else o

    def _down(self, a):
        """The inverse of _up."""
        o = np.ascontiguousarray(invert_t(np.asarray(a), self.t))
        return Image.fromarray(o) if isinstance(a, Image.Image) else o

    def flat(self, r):
        """The part of r's hole that continues a sky (or another flat surface) and its colours (blend.flat_region),
        once per removal; None when it is too small to matter."""
        if r.flat is False:
            region, field = blend.flat_region(np.asarray(r.src), r.reg_mask, r.membrane)
            r.flat = (region, field) if region.sum() >= max(400, 0.01 * r.reg_mask.sum()) else None
        return r.flat

    # -------------------------------------------------------------- long removals, in squares (tiles.py)
    @staticmethod
    def tile_seconds(model, size, refine=False):
        """What one square takes on this PC (measured), drawn or redrawn ("Full detail")."""
        return expected(f"{model}_{'refine' if refine else 'tile'}{size}")

    def tile_plan(self, r, model, label=None, refine=False):
        """(engine size, tiles.Plan) to fill r's hole in squares, or None for one pass as before. label: the variant
        whose hole it is (OSOR / ObjectClear variants have their own). For a variant: only a thin hole, only when one
        pass would enlarge the fill more than TILE_FROM times, in squares as small as TILE_BUDGET allows. For a
        refinement ("Full detail"): any hole, as near the engine's size as REFINE_BUDGET allows. An area longer than
        a square (plan_region square=False) is always filled in squares, by every engine: at worst squares of its
        short side, each as one pass would be."""
        sizes = TILE_SIZES.get(model)
        oblong = r.reg_mask.shape[0] != r.reg_mask.shape[1]
        if not sizes or (not refine and not oblong and model not in TILED_VARIANTS):
            return None
        own = label if label in r.holes else None
        key = (model, refine, own)  # decided once per removal: its variants are all made alike
        if key not in r.plans:
            r.plans[key] = self._tile_plan(r.holes[own] if own else r.reg_mask, model, sizes, refine)
        return r.plans[key]

    def _tile_plan(self, hole, model, sizes, refine):
        short = min(hole.shape)
        oblong = hole.shape[0] != hole.shape[1]
        one = sizes[0] if short <= sum(sizes) // 2 else sizes[-1]  # the size one pass uses
        if not oblong and short <= (1.5 if refine else TILE_FROM) * one:
            return None
        width, length = tiles.shape(hole)
        if not refine and not oblong and length < TILE_LONG * width:
            return None
        budget = REFINE_BUDGET if refine else TILE_BUDGET
        best = None
        if refine or model in TILED_VARIANTS:
            for size in sizes:
                secs = self.tile_seconds(model, size, refine)
                for f in TILE_SCALES:
                    T = int(size * f) // 16 * 16
                    if T >= 0.8 * short:  # hardly better than one pass
                        break
                    if width > TILE_WIDE * T:  # each square must see the photo across the hole
                        continue
                    n = len(tiles.squares(hole, T))
                    if n * secs <= budget:
                        if best is None or (f, n) < best[:2]:
                            best = (f, n, size, T)
                        break  # larger squares only enlarge more
        if best is None:
            if not oblong:
                return None
            best = (0, 0, one, short)  # squares of the short side: each as one pass would be
        __, __, size, T = best
        return size, tiles.Plan(hole, T)

    @staticmethod
    def long(r):
        """Whether r's hole is long and thin (a pole, a cable, a railing; not a person): TILE_LONG."""
        if r.shape is None:
            r.shape = tiles.shape(r.reg_mask)
        width, length = r.shape
        return length >= TILE_LONG * width

    @classmethod
    def thin(cls, r):
        """Whether r's hole is a cord, a cable, a wire or a closely selected pole: long and at most THIN px wide."""
        return cls.long(r) and r.shape[0] <= THIN

    def variant_seconds(self, r, model):
        """What one variant of `model` will take for r (for the progress bar)."""
        plan = self.tile_plan(r, model)
        if plan is None:
            return expected("lama" if model == "lama" else f"{model}_variant")
        return len(plan[1]) * self.tile_seconds(model, plan[0]) + expected("tiled_blend")

    def _tiled(self, r, model, eng, plan, prompt, seed, progress=None, src=None, strength=1.0, effect=None):
        """r's raw fill made square by square (tiles.Plan.fill); src (default: the area) and strength < 1 redraw a
        fill already in the hole. SDXL sees each square upright, with the sky it continues held. OSOR / ObjectClear:
        `effect` (uint8, the area's shape) gets what each square changed (their shadow and reflection maps)."""
        size, P = plan
        up, down = (self._up, self._down) if model == "sdxl" and SDXL_UPRIGHT else (lambda a: a, lambda a: a)
        flat = self.flat(r) if model == "sdxl" and strength >= 1 else None
        key = f"{model}_{'tile' if strength >= 1 else 'refine'}{size}"

        def one(img, mask, k):
            s = seed + 7919 * k
            if model == "flux":
                out = eng.fill(img, mask, prompt, s, log=log, strength=strength, size=size, progress=self.check_stop)
            elif model == "lama":
                out = engines.lama(img, mask)
            elif model == "qwen":
                out = self._qwen(eng, img, mask, prompt, s, self.check_stop)
            elif model in ("osor", "objectclear"):
                out, eff = self._effect_fill(model, eng, img, np.asarray(mask) > 127, s, self.check_stop)
                sl = P.steps[k][0]
                effect[sl] = np.maximum(effect[sl], np.asarray(eff.convert("L")))
            else:
                hold = None
                if flat is not None:
                    sl = P.steps[k][0]
                    region = flat[0][sl] & (np.asarray(mask) > 127)
                    if region.sum() >= 400:
                        hold = (up(Image.fromarray(np.ascontiguousarray(flat[1][sl]))), up(region))
                out = down(eng.fill(up(img), up(mask), prompt, s, strength=SDXL_STRENGTH if strength >= 1 else strength,
                                    hold=hold, progress=self.check_stop))
            return out
        t0 = time.time()
        out = P.fill(r.src if src is None else src, one, progress)
        secs = time.time() - t0
        measured(key, secs / max(1, len(P)))  # a square with its share of the matching (blend.Membrane)
        redrawn = "" if strength >= 1 else f", redrawn at {strength}"
        log(f"#{r.id}: {len(P)} squares of {P.T} px ({model} at {size}{redrawn}) in {secs:.0f}s")
        return out

    @staticmethod
    def texture(r, model, plan):
        """Whether the blend adds texture copied from around the hole (blend.texture_field): only to a fill made in
        one pass, as before. Along a long removal the copied patches carry the edges next to it (columns beside a
        plain wall) into the fill as streaks — measured at every square size, 1.25x to 3.5x."""
        return plan is None

    def refine_model(self):
        """The engine "Full detail" redraws with: FLUX (the most detail), else SDXL; None without a GPU model."""
        return next((m for m in ("flux", "sdxl") if engines.usable(m)), None)

    @staticmethod
    def enlarged(r, model, plan=None):
        """How many photo pixels one pixel of a fill of `model` for r covers (1: drawn at the photo's resolution)."""
        if plan is not None:
            return plan[1].T / plan[0]
        side = max(r.reg_mask.shape)
        if model in ("flux", "osor"):
            return side / (engines.FLUX_SIZES[0] if side <= sum(engines.FLUX_SIZES) // 2 else engines.FLUX_SIZES[1])
        own = {"sdxl": engines.SDXL.S, "objectclear": engines.ObjectClear.S, "qwen": engines.QWEN_SIZE}
        return side / own.get(model, 512)

    def can_refine(self, r):
        """Whether "Full detail" would redraw r's chosen variant sharper: a long removal's variant drawn smaller than
        the photo (more than 1.6 times), not redrawn already."""
        label = r.chosen_label()
        if label is None or label.endswith(REFINED) or self.refine_model() is None or not self.long(r):
            return False
        f = r.scale.get(label)  # unknown for variants of a reopened project: made in one pass
        if f is None:
            f = self.enlarged(r, LABEL_MODELS.get(label.split()[0], "lama"))
        return f > 1.6

    def refine_seconds(self, r):
        model = self.refine_model()
        plan = self.tile_plan(r, model, r.chosen_label(), refine=True) if model else None
        return 0.0 if plan is None else len(plan[1]) * self.tile_seconds(model, plan[0], True) + expected("tiled_blend")

    def refine(self, r, prompt="", progress=None):
        """"Full detail": r's chosen variant redrawn in squares near the engine's own size (tiles.py), at
        REFINE_STRENGTH — what it shows stays, its detail is drawn at the photo's resolution. A new variant
        "<label> HD", chosen. Returns (label, image) or None when there is nothing to gain."""
        label = r.chosen_label()
        model = self.refine_model()
        plan = self.tile_plan(r, model, label, refine=True) if self.can_refine(r) else None
        if plan is None:
            return None
        eng = self.get_engine(model)
        if model == "flux":
            eng.embeddings(f"{prompt}, {engines.DEFAULT_PROMPT}" if prompt else engines.DEFAULT_PROMPT, log)
        t0 = time.time()
        mask_img, __, __ = self.hole(r, label)
        src = Image.composite(r.candidates[r.chosen][1], r.src, mask_img)
        seed = self.seed + 97 * r.id + 5000 + len(r.candidates)
        try:
            raw = self._tiled(r, model, eng, plan, prompt, seed, progress, src=src, strength=REFINE_STRENGTH)
        except Stopped:
            engines._free_gpu()
            log(f"#{r.id}: Full detail stopped")
            raise
        hole = r.holes.get(label)
        if hole is None:
            im = blend.seamless(raw, r.src, r.reg_mask, r.membrane, seed=seed, texture=self.texture(r, model, plan))
        else:
            im = blend.seamless(raw, r.src, hole, seed=seed, texture=self.texture(r, model, plan))
        labels = {c[0] for c in r.candidates}
        new, n = label + REFINED, 2
        while new in labels:
            new, n = f"{label}{REFINED} {n}", n + 1
        if hole is not None:
            r.holes[new] = hole
        r.scale[new] = self.enlarged(r, model, plan)
        self.add_candidate(r, new, im)
        r.chosen = len(r.candidates) - 1
        log(f"#{r.id} {new} in {time.time() - t0:.0f}s")
        return new, im

    def _effect_fill(self, model, eng, src, hole, seed, progress=None):
        """OSOR / ObjectClear on an area (sensor orientation), shown to them upright — as the photo is seen: they
        recognise a shadow by where the light comes from and where the ground is — and turned back. Returns
        (image, effect) in the area's orientation."""
        fill = eng.fill_osor if model == "osor" else eng.fill
        img, effect = fill(self._up(src), self._up(Image.fromarray((hole * 255).astype(np.uint8))), seed=seed,
                           progress=progress, log=log)
        return self._down(img), self._down(effect)

    def _effect_hole(self, r, effect):
        """The hole of an OSOR / ObjectClear variant: the area's hole plus what the model changed beyond it (the
        object's shadow, its reflection), slightly grown like the object's own hole. None if that adds nothing
        worth it. The very edge of the area stays out: the blend needs photo all around the hole."""
        e = np.asarray(effect.convert("L")) > 127
        side = max(e.shape)
        e = grow(e, max(3, side // 250))
        b = max(2, side // 100)
        e[:b], e[-b:], e[:, :b], e[:, -b:] = False, False, False, False
        extra = e & ~r.reg_mask
        if extra.sum() < max(50, 0.02 * r.reg_mask.sum()):
            return None
        return r.reg_mask | e

    def shadow_model(self):
        """The model "Includi l'ombra" uses: OSOR (its effect map is the most precise), else ObjectClear."""
        return next((m for m in engines.SHADOW_MODELS if engines.usable(m)), None)

    def _shadow_pass(self, model, eng, mask_e, margin, progress=None):
        """The model's effect map over the area around mask_e (side = margin x the object), on the whole sensor
        frame, and whether it reaches the area's edge (the shadow goes on beyond it)."""
        _t, box, hole = plan_region(self.raw, mask_e, self.lum_e, self.t, margin=margin)
        srgb, __ = self.raw.render(box, None, cfa=self.working_cfa())
        src = Image.fromarray((srgb * 255).round().astype(np.uint8))
        __, effect = self._effect_fill(model, eng, src, hole, self.seed, progress)
        a = np.asarray(effect.convert("L")) > 127
        b = max(2, a.shape[0] // 50)
        edge = np.ones_like(a)
        edge[b:-b, b:-b] = False
        e = np.zeros(self.raw.cfa.shape, bool)
        y0, y1, x0, x1 = box
        e[y0:y1, x0:x1] = a
        return e, box, (a & edge).sum() > 0.005 * edge.sum()

    def find_shadow(self, mask_e, progress=None, margin=SHADOW_MARGIN):
        """"Includi l'ombra": what OSOR (or ObjectClear) removes together with the selected object — its shadow,
        its reflection — as a bool mask in base.png's frame, outside the selection; None if there is nothing.
        The area is the size of a removal's: the smaller the object is in the model's 512/768 px view, the less it
        sees of its shadow. When the shadow reaches the area's edge, once more in a larger area."""
        model = self.shadow_model()
        if model is None:
            raise Fail(_("Neither OSOR nor ObjectClear is installed: they find the shadow (see the installer)"))
        t0 = time.time()
        eng = self.get_engine(model)
        e, box, beyond = self._shadow_pass(model, eng, mask_e, margin, progress)
        if beyond:
            e2, box2, __ = self._shadow_pass(model, eng, mask_e, margin * 1.6, progress)
            if box2[1] - box2[0] > box[1] - box[0]:  # not already the whole photo's height or width
                log("shadow: it goes beyond the area, looked again in a larger one")
                e, box = e2, box2
        y0, y1, x0, x1 = box
        # the effect map is coarse (OSOR: 1/8 of its 512/768 px view, ObjectClear: 1/16 of 512 px): the band of one
        # or two of its cells around the object is its blur, not a shadow
        side = y1 - y0
        view = engines.FLUX_SIZES[0] if side <= sum(engines.FLUX_SIZES) // 2 else engines.FLUX_SIZES[1]
        cell = side / (view / 8 if model == "osor" else engines.ObjectClear.S / 16)
        band_px = max(2, int(round(1.5 * cell * self.base_scale)))
        eff = self._sensor_to_base(e) & ~mask_e
        band = grow(mask_e, band_px) & ~mask_e
        m = eff & ~band
        lab, n = ndi.label(m)
        if n:  # specks are not a shadow
            sizes = ndi.sum(m, lab, range(1, n + 1))
            keep = np.zeros(n + 1, bool)
            keep[1:] = sizes >= max(30, 0.01 * mask_e.sum())
            m = keep[lab]
        if m.any():
            m |= eff & band & grow(m, band_px)  # the band only where a shadow crosses it, joining it to the object
        measured("shadow", time.time() - t0)
        log(f"shadow ({MODELS[model]}): {int(m.sum())} px next to a {int(mask_e.sum())} px selection, "
            f"in {time.time() - t0:.1f}s")
        return m if m.any() else None

    # -------------------------------------------------------------- output
    def write_all(self):
        """The photo with every removal's chosen fill, always into the same <stem>-AIRemove.dng: created, stacked and
        given the original's development the first time; afterwards rewritten and reloaded in LightCraft (its own
        edits kept). The project file is saved with it. Returns (path, photo id, updated?)."""
        rs = [r for r in self.removals if not r.deleted and r.chosen is not None]
        if not rs:
            raise Fail(_("No removal to save."))
        t0 = time.time()
        cfa = self.working_cfa()
        update = self.dng_path is not None and self.dng_path.exists()
        out = self.dng_path if update else unique_path(self.src_path.with_name(f"{self.src_path.stem}-AIRemove.dng"))
        tmp = out.with_name(out.stem + ".tmp.dng")
        self.raw.write_cfa(str(tmp), cfa, [r.box for r in rs])
        try:
            os.replace(tmp, out)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            raise Fail(_("{file} is locked by another program: close it and save again.", file=out.name))
        log(f"{'updated' if update else 'written'} {out} | removals: "
            + ", ".join(f"#{r.id} {r.chosen_label()}" for r in rs)
            + f" | rumore sensore var={self.raw.cached_noise()[0]:.2f}*S+{self.raw.cached_noise()[1]:.0f}")
        nid = None
        if update and self.dng_id:
            try:
                inf = self.lc.one("photo.inspect", {"id": self.dng_id})
                same = os.path.normcase(os.path.abspath(inf["source"]["path"])) == os.path.normcase(str(out.resolve()))
                nid = self.dng_id if same and not inf.get("deleted") else None
            except Fail:
                nid = None
        if nid is not None:
            self.lc.run([{"command": "photo.reload", "params": {"ids": [nid]}},
                         {"command": "library.select", "params": {"ids": [nid], "active": nid}}])
            log(f"reloaded in LightCraft (id {nid})")
        else:
            nid = import_stacked(self.lc, self.pid, self.info, out)
            log(f"imported into LightCraft (id {nid}), stacked with the original, same development")
        self.dng_path, self.dng_id = out, nid
        self.save_project()
        measured("save", time.time() - t0)
        return out, nid, update

    def close(self):
        if self.raw is not None:
            self.raw.close()
            self.raw = None


def check():
    """--check: what this install has and whether it can reach LightCraft, as JSON (the installer and the MCP
    server read it)."""
    rep = {"version": system.VERSION, "os": system.system(), "python": sys.version.split()[0], "root": str(ROOT),
           "port": system.control_port(), "lightcraft_settings": str(system.lightcraft_config_dir())}
    try:
        sel = LC().state().get("selection") or {}
        rep["lightcraft"] = {"connected": True, "active_photo": sel.get("active"), "selected": len(sel.get("ids") or [])}
    except Fail as e:
        rep["lightcraft"] = {"connected": False, "error": str(e).splitlines()[0]}
    try:
        import torch
        rep["torch"] = torch.__version__
        rep["device"], rep["gpu"] = system.gpu_summary()
    except Exception as e:
        rep["torch_error"] = f"{type(e).__name__}: {e}"
    rep["models"] = engines.available()
    rep["model_folders"] = engines.model_folders()  # parts used from the user's own folders (the rest: models/)
    rep["usable_models"] = [m for m in ("lama", "sdxl", "flux", "osor", "objectclear", "qwen")
                            if engines.usable(m, rep.get("device", "cpu"))]
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return 0


def auto(args):
    """--auto MODEL[N]: no window. One removal from the photo's "Rimuovi" masks, made with MODEL; variant N (default
    1) is the one used; the DNG is written and stacked like "Salva in LightCraft". --shadow: the object's shadow and
    reflection are added to the selection first ("Includi l'ombra"). Prints a JSON line."""
    m = re.fullmatch(r"(lama|sdxl|flux|osor|objectclear|qwen)(\d*)", args.auto.strip().lower())
    if not m:
        raise Fail(_("--auto: lama | sdxl | flux | osor | objectclear | qwen, optionally the number of the variant "
                     "to use (e.g. sdxl2)"))
    model, pick = m.group(1), max(1, int(m.group(2) or 1))
    if model != "lama" and not engines.usable(model, engines.device()):
        raise Fail(_("{model} is not installed or does not run on this computer (see --check)", model=MODELS[model]))
    s = Session(LC(), args)
    try:
        s.prepare()
        if s.init_mask is None:
            raise Fail(_("--auto needs a \"Remove\" mask on the photo in LightCraft (e.g. an Object mask renamed "
                         "\"Remove\", or \"Remove: old wooden door\" to guide the fill)"))
        sel = s.init_mask
        if getattr(args, "shadow", False):
            shadow = s.find_shadow(sel)
            if shadow is not None:
                sel = sel | shadow
        r = s.new_removal(sel)
        if model == "lama":
            s.run_lama(r)
            pick = 1
        else:
            for __ in range(pick):
                s.run_model(r, model, s.prompt)
        r.chosen, r.user_picked = pick - 1, True
        s.save_project()
        out, nid, update = s.write_all()
        print(json.dumps({"ok": True, "dng": str(out), "photo_id": nid, "updated": update, "removal": r.id,
                          "variant": r.chosen_label(), "project": str(project.path_for(s.src_path))}), flush=True)
    finally:
        s.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description="AI Remove for LightCraft")
    ap.add_argument("raw", nargs="?", help="path passed by LightCraft's external-editor command")
    ap.add_argument("--id", type=int, help="LightCraft photo id (default: the active photo)")
    ap.add_argument("--variants", type=int, default=None, help="variants per removal (window default: last used)")
    ap.add_argument("--auto", help="no window: lama | sdxl | flux | osor | objectclear | qwen[N] on the photo's "
                                   "Rimuovi masks")
    ap.add_argument("--shadow", action="store_true", help="--auto: remove the object's shadow and reflection too")
    ap.add_argument("--check", action="store_true", help="print a JSON report and exit")
    args = ap.parse_args()
    if args.check:
        return check()
    LOG_FILE.write_text("", encoding="utf-8")
    log(f"AI Remove {system.VERSION} started ({system.system()})", f"(file: {args.raw})" if args.raw else "")
    if args.auto:
        return auto(args)
    import ui
    return ui.run(Session(LC(), args), args)


def _quiet_streams():
    """Under pythonw (launched from LightCraft) there is no console: send stray output to a file."""
    if sys.stdout is None or sys.stderr is None:
        f = open(ROOT / "work" / "last-run.out", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def run():
    """The program: the installed `airemove` launcher (AI Remove.exe on Windows) and `python airemove.py` both
    come here."""
    (ROOT / "work").mkdir(parents=True, exist_ok=True)
    _quiet_streams()
    code = 1
    try:
        code = main() or 0
    except Fail as e:
        log("ERROR:", e)
        if "--auto" in sys.argv or "--check" in sys.argv:  # no window: the caller reads stdout
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), flush=True)
        else:
            try:
                import tkinter as tk
                from tkinter import messagebox
                r = tk.Tk(); r.withdraw(); messagebox.showerror("AI Remove", str(e)); r.destroy()
            except Exception:
                pass
    except Exception:
        log("ERROR:", traceback.format_exc())
        traceback.print_exc()
    # never through the normal shutdown once torch has touched the GPU: ROCm can hang in it (system.hard_exit)
    system.hard_exit(code)


if __name__ == "__main__":
    run()
