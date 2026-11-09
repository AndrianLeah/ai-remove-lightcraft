"""A bench for removal quality: the same removals made again, with fixed seeds, so that a change (another model, a
setting, a prompt, a change to the code) can be compared side by side with what came before, at 100 %, as it ends up
in the DNG.

  bench.py collect BENCH SOURCE...     the cases, from AI Remove projects (.airemove files, or folders searched for
                                       them): each removal's selection and the variant kept then; the photos are
                                       copied into BENCH/photos (the originals and their projects are only read)
           [--synthetic]               also, per case, its selection moved onto the background beside it, where what
                                       is under it is known (the photo itself): those fills are measured against it
  bench.py run BENCH --name NAME       the cases made again with this checkout's code and an install's models
           [--models lama,rorem:2,flux:2,qwen:1]   models and variants per model (LaMa makes one)
           [--cases GLOB,...] [--seed 1] [--prompt TEXT] [--install DIR]
  bench.py sheet BENCH [--runs A,B]    BENCH/sheet.html: per case the area before, the variant kept then and every
                                       run's variants; click one for 100 %, the arrow keys flip through them at the
                                       same spot

Run it with an install's Python, which has the models' libraries: <install>/venv/Scripts/python.exe (Windows) or
<install>/venv/bin/python. It imports AI Remove from this checkout, so a run measures the code as it is here, with the
install's models (--install, default the install that Python belongs to) and AI Remove's default settings. RAWs are
read through lightcraft-cli (or Chromaforge's), once per photo: BENCH/cache keeps that export, so later runs start
from the same data even after LightCraft is updated.

Each variant is shown as it is written: the fill put into the sensor data with its noise (RawDNG.fill_region),
rendered again, in base.png's look and upright. A run is resumable (variants made already are kept) and stops by
itself when AI Remove's window or panel opens, to leave it the GPU: run it again to go on.

Numbers, per variant (BENCH/runs/NAME/run.json, and under each picture in the sheet):
- detail: the fill's fine texture (high-pass standard deviation) over the photo's: around the hole for a real case,
  under the hole for a synthetic one. Below 1 the fill is softer than the photo, above 1 noisier.
- tone (synthetic cases): the mean difference, in levels (0-255), between the fill and the photo it replaced, both
  blurred (sigma 8 px): colour or brightness that does not match, blotches, something drawn that was not there.
They point at where to look; they do not say which fill is best. The pictures do.
"""
import argparse
import fnmatch
import html
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODELS = "lama,rorem:2,flux:2,qwen:1"
THUMB = 420  # the sheet's pictures, long side


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(p, d):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------------------------------------ the app's code
def find_install(arg):
    if arg:
        return Path(arg)
    exe = Path(sys.executable).resolve()
    for d in exe.parents:  # <install>/venv/Scripts/python.exe
        if (d / "airemove.json").exists() and (d / "venv").is_dir():
            return d
    return Path.home() / "LightCraftAI"


def load_app(install, log_file):
    """AI Remove from this checkout, reading the install's configuration (its models, its apps' paths): system.config
    answers with the install's airemove.json, models_dir set to its models folder."""
    os.environ["AIREMOVE_LOG"] = str(log_file)
    sys.path.insert(0, str(REPO / "airemove"))
    import system
    try:
        cfg = json.loads((install / "airemove.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        sys.exit(f"{install / 'airemove.json'} not found: pass --install with an AI Remove install")
    cfg.setdefault("models_dir", str(install / "models"))
    system.config = lambda: dict(cfg)
    import airemove as A
    if Path(A.__file__).resolve().parent != REPO / "airemove":
        sys.exit(f"airemove imported from {A.__file__}, not from this checkout")
    return A, cfg


def photo_data(A, bench, photo):
    """base.png and the raw DNG of a photo (lightcraft-cli, as AI Remove reads a photo on its own), kept in
    BENCH/cache/<photo>."""
    cache = bench / "cache" / photo.name
    if not ((cache / "base.png").exists() and (cache / "source.dng").exists()):
        cache.mkdir(parents=True, exist_ok=True)
        A.extract_headless(photo, cache)
    return cache / "base.png", cache / "source.dng"


def open_session(A, bench, photo, work, seed):
    """A Session on a photo, as Session.prepare() leaves it, from the cached export; no project is read (the copies
    in BENCH/photos have none)."""
    base_png, dng = photo_data(A, bench, photo)
    s = A.Session(None, argparse.Namespace(id=None, raw=str(photo), variants=None, auto=None, shadow=False),
                  path=photo)
    s.find()
    s.work, s.init_mask = work, None
    work.mkdir(parents=True, exist_ok=True)
    s.base = Image.open(base_png).convert("RGB")
    s.base_arr = np.asarray(s.base)
    s.lum_e = A.base_luminance(base_png)
    s.raw = A.open_source(str(dng))
    s.t, __ = A.match_orientation(s.raw.preview_lum(), s.lum_e)
    s.gain = s.raw.global_gain()
    __, __, h, w = s.raw.frame
    s.base_scale = s.base.width / A.apply_t(np.zeros((h, w), bool), s.t).shape[1]
    s.seed = seed
    s.bench_cfa = s.raw.cfa.copy()  # where each variant is written to be rendered again (its box restored after)
    return s


def user_app_running():
    """Whether the user's AI Remove (window or panel) is running: the bench leaves it the GPU."""
    try:
        import psutil
    except ImportError:
        return False
    me = {os.getpid()} | {p.pid for p in psutil.Process().parents()}
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        if p.info["pid"] in me:
            continue
        cmd = " ".join(p.info["cmdline"] or []).lower()
        if (p.info["name"] or "").lower() == "airemove.exe" or ("airemove" in cmd and "bench.py" not in cmd
                                                                and ("airemove.exe" in cmd or "airemove.py" in cmd)
                                                                and "--check" not in cmd):
            return True
    return False


# ------------------------------------------------------------------------------------------------ pictures
def upright(s, r, a):
    """An area image (render space, uint8) in base.png's look and upright, at 100 %."""
    a = np.stack([r.lut[c][a[..., c]] for c in range(3)], -1)
    return np.ascontiguousarray(app().apply_t(a, s.t))


def app():
    import airemove  # loaded by load_app
    return airemove


def as_written(s, r, im, hole_img, hole_alpha):
    """A variant as the DNG has it: its fill put into the sensor data (with the sensor's noise) and rendered again."""
    filled = np.asarray(Image.composite(im.convert("RGB"), r.src, hole_img)).astype(np.float64) / 255.0
    y0, y1, x0, x1 = r.box
    region = s.raw.fill_region(r.box, filled, r.gain, hole_alpha, cfa=s.raw.cfa, rng_seed=r.id)
    keep = s.bench_cfa[y0:y1, x0:x1].copy()
    s.bench_cfa[y0:y1, x0:x1] = region
    try:
        srgb, __ = s.raw.render(r.box, r.gain, cfa=s.bench_cfa)
    finally:
        s.bench_cfa[y0:y1, x0:x1] = keep
    return (np.clip(srgb, 0, 1) * 255).round().astype(np.uint8)


def outline(img, hole, colour=(255, 0, 200)):
    """img with the hole's edge drawn (2 px)."""
    from scipy import ndimage
    edge = hole & ~ndimage.binary_erosion(hole, iterations=2)
    out = img.copy()
    out[edge] = colour
    return out


def measure(img, hole, ref=None):
    """detail and, against ref (what is under a synthetic case's hole), tone: see the module's docstring."""
    from scipy import ndimage
    f = img.astype(np.float64)
    g = f.mean(-1)
    hp = g - ndimage.gaussian_filter(g, 2)
    out = {}
    if ref is None:
        ring = ndimage.binary_dilation(hole, iterations=48) & ~ndimage.binary_dilation(hole, iterations=16)
        if ring.sum() > 100 and hole.sum() > 100:
            out["detail"] = round(float(hp[hole].std() / max(hp[ring].std(), 1e-6)), 2)
        return out
    rf = ref.astype(np.float64)
    rg = rf.mean(-1)
    rhp = rg - ndimage.gaussian_filter(rg, 2)
    out["detail"] = round(float(hp[hole].std() / max(rhp[hole].std(), 1e-6)), 2)
    blur = [ndimage.gaussian_filter(f[..., c], 8) - ndimage.gaussian_filter(rf[..., c], 8) for c in range(3)]
    out["tone"] = round(float(np.mean([np.abs(b[hole]).mean() for b in blur])), 1)
    return out


def save_png(a, p):
    Image.fromarray(a).save(p, compress_level=3)


# ------------------------------------------------------------------------------------------------ collect
def find_projects(sources):
    out = []
    for src in sources:
        p = Path(src)
        if p.is_dir():
            out += sorted(p.rglob("*.airemove"))
        elif p.suffix.lower() == ".airemove" and p.exists():
            out.append(p)
        else:
            say(f"skipped {p}: not a project nor a folder")
    return out


def collect(args):
    bench = Path(args.bench)
    (bench / "photos").mkdir(parents=True, exist_ok=True)
    (bench / "cases").mkdir(exist_ok=True)
    made, skipped = [], {}
    for proj in find_projects(args.sources):
        photo = proj.with_name(proj.name[:-len(".airemove")])
        if not photo.exists():
            say(f"{proj.name}: its photo is not next to it, skipped")
            continue
        with zipfile.ZipFile(proj) as z:
            meta = json.loads(z.read("project.json"))
            if meta.get("raw", {}).get("size") not in (None, photo.stat().st_size):
                say(f"{proj.name}: made for another version of {photo.name}, skipped")
                continue
            copy = bench / "photos" / photo.name
            if not copy.exists() or copy.stat().st_size != photo.stat().st_size:
                shutil.copy2(photo, copy)
            for e in meta["removals"]:
                kind = "reflect" if e.get("reflection") else "draw" if e.get("fill") else "remove"
                if kind != "remove":  # the bench is for removals: reflections and drawings have their own models
                    skipped[kind] = skipped.get(kind, 0) + 1
                    continue
                name = f"{photo.stem}-r{e['id']}"
                d = bench / "cases" / name
                d.mkdir(exist_ok=True)
                (d / "selection.png").write_bytes(z.read(f"r{e['id']}/selection.png"))
                vs, chosen = e.get("variants") or [], e.get("chosen")
                kept = vs[chosen]["label"] if chosen is not None and 0 <= chosen < len(vs) else None
                if kept:
                    (d / "kept.png").write_bytes(z.read(vs[chosen]["file"]))
                write_json(d / "case.json", {
                    "photo": photo.name, "original": str(photo), "id": e["id"], "kind": "real",
                    "hints": e.get("hints") or [], "box": e.get("box"), "kept": kept,
                    "user_picked": bool(e.get("user_picked")), "variants_then": [v["label"] for v in vs],
                    "project_saved": meta.get("saved")})
                made.append(name)
    say(f"{len(made)} cases in {bench / 'cases'}" + "".join(f", {n} {k} removals skipped" for k, n in skipped.items()))
    if args.synthetic:
        synthesize(args, bench)


def synthesize(args, bench):
    """Per real case, its selection moved beside it, onto the background most like what surrounds it (mean colour
    and texture), away from every selection of the photo and every person in it (SAM 3's Describe): <case>-s.
    placement.jpg shows where."""
    from scipy import ndimage
    A, __ = load_app(find_install(args.install), bench / "collect.log")
    sam = A.engines.SAM3(A.log)
    cases = sorted((bench / "cases").glob("*/case.json"))
    by_photo = {}
    for c in cases:
        info = read_json(c)
        if info.get("kind") == "real":
            by_photo.setdefault(info["photo"], []).append((c.parent, info))
    n = 0
    for photo, items in by_photo.items():
        base_png, __ = photo_data(A, bench, bench / "photos" / photo)
        base = np.asarray(Image.open(base_png).convert("RGB")).astype(np.float64)
        H, W = base.shape[:2]
        sels = []
        for d, info in items:
            m = np.asarray(Image.open(d / "selection.png").convert("L")) > 127
            if m.shape != (H, W):
                m = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((W, H), Image.NEAREST)) > 127
            sels.append(m)
        sam.set_image(Image.open(base_png).convert("RGB"))
        people, __ = sam.describe("person", log=A.log)
        taken = ndimage.binary_dilation(np.logical_or.reduce(sels + [np.asarray(p, bool) for p in people]),
                                        iterations=max(8, H // 40))
        lum = base.mean(-1)
        tex = np.sqrt(np.maximum(ndimage.uniform_filter(lum ** 2, 15) - ndimage.uniform_filter(lum, 15) ** 2, 0))
        for (d, info), m in zip(items, sels):
            ys, xs = np.nonzero(m)
            if ys.size < 50:
                continue
            h, w = np.ptp(ys) + 1, np.ptp(xs) + 1
            if h * w > 0.12 * H * W:  # a crowd: no room beside it
                continue
            ring = ndimage.binary_dilation(m, iterations=40) & ~ndimage.binary_dilation(m, iterations=10)
            want = np.r_[base[ring].mean(0), tex[ring].mean()]
            margin, pad = max(H, W) // 50, 10
            y0, x0 = ys.min(), xs.min()
            shape = np.pad(m[y0:y0 + h, x0:x0 + w], pad)  # the selection, and what it covers grown by pad
            under = ndimage.binary_dilation(shape, iterations=pad)
            step = max(16, max(h, w) // 3)
            best = None
            for ny in range(margin, H - margin - h, step):  # every place in the photo, on a grid
                for nx in range(margin, W - margin - w, step):
                    win = (slice(ny - pad, ny + h + pad), slice(nx - pad, nx + w + pad))
                    if taken[win][under].any():
                        continue
                    got = np.r_[base[win][under].mean(0), tex[win][under].mean()]
                    far = np.hypot(ny - y0, nx - x0) / np.hypot(H, W)  # nearby: the same light and distance
                    score = float(np.abs(got - want).sum()) + 60 * far
                    if best is None or score < best[0]:
                        best = (score, int(ny - y0), int(nx - x0))
            if best is None:
                say(f"{d.name}: no free background in the photo")
                continue
            score, dy, dx = best
            moved = np.zeros_like(m)
            moved[ys + dy, xs + dx] = True
            sd = bench / "cases" / f"{d.name}-s"
            sd.mkdir(exist_ok=True)
            Image.fromarray(moved.astype(np.uint8) * 255).save(sd / "selection.png")
            write_json(sd / "case.json", {"photo": photo, "id": info["id"], "kind": "synthetic", "of": d.name,
                                          "shift": [dy, dx], "match": round(score, 1), "hints": []})
            view = outline(base.astype(np.uint8), moved)
            view = outline(view, m, (255, 210, 0))
            im = Image.fromarray(view)
            im.thumbnail((1200, 1200))
            im.save(sd / "placement.jpg", quality=85)
            n += 1
    say(f"{n} synthetic cases (placement.jpg in each shows where: magenta, its real case yellow)")


# ------------------------------------------------------------------------------------------------ run
def parse_models(spec):
    out = []
    for part in spec.split(","):
        m, __, k = part.strip().partition(":")
        if m:
            out.append((m, 1 if m == "lama" else int(k or 1)))
    return out


def git_state():
    try:
        rev = subprocess.run(["git", "-C", str(REPO), "describe", "--always", "--dirty"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        branch = subprocess.run(["git", "-C", str(REPO), "branch", "--show-current"], capture_output=True, text=True,
                                timeout=10).stdout.strip()
        return f"{branch} {rev}".strip()
    except (OSError, subprocess.SubprocessError):
        return None


def selected_cases(bench, patterns):
    cases = []
    for c in sorted((bench / "cases").glob("*/case.json")):
        if patterns and not any(fnmatch.fnmatch(c.parent.name, p) for p in patterns):
            continue
        cases.append((c.parent, read_json(c)))
    return cases


def run(args):
    bench = Path(args.bench)
    out = bench / "runs" / args.name
    out.mkdir(parents=True, exist_ok=True)
    install = find_install(args.install)
    A, cfg = load_app(install, out / "log.txt")
    models = parse_models(args.models)
    for m, __ in models:
        if m != "lama" and (m not in A.ENGINES or A.model_kind(m) != "remove"):
            sys.exit(f"{m}: not a removal model (models: lama, " + ", ".join(
                k for k in A.ENGINES if A.model_kind(k) == "remove") + ")")
        if not A.engines.available().get(m):
            sys.exit(f"{m} is not installed in {install}")
    rj = out / "run.json"
    state = read_json(rj) or {"name": args.name, "started": time.strftime("%Y-%m-%d %H:%M"), "results": {}}
    if state.get("seed", args.seed) != args.seed or state.get("prompt", args.prompt) != args.prompt:
        sys.exit(f"run {args.name} was made with seed {state.get('seed')} and prompt {state.get('prompt')!r}: "
                 "use another --name")
    state.update({"code": git_state(), "app_version": A.system.VERSION, "install": str(install),
                  "install_version": cfg.get("version"), "gpu": cfg.get("gpu"), "device": cfg.get("device"),
                  "models": args.models, "seed": args.seed, "prompt": args.prompt})
    write_json(rj, state)
    cases = selected_cases(bench, [p for p in (args.cases or "").split(",") if p])
    by_photo = {}
    for d, info in cases:
        by_photo.setdefault(info["photo"], []).append((d, info))
    say(f"run {args.name}: {len(cases)} cases on {len(by_photo)} photos, models {args.models}, code {state['code']}")

    held = {}  # the engine loaded, carried from one photo's session to the next
    t_run = time.time()
    for model, count in models:  # model by model: each loads once
        for photo, items in by_photo.items():
            todo = [(d, info) for d, info in items
                    if any(not (out / d.name / f"{label}.png").exists()
                           for label in labels(A, model, count))
                    or not (out / d.name / "before.png").exists()]
            if not todo:
                continue
            s = open_session(A, bench, bench / "photos" / photo, out / "work" / Path(photo).stem, args.seed)
            for attr, eng in held.items():
                setattr(s, attr, eng)
            try:
                for d, info in todo:
                    if user_app_running():
                        say("AI Remove is open: the bench stops to leave it the GPU (run it again to go on)")
                        state["stopped"] = time.strftime("%Y-%m-%d %H:%M")
                        write_json(rj, state)
                        return 3
                    one_case(A, s, d, info, model, count, out, state, args)
                    write_json(rj, state)
            finally:
                held = {a: getattr(s, a) for a in A.ENGINE_ATTRS.values() if getattr(s, a) is not None}
                s.close()
    state.pop("stopped", None)
    state["finished"] = time.strftime("%Y-%m-%d %H:%M")
    write_json(rj, state)
    say(f"run {args.name} done in {(time.time() - t_run) / 60:.0f} min: {out}")
    return 0


def labels(A, model, count):
    return ["LaMa"] if model == "lama" else [f"{A.MODELS[model]} {k}" for k in range(1, count + 1)]


def one_case(A, s, d, info, model, count, out, state, args):
    cd = out / d.name
    cd.mkdir(exist_ok=True)
    res = state["results"].setdefault(d.name, {})
    sel = np.asarray(Image.open(d / "selection.png").convert("L")) > 127
    bw, bh = s.base.size
    if sel.shape != (bh, bw):
        sel = np.asarray(Image.fromarray(sel.astype(np.uint8) * 255).resize((bw, bh), Image.NEAREST)) > 127
    s.next_id = info["id"]  # the removal's number seeds its variants: the same as in the project
    t0 = time.time()
    r = s.new_removal(sel, hints=info.get("hints"))
    try:
        hole = A.apply_t(r.reg_mask, s.t)
        before = upright(s, r, np.asarray(r.src))
        truth = before if info.get("kind") == "synthetic" else None
        if not (cd / "before.png").exists():
            save_png(before, cd / "before.png")
            save_png(outline(before, hole), cd / "before_marked.png")
            res["_area"] = {"box": list(r.box), "size": [int(before.shape[1]), int(before.shape[0])],
                            "render_s": round(time.time() - t0, 1)}
        kept = d / "kept.png"
        if info.get("kept") and kept.exists() and not (d / "kept_view.png").exists():
            im = Image.open(kept).convert("RGB")
            if im.size == r.src.size:  # the same area as then (else the app plans areas differently now)
                mi, al, __ = s.hole(r)
                save_png(upright(s, r, as_written(s, r, im, mi, al)), d / "kept_view.png")
        for k, label in enumerate(labels(A, model, count), 1):
            if (cd / f"{label}.png").exists():
                continue
            if model != "lama":
                r.counts[model] = k - 1  # its seed: the k-th variant's, whatever was made before
            t0 = time.time()
            try:
                label, im = s.run_lama(r) if model == "lama" else s.run_model(r, model, args.prompt or "")
            except Exception as e:  # a model that fails is noted, the bench goes on
                say(f"{d.name}: {label} failed: {e!r}")
                res[label] = {"error": repr(e)[:300]}
                A.engines._free_gpu()
                continue
            secs = time.time() - t0
            mi, al, __ = s.hole(r, label)
            view = upright(s, r, as_written(s, r, im, mi, al))
            save_png(view, cd / f"{label}.png")
            res[label] = {"seconds": round(secs, 1), **measure(view, hole, truth)}
            if model == "qwen" and getattr(s.qwen, "what", None):
                res[label]["qwen_saw"] = s.qwen.what
            say(f"{d.name}: {label} in {secs:.0f}s {res[label]}")
    finally:
        s.removals.remove(r)


# ------------------------------------------------------------------------------------------------ sheet
def thumb(src, dst):
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    im.thumbnail((THUMB, THUMB), Image.LANCZOS)
    im.save(dst, quality=86)


def sheet(args):
    bench = Path(args.bench)
    runs = [Path(p) for p in sorted((bench / "runs").glob("*/run.json"), key=lambda p: p.stat().st_mtime)]
    if args.runs:
        want = args.runs.split(",")
        runs = [bench / "runs" / n / "run.json" for n in want if (bench / "runs" / n / "run.json").exists()]
    runs = [(p.parent, read_json(p, {})) for p in runs]
    cases = selected_cases(bench, [p for p in (args.cases or "").split(",") if p])
    rel = lambda p: Path(os.path.relpath(p, bench)).as_posix()  # noqa: E731
    rows = []
    for d, info in cases:
        tiles = []
        first = next(((rd / d.name / "before.png") for rd, __ in runs if (rd / d.name / "before.png").exists()), None)
        if first is None:
            continue
        marked = first.with_name("before_marked.png")
        t = bench / "thumbs" / rel(marked)
        thumb(marked, t.with_suffix(".jpg"))
        tiles.append(("before", rel(first), rel(t.with_suffix(".jpg")), "the photo; magenta: the hole"))
        if (d / "kept_view.png").exists():
            t = bench / "thumbs" / rel(d / "kept_view.png")
            thumb(d / "kept_view.png", t.with_suffix(".jpg"))
            tiles.append((f"kept: {info.get('kept')}", rel(d / "kept_view.png"), rel(t.with_suffix(".jpg")),
                          "the variant kept then" + (" (picked)" if info.get("user_picked") else "")))
        for rd, rinfo in runs:
            res = (rinfo.get("results") or {}).get(d.name, {})
            for label, m in res.items():
                p = rd / d.name / f"{label}.png"
                if label.startswith("_") or not p.exists():
                    continue
                t = (bench / "thumbs" / rel(p)).with_suffix(".jpg")
                thumb(p, t)
                nums = " · ".join(f"{k} {v}" for k, v in m.items() if k in ("detail", "tone"))
                tiles.append((f"{rd.name}: {label}", rel(p), rel(t), f"{m.get('seconds', '?')} s · {nums}"
                              + (f" · saw: {m['qwen_saw']}" if m.get("qwen_saw") else "")))
        what = (f"synthetic: {info.get('of')}'s selection moved {info.get('shift')}"
                if info.get("kind") == "synthetic" else
                f"{info.get('photo')} removal {info.get('id')}" + (f" · {', '.join(info['hints'])}"
                                                                    if info.get("hints") else ""))
        rows.append((d.name, what, tiles))
    page = SHEET.replace("{{runs}}", html.escape(", ".join(
        f"{rd.name} ({ri.get('code')}, {ri.get('models')}, seed {ri.get('seed')}"
        + (f", prompt {ri.get('prompt')!r}" if ri.get("prompt") else "") + ")" for rd, ri in runs)))
    body = []
    for name, what, tiles in rows:
        cells = "".join(
            f'<figure><img loading="lazy" src="{html.escape(t)}" data-full="{html.escape(full)}" '
            f'data-label="{html.escape(name)} · {html.escape(lab)}"><figcaption><b>{html.escape(lab)}</b><br>'
            f'{html.escape(sub)}</figcaption></figure>' for lab, full, t, sub in tiles)
        body.append(f'<section><h2>{html.escape(name)} <small>{html.escape(what)}</small></h2>'
                    f'<div class="row">{cells}</div></section>')
    (bench / "sheet.html").write_text(page.replace("{{body}}", "\n".join(body)), encoding="utf-8")
    say(f"{bench / 'sheet.html'}: {len(rows)} cases, {sum(len(t) for __, __, t in rows)} pictures")


SHEET = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Remove bench</title>
<style>
:root { --bg:#f6f5f2; --fg:#1d1d1b; --muted:#6b6a66; --line:#dddbd5; --card:#fff; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe7; --muted:#9c9b96; --line:#33322f; --card:#1f1f1d; } }
body { background:var(--bg); color:var(--fg); font:14px/1.4 system-ui, sans-serif; margin:0; padding:16px 20px 60px; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:15px; margin:28px 0 8px; } small { color:var(--muted); font-weight:normal; }
p.runs, .help { color:var(--muted); margin:0 0 4px; }
.row { display:flex; gap:10px; overflow-x:auto; padding-bottom:6px; }
figure { margin:0; flex:0 0 auto; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:6px; }
figure img { display:block; height:230px; width:auto; cursor:zoom-in; border-radius:3px; }
figcaption { font-size:12px; color:var(--muted); max-width:300px; margin-top:4px; } figcaption b { color:var(--fg); font-weight:600; }
#view { position:fixed; inset:0; background:#000; display:none; overflow:auto; z-index:9; }
#view img { display:block; margin:auto; image-rendering:auto; }
#bar { position:fixed; left:0; right:0; top:0; background:rgba(0,0,0,.72); color:#fff; padding:6px 12px; font-size:13px; z-index:10; display:none; }
</style></head><body>
<h1>AI Remove bench</h1>
<p class="runs">Runs: {{runs}}</p>
<p class="help">Click a picture for 100 %. Then ← → flip through the case's pictures at the same spot, B shows the photo before, Esc closes.</p>
{{body}}
<div id="view"><img id="big" alt=""></div><div id="bar"></div>
<script>
const view = document.getElementById('view'), big = document.getElementById('big'), bar = document.getElementById('bar');
let row = [], idx = 0, back = null;
function show(i, keep) {
  const sx = view.scrollLeft, sy = view.scrollTop;
  idx = (i + row.length) % row.length;
  const im = row[idx];
  big.onload = () => { if (keep) { view.scrollLeft = sx; view.scrollTop = sy; } };
  big.src = im.dataset.full;
  bar.textContent = im.dataset.label + '   (' + (idx + 1) + '/' + row.length + ')';
  view.style.display = bar.style.display = 'block';
}
document.querySelectorAll('figure img').forEach(im => im.addEventListener('click', e => {
  row = [...im.closest('.row').querySelectorAll('img')];
  const x = e.offsetX / im.width, y = e.offsetY / im.height;
  show(row.indexOf(im), false);
  big.onload = () => { view.scrollLeft = x * big.naturalWidth - innerWidth / 2; view.scrollTop = y * big.naturalHeight - innerHeight / 2; };
}));
addEventListener('keydown', e => {
  if (view.style.display !== 'block') return;
  if (e.key === 'ArrowRight') { show(idx + 1, true); e.preventDefault(); }
  else if (e.key === 'ArrowLeft') { show(idx - 1, true); e.preventDefault(); }
  else if (e.key === 'b' || e.key === 'B') { if (back === null) { back = idx; show(0, true); } }
  else if (e.key === 'Escape') { view.style.display = bar.style.display = 'none'; }
});
addEventListener('keyup', e => { if ((e.key === 'b' || e.key === 'B') && back !== null) { show(back, true); back = null; } });
view.addEventListener('click', () => { view.style.display = bar.style.display = 'none'; });
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("bench")
    c.add_argument("sources", nargs="+")
    c.add_argument("--synthetic", action="store_true")
    c.add_argument("--install")
    r = sub.add_parser("run")
    r.add_argument("bench")
    r.add_argument("--name", required=True)
    r.add_argument("--models", default=DEFAULT_MODELS)
    r.add_argument("--cases", help="comma-separated globs on the cases' names, e.g. IMG_30*,*-s")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--prompt", default="")
    r.add_argument("--install")
    sh = sub.add_parser("sheet")
    sh.add_argument("bench")
    sh.add_argument("--runs")
    sh.add_argument("--cases")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    return {"collect": collect, "run": run, "sheet": sheet}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
