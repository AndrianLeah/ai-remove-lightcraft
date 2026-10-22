"""The AI Remove project of a photo: ONE file next to the raw (<raw name>.airemove, a zip) with every removal — its
selection, its area, all its variants and the chosen one. The raw itself is never modified; the DNG that LightCraft
shows (<stem>-AIRemove.dng) is rebuilt from the project on every save, always into the same file, so a removal can
be regenerated, changed or deleted later without creating a new photo each time.

Layout of the zip: project.json, r<id>/selection.png (1-bit, base.png frame), r<id>/area.png (1-bit, area frame),
r<id>/NN.png (each variant, render space of the area), r<id>/NN_hole.png (1-bit, area frame: only for a variant
that also removed the object's shadow — OSOR, ObjectClear — whose hole is larger than area.png).
A reflection removal ("Remove reflections", often the whole photo) has r<id>/light.npz instead of its variants'
pictures: the reflection's light as the model found it (Removal.light) — a few MB instead of tens per picture — and
in project.json its strength, how much of that light is taken away.
"""
import io
import json
import os
import time
import zipfile

import numpy as np
from PIL import Image

VERSION = 1


def path_for(raw_path):
    return raw_path.with_name(raw_path.name + ".airemove")


def photo_for(project_path):
    """The photo a project belongs to (path_for's inverse): IMG_1.CR2.airemove -> IMG_1.CR2."""
    return project_path.with_name(project_path.name[:-len(".airemove")])


def png(im, mode=None):
    buf = io.BytesIO()
    (im.convert(mode) if mode else im).save(buf, "PNG", compress_level=1)
    return buf.getvalue()


def mask_png(m):
    return png(Image.fromarray(m.astype(np.uint8) * 255), "1")


def _variant_bytes(r, label, im):
    b = r.png.get(label)
    if b is None:
        b = r.png[label] = png(im)
    return b


def save(s):
    """Write the session's project (all live removals) next to the raw; atomic (temp file + replace)."""
    p = path_for(s.src_path)
    meta = {"app": "AI Remove", "version": VERSION,
            "raw": {"name": s.src_path.name, "size": s.src_path.stat().st_size},
            "base_size": list(s.base.size), "orientation": [int(s.t[0]), bool(s.t[1])],
            "dng": {"path": str(s.dng_path) if s.dng_path else None, "id": s.dng_id},
            "next_id": s.next_id, "saved": time.strftime("%Y-%m-%d %H:%M:%S"), "removals": []}
    files = {}
    for r in list(s.removals):
        if r.deleted:
            continue
        cands = list(r.candidates)
        e = {"id": r.id, "box": [int(v) for v in r.box], "gain": r.gain, "chosen": r.chosen, "user_picked": r.user_picked,
             "counts": dict(r.counts), "variants": []}
        if r.hints:  # what Describe found in it, for Qwen-Image's namer
            e["hints"] = list(r.hints)
        if "selection" not in r.png:
            r.png["selection"] = mask_png(r.mask_e)
            r.png["area"] = mask_png(r.reg_mask)
        files[f"r{r.id}/selection.png"] = r.png["selection"]
        files[f"r{r.id}/area.png"] = r.png["area"]
        if r.light is not None:  # a reflection removal: its light, its variants rebuilt from it
            if "light" not in r.png:
                buf = io.BytesIO()
                np.savez_compressed(buf, light=r.light)
                r.png["light"] = buf.getvalue()
            e["reflection"] = f"r{r.id}/light.npz"
            e["strength"] = r.strength  # how much of it is taken away (the window's slider)
            files[e["reflection"]] = r.png["light"]
            e["variants"] = [{"label": label} for label, __ in cands]
            meta["removals"].append(e)
            continue
        for i, (label, im) in enumerate(cands):
            name = f"r{r.id}/{i:02d}.png"
            files[name] = _variant_bytes(r, label, im)
            v = {"label": label, "file": name}
            hole = r.holes.get(label)
            if hole is not None:
                v["hole"] = f"r{r.id}/{i:02d}_hole.png"
                files[v["hole"]] = r.png.setdefault(label + "#hole", mask_png(hole))
            e["variants"].append(v)
        meta["removals"].append(e)
    tmp = p.with_name(p.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:  # PNGs are compressed already
        z.writestr("project.json", json.dumps(meta, indent=1))
        for name, data in files.items():
            z.writestr(name, data)
    os.replace(tmp, p)
    return p


def load(raw_path, log=print):
    """(meta, [(entry, selection, area, [(label, PIL image, png bytes, hole or None)], light)]) or None if there is no
    usable project. light: a reflection removal's (its variants' picture and bytes are None: the session rebuilds
    them), else None."""
    p = path_for(raw_path)
    if not p.exists():
        return None
    try:
        with zipfile.ZipFile(p) as z:
            meta = json.loads(z.read("project.json"))
            if meta.get("raw", {}).get("name") != raw_path.name or meta["raw"].get("size") != raw_path.stat().st_size:
                log(f"project {p.name} belongs to another file: ignored")
                return None
            out = []
            for e in meta["removals"]:
                sel = np.asarray(Image.open(io.BytesIO(z.read(f"r{e['id']}/selection.png"))).convert("L")) > 127
                area = np.asarray(Image.open(io.BytesIO(z.read(f"r{e['id']}/area.png"))).convert("L")) > 127
                light = None
                if e.get("reflection"):
                    with np.load(io.BytesIO(z.read(e["reflection"]))) as f:
                        light = f["light"]
                vs = []
                for v in e["variants"]:
                    if light is not None:
                        vs.append((v["label"], None, None, None))
                        continue
                    b = z.read(v["file"])
                    hole = (np.asarray(Image.open(io.BytesIO(z.read(v["hole"]))).convert("L")) > 127
                            if v.get("hole") else None)
                    vs.append((v["label"], Image.open(io.BytesIO(b)).convert("RGB"), b, hole))
                out.append((e, sel, area, vs, light))
        return meta, out
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as err:
        log(f"project {p.name} unreadable ({type(err).__name__}): ignored")
        return None
