# Third-party notices

AI Remove's own code and icon are under the MIT licence ([LICENSE.txt](LICENSE.txt)).

**No model weights are included in this package.** The installer downloads them from their publishers, at the
user's choice, after showing each licence. Using a model means accepting its licence.

## Models

| Model | Source | Licence |
|---|---|---|
| LaMa (ONNX) | [Carve/LaMa-ONNX](https://huggingface.co/Carve/LaMa-ONNX), from [advimman/lama](https://github.com/advimman/lama) | Apache-2.0 |
| SAM 3 | [facebook/sam3](https://huggingface.co/facebook/sam3) (gated), or the copy LightCraft downloaded | [SAM License](https://github.com/facebookresearch/sam3/blob/main/LICENSE) (Meta): custom, not OSI; read it |
| SDXL Inpainting 0.1 | [diffusers/stable-diffusion-xl-1.0-inpainting-0.1](https://huggingface.co/diffusers/stable-diffusion-xl-1.0-inpainting-0.1) | CreativeML Open RAIL++-M (use-based restrictions) |
| SDXL VAE fp16 fix | [madebyollin/sdxl-vae-fp16-fix](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix) | MIT |
| FLUX.1 Fill [dev] | [black-forest-labs/FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev) (gated) | FLUX.1 [dev] Non-Commercial License: read what it allows for the model and for the images it makes |
| FLUX.1 Fill [dev] GGUF Q4_K_S | [YarvixPA/FLUX.1-Fill-dev-GGUF](https://huggingface.co/YarvixPA/FLUX.1-Fill-dev-GGUF) | as FLUX.1 [dev] |
| FLUX.1 Turbo-Alpha LoRA | [alimama-creative/FLUX.1-Turbo-Alpha](https://huggingface.co/alimama-creative/FLUX.1-Turbo-Alpha) | as FLUX.1 [dev] |
| OSOR (FLUX Fill, phase II) — optional | [QinmingZhou/OSOR](https://huggingface.co/QinmingZhou/OSOR), from [Zhouqm-Git/osor](https://github.com/Zhouqm-Git/osor) (ECCV 2026) | as FLUX.1 [dev] (non-commercial); OSOR's code is MIT, but AI Remove uses none of it: it loads the weights itself |
| ObjectClear — optional | [jixin0101/ObjectClear](https://huggingface.co/jixin0101/ObjectClear), from [zjx0101/ObjectClear](https://github.com/zjx0101/ObjectClear) (CVPR 2026) | [S-Lab License 1.0](https://github.com/zjx0101/ObjectClear/blob/main/LICENSE): non-commercial use only |
| Qwen-Image 2.1 Turbo — optional | [Qwen/Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) (configs, processor, VAE), from [QwenLM/Qwen-Image-2.1](https://github.com/QwenLM/Qwen-Image-2.1) | [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/LICENSE): research and evaluation only; commercial use needs a separate licence from Qwen |
| Qwen-Image 2.1 Turbo GGUF Q4_K_M — optional | [unsloth/Qwen-Image-2.1-Turbo-GGUF](https://huggingface.co/unsloth/Qwen-Image-2.1-Turbo-GGUF) | as Qwen-Image 2.1 |
| Qwen3-VL-8B-Instruct FP8 — optional, Qwen-Image's text encoder | [Qwen/Qwen3-VL-8B-Instruct-FP8](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-FP8) | Apache-2.0 |

Qwen-Image 2.1's text encoder is Qwen3-VL-8B-Instruct unchanged (checked tensor by tensor against Qwen's repository),
so AI Remove downloads Qwen's own FP8 release of it (10 GB) instead of the 17.5 GB bfloat16 copy in Qwen-Image's
repository.

ObjectClear's pipeline code is under the same S-Lab licence, so it is not part of AI Remove either: the installer
downloads it from GitHub (a fixed commit) into `models/objectclear/code` together with its weights, only when the user
chooses ObjectClear.

SAM 3 needs no configuration files from Meta: AI Remove uses Hugging Face Transformers' built-in defaults for the SAM 3
tracker. These give the same masks as the checkpoint's own configuration.

## Software installed into the private environment

| Software | Licence |
|---|---|
| Python (python-build-standalone, via [uv](https://github.com/astral-sh/uv)) | PSF; uv: Apache-2.0 / MIT |
| PyTorch, torchvision | BSD-3-Clause |
| AMD ROCm for Windows wheels (`rocm`, `rocm_sdk_*`), on AMD Windows PCs only | AMD's licences (see the packages) |
| Hugging Face diffusers, transformers, accelerate, peft, huggingface_hub, safetensors, tokenizers | Apache-2.0 |
| ONNX Runtime | MIT |
| NumPy, SciPy | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| tifffile | BSD-3-Clause |
| gguf | MIT |
| sentencepiece | Apache-2.0 |
| protobuf | BSD-3-Clause |

## LightCraft and ArtCraft

LightCraft is made by the ArtCraft team ([storytold/lightcraft](https://github.com/storytold/lightcraft), MIT OR
Apache-2.0). AI Remove is an independent plug-in. It talks to LightCraft through LightCraft's documented local control
channel and contains no LightCraft code.

AI Remove is not made, sponsored or endorsed by the ArtCraft team. It does not use the ArtCraft name or marks.

## The icon

The icon uses the same three-colour engraving style as the Crafting Apps icons, but it is not one of their marks. It
was made in three steps (details in `assets/icon/README.md`):

1. A portrait was generated on this machine with FLUX.1 Fill [dev] (GGUF), the Turbo-Alpha LoRA and the
   [Perfect Ink Drawing (Engraving Style)](https://civitai.com/models/1717646) LoRA by deep_synth (Flux v1.0).
   - Its author's permissions on Civitai allow commercial use of the images made with it and derivatives, with no
     credit required.
   - It was downloaded from a copy on Hugging Face,
     [Muapi/perfect-ink-drawing-engraving-style](https://huggingface.co/Muapi/perfect-ink-drawing-engraving-style),
     which is labelled openrail++. The original author's terms are the ones that apply.
   - FLUX.1 [dev]'s licence lets its outputs be used for any purpose, except training competing models. The
     portrait was used only for its tones.
2. AI Remove's own engraving algorithm drew the lines.
3. VectorCraft traced the result into vectors.

The icon is under the same MIT licence as the code.
