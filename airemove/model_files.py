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
QWEN_QUANTS = ("Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0")  # Qwen-Image's transformer: the first one present is used
QWEN_GGUF = "qwen-image-2.1-turbo-{}.gguf"
TURBO_WEIGHTS = "diffusion_pytorch_model.safetensors"  # alimama's FLUX.1-Turbo-Alpha LoRA
OSOR_WEIGHTS = "osor-fluxfill/weights/fluxfill_phase2.pth"
SAM3_WEIGHTS = "model.safetensors"
# "Remove reflections": the share of the reflection's light DAI found that each variant takes away, in this order. DAI
# takes away more than Lightroom: 1.4 times as much on a statue behind a shop window (Lightroom's own result, from its
# .acr sidecar); at 75 % it came closest, there and over the whole photo
REFLECTION_STRENGTHS = (0.75, 1.0, 0.5, 1.25)


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


def _sdxl_inpaint_unet(d):
    """An SDXL Inpainting UNet (RORem's: its folder's name, not this, tells it from SDXL's own)."""
    c = _json(d / "unet" / "config.json")
    return (c.get("_class_name") == "UNet2DConditionModel" and c.get("in_channels") == 9
            and c.get("cross_attention_dim") == 2048)


def _qwen_turbo(d):
    """Qwen-Image-2.1-Turbo's diffusers folder: its 8-step schedule is in model_index.json (the base model has none)."""
    i = _json(d / "model_index.json")
    return i.get("_class_name") == "QwenImage21Pipeline" and bool(i.get("sample_sigmas"))


def _qwen3_vl_fp8(d):
    """Qwen's FP8 release of Qwen3-VL-8B-Instruct: Qwen-Image-2.1's text encoder is that model, unchanged."""
    c = _json(d / "config.json")
    return ("Qwen3VLForConditionalGeneration" in (c.get("architectures") or [])
            and (c.get("quantization_config") or {}).get("quant_method") == "fp8"
            and (c.get("text_config") or {}).get("hidden_size") == 4096)


def _dai(d):
    """DAI's folder (Dereflection Any Image): its pipeline, as its model_index.json says, with its second decoder."""
    return _json(d / "model_index.json").get("_class_name") == "DAIPipeline"


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
    """offered=False: not a choice of its own in the installer (SDXL: RORem brings its files)."""

    def __init__(self, name, what, licence, parts, offered=True):
        self.name, self.what, self.licence, self.parts, self.offered = name, what, licence, parts, offered

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
    # RORem: only its UNet (its text encoders and VAE are SDXL Inpainting's, unchanged); its config looks like SDXL's,
    # so only a folder named like it
    Part("rorem", 4.78, ["unet/config.json", "unet/diffusion_pytorch_model.safetensors"], "LetsThink/RORem",
         ["unet/config.json", "unet/diffusion_pytorch_model.safetensors"], check=_sdxl_inpaint_unet, anywhere=False),
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
    # Qwen-Image 2.1 Turbo: the configs, processor and VAE (the transformer is the GGUF, the text encoder Qwen's own
    # FP8 Qwen3-VL — byte for byte the bf16 one inside Qwen-Image's repo, at 10 GB instead of 17.5)
    Part("qwen-image-2.1-turbo", 0.64, ["model_index.json", "processor/tokenizer.json", "transformer/config.json",
                                        "vae/diffusion_pytorch_model.safetensors"],
         "Qwen/Qwen-Image-2.1-Turbo", ["model_index.json", "LICENSE", "scheduler/*", "processor/*", "vae/*",
                                       "transformer/config.json"], check=_qwen_turbo),
    Part("qwen-image-2.1-turbo-gguf", 3.91, [tuple(QWEN_GGUF.format(q) for q in QWEN_QUANTS)],
         "unsloth/Qwen-Image-2.1-Turbo-GGUF", [QWEN_GGUF.format(QWEN_QUANTS[0])]),
    Part("qwen3-vl-8b-fp8", 9.88, ["config.json", "model.safetensors.index.json", "model-00001-of-00002.safetensors",
                                   "model-00002-of-00002.safetensors"],
         "Qwen/Qwen3-VL-8B-Instruct-FP8", ["*.json", "*.safetensors", "*.txt"], check=_qwen3_vl_fp8),
    # DAI: its UNet and ControlNet as released (fp32, there is no fp16 copy), the VAE and the text encoder in fp16, and
    # vae_2, its decoder with skip connections
    Part("dai", 5.69, ["model_index.json", "unet/diffusion_pytorch_model.safetensors",
                       "controlnet/diffusion_pytorch_model.safetensors", "vae/diffusion_pytorch_model.fp16.safetensors",
                       "vae_2/diffusion_pytorch_model.safetensors", "text_encoder/model.fp16.safetensors",
                       "tokenizer/vocab.json"],
         "sjtu-deepvision/dereflection-any-image-v0",
         ["model_index.json", "unet/*", "controlnet/*", "vae/config.json",
          "vae/diffusion_pytorch_model.fp16.safetensors", "vae_2/*", "text_encoder/config.json",
          "text_encoder/model.fp16.safetensors", "tokenizer/*", "scheduler/*"],
         check=_dai),
)}
# the same words as the README's model table and the window's texts (ui.py show_model_info)
MODELS = {
    "lama": Model("LaMa", N_("Quick fill on the processor, one result in seconds: small and medium objects on plain "
                             "backgrounds (wall, sky, lawn, tarmac). The window always has it."),
                  "Apache-2.0", ["lama"]),
    "sam3": Model("SAM 3", N_("One-click selection: the same model as LightCraft's Object masks. Without it you "
                              "select with the brush."),
                  "SAM License (Meta)", ["sam3"]),
    # no longer in the window's menu: RORem runs on its files (and "Full detail" without FLUX)
    "sdxl": Model("SDXL Inpainting", N_("Generative fill on the GPU, ~8–15 s per variant, each one different: medium "
                                        "areas with detail."),
                  "CreativeML Open RAIL++-M", ["sdxl-inpaint", "sdxl-vae-fp16-fix"], offered=False),
    "rorem": Model("RORem", N_("Removes people and objects without drawing anyone back: SDXL Inpainting retrained "
                               "only to remove (SDXL's files come with it). ~7 s per variant on a GPU."),
                   "Apache-2.0; on SDXL Inpainting (CreativeML Open RAIL++-M)",
                   ["sdxl-inpaint", "sdxl-vae-fp16-fix", "rorem"]),
    "flux": Model("FLUX.1 Fill [dev] + Turbo", N_("The most realistic fill: it respects light, perspective and "
                                                  "architecture; for large or difficult areas. Needs a GPU with 12 GB "
                                                  "or more."),
                  "FLUX.1 [dev] Non-Commercial License", ["FLUX.1-Fill-dev", "gguf", "flux-turbo-alpha"]),
    "osor": Model("OSOR", N_("Finds the shadows and reflections next to what you select, for \"Include the "
                             "shadow\" (with SAM 3). Runs on FLUX."),
                  "FLUX.1 [dev] Non-Commercial License", ["osor"]),
    "qwen": Model("Qwen-Image 2.1 Turbo", N_("Removes what you select by name: it recognises the object and redraws "
                                             "the scene behind it, at 1024 px. For large areas on complex "
                                             "backgrounds (a person in front of steps, a pole across columns). Needs "
                                             "a GPU with 16 GB or more; ~30 s per variant."),
                  "Qwen Research License (non-commercial); Qwen3-VL: Apache-2.0",
                  ["qwen-image-2.1-turbo", "qwen-image-2.1-turbo-gguf", "qwen3-vl-8b-fp8"]),
    "dai": Model("DAI (reflections)", N_("Removes reflections in glass — a shop window, a display case, a car "
                                         "window: \"Remove reflections\" takes away the light the glass reflects, "
                                         "over the whole photo or the selection, and keeps every detail. A few "
                                         "seconds on a GPU."),
                 "Apache-2.0, on Stable Diffusion 2's CreativeML Open RAIL++-M", ["dai"]),
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
