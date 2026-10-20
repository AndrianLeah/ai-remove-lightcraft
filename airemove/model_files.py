"""The AI models: what each one is for, its download and licence, the files it needs, and where they are.

A model is one or more parts, each a folder like the ones in the install's models/ (SDXL: the inpainting model and its
fp16 VAE; FLUX: its diffusers folder, the GGUF transformer and the Turbo LoRA). A part is in models/<part>, or in a
folder of the user's own — another AI Remove install, a Hugging Face cache, ComfyUI's models — that the installer
found it in and recorded in airemove.json ("model_paths": {part: folder}): used where it is, nothing downloaded or
copied, and an uninstall leaves it alone.

The app (engines.available and every model path), the installer and the MCP server use the same checks (part_ok):
a folder the installer accepts is one the app loads.

Standard library only: the installer and the MCP server import it too."""
import json
import os
import struct
from pathlib import Path

import system
from i18n import N_

FLUX_QUANTS = ("Q4_K_S", "Q5_K_S")  # first one present is used; Q4_K_S: ~1.4 GB less VRAM, so it does not spill
TURBO_WEIGHTS = "diffusion_pytorch_model.safetensors"  # alimama's FLUX.1-Turbo-Alpha LoRA
OSOR_WEIGHTS = "osor-fluxfill/weights/fluxfill_phase2.pth"
SAM3_WEIGHTS = "model.safetensors"


def _json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def tensor_names(p):
    """The tensor names in a .safetensors file (its JSON header only), [] if it is not one."""
    try:
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if not 0 < n < 100 * 2 ** 20:
                return []
            return [k for k in json.loads(f.read(n)) if k != "__metadata__"]
    except (OSError, ValueError, struct.error):
        return []


def _pipeline(name):
    """The folder is this diffusers pipeline (its model_index.json says so)."""
    return lambda d: _json(d / "model_index.json").get("_class_name") == name


def _fp16_vae(d):
    """SDXL's VAE fixed for half precision (madebyollin): the original overflows in fp16, so it asks for an upcast."""
    c = _json(d / "config.json")
    return c.get("_class_name") == "AutoencoderKL" and c.get("latent_channels") == 4 and c.get("force_upcast") is False


def _sam3(d):
    """SAM 3's weights (LightCraft's copy has no config.json): its detector's and its tracker's tensors."""
    roots = {n.split(".", 1)[0] for n in tensor_names(d / SAM3_WEIGHTS)}
    return {"detector_model", "tracker_model"} <= roots


class Part:
    """One folder of a model.
    name      its folder in models/, and its key in airemove.json's "model_paths"
    gb        download size (GB as the free-space check counts them: 2**30 bytes)
    need      files that must be there, relative to the folder; a tuple = any one of them
    repo, get the Hugging Face repo it comes from and the files taken from it (None: fetch_models makes it)
    check     f(folder) -> bool: what tells it from a look-alike (another pipeline, another VAE)
    anywhere  a folder of any name may hold it (its files or its check say what it is); else the folder has the part's
              name or its repo's, or is that repo in a Hugging Face cache (models--<org>--<repo>/snapshots/<rev>)
    optional  the app works without it (the installer still gets it)
    gated     a licence to accept on Hugging Face first: the download needs the user's token"""

    def __init__(self, name, gb, need, repo=None, get=(), check=None, anywhere=True, optional=False, gated=False):
        self.name, self.gb, self.need, self.repo, self.get = name, gb, need, repo, list(get)
        self.check, self.anywhere, self.optional, self.gated = check, anywhere, optional, gated


class Model:
    def __init__(self, name, what, licence, parts):
        self.name, self.what, self.licence, self.parts = name, what, licence, parts

    @property
    def gb(self):
        return round(sum(PARTS[p].gb for p in self.parts), 1)

    @property
    def gated(self):
        return next((PARTS[p].repo for p in self.parts if PARTS[p].gated), None)


SDXL_FILES = ["model_index.json", "scheduler/scheduler_config.json",
              "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
              "text_encoder_2/config.json", "text_encoder_2/model.fp16.safetensors",
              "tokenizer/*", "tokenizer_2/*", "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
              "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors"]
FLUX_FILES = ["model_index.json", "LICENSE.md", "scheduler/*", "text_encoder/*", "text_encoder_2/*", "tokenizer/*",
              "tokenizer_2/*", "transformer/config.json", "vae/*"]
OBJECTCLEAR_FILES = ["model_index.json", "scheduler/*", "tokenizer/*", "tokenizer_2/*", "*/config.json",
                     "*/model.fp16.safetensors", "*/diffusion_pytorch_model.fp16.safetensors"]
PARTS = {p.name: p for p in (
    Part("lama", 0.19, ["lama_fp32.onnx"], "Carve/LaMa-ONNX", ["lama_fp32.onnx"]),
    Part("sam3", 3.21, [SAM3_WEIGHTS], "facebook/sam3", [SAM3_WEIGHTS], check=_sam3, gated=True),
    Part("sdxl-inpaint", 6.47, ["model_index.json", "unet/diffusion_pytorch_model.fp16.safetensors",
                                "text_encoder/model.fp16.safetensors", "text_encoder_2/model.fp16.safetensors",
                                "vae/diffusion_pytorch_model.fp16.safetensors"],
         "diffusers/stable-diffusion-xl-1.0-inpainting-0.1", SDXL_FILES,
         check=_pipeline("StableDiffusionXLInpaintPipeline")),
    Part("sdxl-vae-fp16-fix", 0.31, ["config.json", "diffusion_pytorch_model.safetensors"],
         "madebyollin/sdxl-vae-fp16-fix", ["config.json", "diffusion_pytorch_model.safetensors"], check=_fp16_vae),
    # only the text encoders, the VAE and the transformer's config: the transformer itself is the GGUF
    Part("FLUX.1-Fill-dev", 9.42, ["model_index.json", "transformer/config.json", "text_encoder/model.safetensors",
                                   "text_encoder_2/model-00001-of-00002.safetensors",
                                   "text_encoder_2/model-00002-of-00002.safetensors",
                                   "vae/diffusion_pytorch_model.safetensors"],
         "black-forest-labs/FLUX.1-Fill-dev", FLUX_FILES, check=_pipeline("FluxFillPipeline"), gated=True),
    Part("gguf", 6.34, [tuple(f"flux1-fill-dev-{q}.gguf" for q in FLUX_QUANTS)], "YarvixPA/FLUX.1-Fill-dev-GGUF",
         [f"flux1-fill-dev-{FLUX_QUANTS[0]}.gguf"]),
    # a LoRA's file name says nothing: only a folder named like it
    Part("flux-turbo-alpha", 0.65, [TURBO_WEIGHTS], "alimama-creative/FLUX.1-Turbo-Alpha", [TURBO_WEIGHTS],
         anywhere=False, optional=True),
    Part("osor", 0.56, [OSOR_WEIGHTS], "QinmingZhou/OSOR", [OSOR_WEIGHTS, "README.md"]),
    Part("objectclear", 7.29, ["model_index.json"] + [f"{c}/model.fp16.safetensors" for c in
                                                     ("text_encoder", "text_encoder_2", "image_prompt_encoder",
                                                      "postfuse_module")]
         + ["unet/diffusion_pytorch_model.fp16.safetensors", "vae/diffusion_pytorch_model.fp16.safetensors"],
         "jixin0101/ObjectClear", OBJECTCLEAR_FILES, check=_pipeline("ObjectClearPipeline")),
    # its pipeline code, from GitHub (S-Lab licence: not shipped with AI Remove)
    Part("objectclear/code", 0.0, ["objectclear/pipelines/pipeline_objectclear.py"]),
)}
# the same words as the README's model table and the window's texts (ui.py show_model_info)
MODELS = {
    "lama": Model("LaMa", N_("Quick fill on the processor, one result in seconds: small and medium objects on plain "
                             "backgrounds (wall, sky, lawn, tarmac). The window always has it."),
                  "Apache-2.0", ["lama"]),
    "sam3": Model("SAM 3", N_("One-click selection: the same model as LightCraft's Object masks. Without it you "
                              "select with the brush."),
                  "SAM License (Meta)", ["sam3"]),
    "sdxl": Model("SDXL Inpainting", N_("Generative fill on the GPU, ~8–15 s per variant, each one different: medium "
                                        "areas with detail."),
                  "CreativeML Open RAIL++-M", ["sdxl-inpaint", "sdxl-vae-fp16-fix"]),
    "flux": Model("FLUX.1 Fill [dev] + Turbo", N_("The most realistic fill: it respects light, perspective and "
                                                  "architecture; for large or difficult areas. Needs a GPU with 12 GB "
                                                  "or more."),
                  "FLUX.1 [dev] Non-Commercial License", ["FLUX.1-Fill-dev", "gguf", "flux-turbo-alpha"]),
    "osor": Model("OSOR", N_("Removes an object together with its shadow and reflection, in one step (~3–8 s); it "
                             "also finds the shadow for \"Include the shadow\". Runs on FLUX."),
                  "FLUX.1 [dev] Non-Commercial License", ["osor"]),
    "objectclear": Model("ObjectClear", N_("Removes an object together with its shadow and reflection, ~5 s per "
                                           "variant, at 512 px (softer detail on large areas)."),
                         "S-Lab License 1.0 (non-commercial)", ["objectclear", "objectclear/code"]),
}


# ------------------------------------------------------------------------------------------------ where they are
def part_ok(part, folder):
    """The folder holds this part: its files, and what its check looks for."""
    if not folder:
        return False
    p, d = PARTS[part], Path(folder)
    for need in p.need:
        if not any((d / n).is_file() for n in (need if isinstance(need, tuple) else (need,))):
            return False
    return p.check is None or p.check(d)


def models_dir():
    """The install's own models folder."""
    return Path(system.config().get("models_dir") or system.ROOT / "models")


def recorded():
    """{part: folder}: the parts the installer found in the user's own folders (airemove.json "model_paths")."""
    paths = system.config().get("model_paths") or {}
    return {k: v for k, v in paths.items() if k in PARTS and isinstance(v, str) and v} if isinstance(paths, dict) else {}


def part_dir(part, models=None, paths=None):
    """Where the part is: the folder recorded for it while it holds it, else models/<part>."""
    paths = recorded() if paths is None else paths
    if paths.get(part) and part_ok(part, paths[part]):
        return Path(paths[part])
    return Path(models or models_dir()) / part


def has(model, models=None, paths=None, optional=False):
    """All the model's parts are there; with optional=True also the ones the app can do without (Turbo)."""
    paths = recorded() if paths is None else paths
    return all(part_ok(p, part_dir(p, models, paths)) for p in MODELS[model].parts if optional or not PARTS[p].optional)


# ------------------------------------------------------------------------------------------------ in the user's folder
SKIP = {"__pycache__", "node_modules", "site-packages", "venv", ".venv", "python", "blobs"}


def _named(part, d):
    p = PARTS[part]
    names = {p.name.lower()}
    if p.repo:
        org, __, repo = p.repo.lower().partition("/")
        names.add(repo)
        if d.parent.name == "snapshots" and d.parent.parent.name.lower() == f"models--{org}--{repo}":
            return True
    return d.name.lower() in names


def find(folder, parts, depth=6, limit=20000):
    """{part: the folder holding it} for the parts in folder or a few levels below it: the folder itself, another
    install (models/<part>), a Hugging Face cache (models--<org>--<repo>/snapshots/<rev>), ComfyUI (models/unet).
    Breadth first, at most `limit` folders, never twice into one folder through a link."""
    left, found, seen = list(parts), {}, set()
    level = [Path(folder)]
    for __ in range(depth + 1):
        deeper = []
        for d in level:
            real = os.path.normcase(os.path.realpath(d))
            if real in seen:
                continue
            seen.add(real)
            for part in list(left):
                if (PARTS[part].anywhere or _named(part, d)) and part_ok(part, d):
                    found[part] = d
                    left.remove(part)
            if not left or len(seen) >= limit:
                return found
            try:
                with os.scandir(d) as it:
                    subs = [e.name for e in it if e.is_dir() and e.name not in SKIP
                            and not (e.name.startswith(".") and e.name != ".cache")]
            except OSError:
                continue
            deeper += [d / s for s in sorted(subs, key=str.lower)]
        level = deeper
    return found


def find_model(model, folder):
    """{part: folder} for the model's parts in the user's folder: all of it, or at least one of its big parts (FLUX's
    GGUF in ComfyUI); the rest is downloaded. {} when it does not hold the model (SDXL's small VAE alone is not
    SDXL)."""
    found = find(folder, MODELS[model].parts)
    whole = all(p in found for p in MODELS[model].parts if not PARTS[p].optional and PARTS[p].gb > 0)
    return found if whole or any(PARTS[p].gb >= 1 for p in found) else {}


def looks_for(model):
    """For a message: one file of each needed part, as the install's models/ folder has it."""
    out = []
    for p in MODELS[model].parts:
        if not PARTS[p].optional and PARTS[p].gb > 0:
            need = PARTS[p].need[0]
            out.append(f"{p}/{need[0] if isinstance(need, tuple) else need}")
    return ", ".join(out)
