"""Download AI Remove's models from Hugging Face into <install>/models — or link them from another install
(--from) or, for SAM 3, from LightCraft's own copy. A part the user already has in a folder of their own (--paths:
the installer found it there and records it in airemove.json) stays where it is: nothing is downloaded for it.
Runs in the install's Python (needs huggingface_hub). Prints one line per model for the installer:
MODEL_OK <name> | MODEL_FAIL <name> <why>.

  fetch_models.py --dest DIR --models lama,sam3,sdxl,flux,osor,objectclear [--from OTHER_MODELS_DIR]
                  [--paths '{"part": "folder", ...}']    (HF_TOKEN for gated ones)
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "airemove"))
import model_files as mf  # noqa: E402
import system  # noqa: E402
from i18n import _, N_  # noqa: E402

# ObjectClear's pipeline code (S-Lab License 1.0, non-commercial: fetched here, not shipped with AI Remove), pinned
OBJECTCLEAR_CODE = "https://codeload.github.com/zjx0101/ObjectClear/zip/c052d91ecd8772744a5ab97527441c813ab83009"
GATED_HELP = {
    "sam3": N_("accept the SAM License at https://huggingface.co/facebook/sam3 (approval can take a while)"),
    "flux": N_("accept the licence at https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev"),
}


def complete(dest, model, paths=None):
    """All of the model is there (in dest, or in the user's folders in paths), Turbo included."""
    return mf.has(model, dest, paths or {}, optional=True)


def link_tree(src, dst):
    """dst gets every file of src (hard links when possible: no extra disk space)."""
    n = 0
    for f in src.rglob("*"):
        if f.is_file() and ".cache" not in f.parts:
            t = dst / f.relative_to(src)
            if not t.exists():
                system.link_or_copy(f, t)
                n += 1
    return n


def sam3_from_lightcraft(dest):
    lc = system.lightcraft_sam3_dir() / mf.SAM3_WEIGHTS
    if lc.exists():
        how = system.link_or_copy(lc, dest / "sam3" / mf.SAM3_WEIGHTS)
        print("  " + (_("SAM 3: using the model LightCraft already downloaded (linked)") if how != "copy" else
                      _("SAM 3: using the model LightCraft already downloaded (copied)")))
        return True
    return False


def sam3_to_lightcraft(sam3, token):
    """LightCraft's Object masks use the same model: give LightCraft our copy if it has none (with its two
    tokenizer files)."""
    lcd = system.lightcraft_sam3_dir()
    if (lcd / mf.SAM3_WEIGHTS).exists():
        return
    try:
        from huggingface_hub import hf_hub_download
        for f in ("vocab.json", "merges.txt"):
            hf_hub_download("facebook/sam3", f, local_dir=str(lcd), token=token)
        system.link_or_copy(sam3 / mf.SAM3_WEIGHTS, lcd / mf.SAM3_WEIGHTS)
        print("  " + _("SAM 3 given to LightCraft too ({dir}): its Object masks work now", dir=lcd))
    except Exception as e:  # nice to have only
        print("  " + _("(SAM 3 not shared with LightCraft: {error})", error=type(e).__name__))


def objectclear_code(code):
    """ObjectClear's package (objectclear/: models, pipelines, utils — not its training dataset code) and its
    licence, from the pinned commit, into code (models/objectclear/code)."""
    with urllib.request.urlopen(OBJECTCLEAR_CODE, timeout=120) as resp:
        z = zipfile.ZipFile(io.BytesIO(resp.read()))
    for name in z.namelist():
        rel = name.split("/", 1)[1] if "/" in name else ""
        keep = rel == "LICENSE" or (rel.startswith("objectclear/") and not rel.startswith("objectclear/dataset/"))
        if not keep or name.endswith("/") or ".." in rel:
            continue
        t = code / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(z.read(name))


def fetch(dest, model, token, other, paths):
    if complete(dest, model, paths):
        mine = [p for p in mf.MODELS[model].parts if mf.part_dir(p, dest, paths) != dest / p]
        print("  " + (_("{model}: used from your folder, nothing downloaded", model=model) if mine else
                      _("{model}: already there", model=model)))
        return
    for part in mf.MODELS[model].parts:
        spec = mf.PARTS[part]
        where = mf.part_dir(part, dest, paths)
        if mf.part_ok(part, where):
            if where != dest / part:
                print("  " + _("{model}: {part} used from your folder {dir}", model=model, part=part, dir=where))
            continue
        if other and mf.part_ok(part, other / part):
            n = link_tree(other / part, dest / part)
            print("  " + _("{model}: {part} taken from {dir} ({n} files linked)", model=model, part=part, dir=other,
                           n=n))
            continue
        if part == "sam3" and sam3_from_lightcraft(dest):
            continue
        if part == "objectclear/code":  # from GitHub, pinned (S-Lab licence: not shipped with AI Remove)
            print("  " + _("{model}: downloading its code from GitHub …", model=model), flush=True)
            objectclear_code(dest / part)
            continue
        from huggingface_hub import snapshot_download
        print("  " + _("{model}: downloading {repo} …", model=model, repo=spec.repo), flush=True)
        snapshot_download(spec.repo, allow_patterns=spec.get, local_dir=str(dest / part), token=token or None)
        if part == "sam3":
            sam3_to_lightcraft(dest / part, token)
    missing = [p for p in mf.MODELS[model].parts if not mf.part_ok(p, mf.part_dir(p, dest, paths))]
    if missing:
        raise RuntimeError(_("incomplete after the download: {parts}", parts=", ".join(missing)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--models", required=True)
    ap.add_argument("--from", dest="other")
    ap.add_argument("--paths", default="{}", help="JSON {part: folder}: parts in the user's own folders")
    a = ap.parse_args()
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    other = Path(a.other) if a.other else None
    paths = {k: v for k, v in json.loads(a.paths).items() if k in mf.PARTS}
    token = os.environ.get("HF_TOKEN") or None
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    for model in [m for m in a.models.split(",") if m in mf.MODELS]:
        try:
            fetch(dest, model, token, other, paths)
            print(f"MODEL_OK {model}", flush=True)
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
            if model in GATED_HELP and any(k in msg for k in ("401", "403", "Gated", "gated", "Unauthorized")):
                msg = _("access denied: {what}, then run the installation again with the token",
                        what=_(GATED_HELP[model]))
            print(f"MODEL_FAIL {model} {msg}", flush=True)


if __name__ == "__main__":
    main()
