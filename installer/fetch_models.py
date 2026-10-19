"""Download AI Remove's models from Hugging Face into <install>/models — or link them from another install
(--from) or, for SAM 3, from LightCraft's own copy. Runs in the install's Python (needs huggingface_hub).
Prints one line per model for the installer: MODEL_OK <name> | MODEL_FAIL <name> <why>.

  fetch_models.py --dest DIR --models lama,sam3,sdxl,flux [--from OTHER_MODELS_DIR]   (HF_TOKEN for gated ones)
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "airemove"))
import system  # noqa: E402
from i18n import _, N_  # noqa: E402

SDXL_FILES = ["model_index.json", "scheduler/scheduler_config.json",
              "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
              "text_encoder_2/config.json", "text_encoder_2/model.fp16.safetensors",
              "tokenizer/*", "tokenizer_2/*", "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
              "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors"]
FLUX_FILES = ["model_index.json", "LICENSE.md", "scheduler/*", "text_encoder/*", "text_encoder_2/*", "tokenizer/*",
              "tokenizer_2/*", "transformer/config.json", "vae/*"]
# model: [(repo, files, sub-folder of models/)], and the file that says it is complete
SPECS = {
    "lama": ([("Carve/LaMa-ONNX", ["lama_fp32.onnx"], "lama")], "lama/lama_fp32.onnx"),
    "sam3": ([("facebook/sam3", ["model.safetensors"], "sam3")], "sam3/model.safetensors"),
    "sdxl": ([("diffusers/stable-diffusion-xl-1.0-inpainting-0.1", SDXL_FILES, "sdxl-inpaint"),
              ("madebyollin/sdxl-vae-fp16-fix", ["config.json", "diffusion_pytorch_model.safetensors"],
               "sdxl-vae-fp16-fix")], "sdxl-inpaint/unet/diffusion_pytorch_model.fp16.safetensors"),
    "flux": ([("black-forest-labs/FLUX.1-Fill-dev", FLUX_FILES, "FLUX.1-Fill-dev"),
              ("YarvixPA/FLUX.1-Fill-dev-GGUF", ["flux1-fill-dev-Q4_K_S.gguf"], "gguf"),
              ("alimama-creative/FLUX.1-Turbo-Alpha", ["diffusion_pytorch_model.safetensors"], "flux-turbo-alpha")],
             "gguf/flux1-fill-dev-Q4_K_S.gguf"),
}
GATED_HELP = {
    "sam3": N_("accept the SAM License at https://huggingface.co/facebook/sam3 (approval can take a while)"),
    "flux": N_("accept the licence at https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev"),
}


def complete(dest, model):
    """All of the model is there (the key file of each of its parts)."""
    parts, key = SPECS[model]
    if not (dest / key).exists():
        return False
    return all((dest / sub).is_dir() and any((dest / sub).iterdir()) for __, ___, sub in parts)


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
    lc = system.lightcraft_sam3_dir() / "model.safetensors"
    if lc.exists():
        how = system.link_or_copy(lc, dest / "sam3" / "model.safetensors")
        print("  " + (_("SAM 3: using the model LightCraft already downloaded (linked)") if how != "copy" else
                      _("SAM 3: using the model LightCraft already downloaded (copied)")))
        return True
    return False


def sam3_to_lightcraft(dest, token):
    """LightCraft's Object masks use the same model: give LightCraft our copy if it has none (with its two
    tokenizer files)."""
    lcd = system.lightcraft_sam3_dir()
    if (lcd / "model.safetensors").exists():
        return
    try:
        from huggingface_hub import hf_hub_download
        for f in ("vocab.json", "merges.txt"):
            hf_hub_download("facebook/sam3", f, local_dir=str(lcd), token=token)
        system.link_or_copy(dest / "sam3" / "model.safetensors", lcd / "model.safetensors")
        print("  " + _("SAM 3 given to LightCraft too ({dir}): its Object masks work now", dir=lcd))
    except Exception as e:  # nice to have only
        print("  " + _("(SAM 3 not shared with LightCraft: {error})", error=type(e).__name__))


def fetch(dest, model, token, other):
    if complete(dest, model):
        print("  " + _("{model}: already there", model=model))
        return
    if other and complete(other, model):
        n = sum(link_tree(other / sub, dest / sub) for __, ___, sub in SPECS[model][0])
        print("  " + _("{model}: taken from {dir} ({n} files linked)", model=model, dir=other, n=n))
        return
    if model == "sam3" and sam3_from_lightcraft(dest):
        return
    from huggingface_hub import snapshot_download
    for repo, files, sub in SPECS[model][0]:
        print("  " + _("{model}: downloading {repo} …", model=model, repo=repo), flush=True)
        snapshot_download(repo, allow_patterns=files, local_dir=str(dest / sub), token=token or None)
    if model == "sam3":
        sam3_to_lightcraft(dest, token)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--models", required=True)
    ap.add_argument("--from", dest="other")
    a = ap.parse_args()
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    other = Path(a.other) if a.other else None
    token = os.environ.get("HF_TOKEN") or None
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    for model in [m for m in a.models.split(",") if m in SPECS]:
        try:
            fetch(dest, model, token, other)
            print(f"MODEL_OK {model}", flush=True)
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
            if model in GATED_HELP and any(k in msg for k in ("401", "403", "Gated", "gated", "Unauthorized")):
                msg = _("access denied: {what}, then run the installation again with the token",
                        what=_(GATED_HELP[model]))
            print(f"MODEL_FAIL {model} {msg}", flush=True)


if __name__ == "__main__":
    main()
