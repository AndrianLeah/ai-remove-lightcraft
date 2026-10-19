"""Engines for AI Remove: SAM 3 (selection), LaMa (ONNX, processor), SDXL Inpainting and FLUX.1 Fill (diffusers).

The accelerator is whatever PyTorch finds: NVIDIA (CUDA), AMD (ROCm, reported by torch as "cuda"), Intel Arc (xpu),
Apple Silicon (mps) — else the processor, where only LaMa is practical. On a 16 GB card SDXL and FLUX don't fit
together: the session unloads one before loading the other."""
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

import system
from i18n import _

ROOT = system.ROOT
MODELS = Path(system.config().get("models_dir") or ROOT / "models")
USE_MASK_PROMPT = True  # refine SAM objects with their previous mask as a prompt (see SAM3.refine)
DEFAULT_PROMPT = "empty background, seamless continuation of the surrounding scene, photograph, natural light"
NEGATIVE = ("person, people, human, man, woman, child, figure, statue, animal, text, watermark, logo, "
            "blurry, deformed, painting, illustration")
FLUX_QUANTS = ("Q4_K_S", "Q5_K_S")  # first one present is used; Q4_K_S: ~1.4 GB less VRAM, so it does not spill
FLUX_SIZES, FLUX_STEPS, FLUX_TURBO_STEPS = (512, 768), 16, 8
FLUX_LORA = MODELS / "flux-turbo-alpha" / "diffusion_pytorch_model.safetensors"  # alimama Turbo-Alpha
SAM3_WEIGHTS = "model.safetensors"

_DEVICE = None


def _gpu_env():
    # AMD (ROCm): the experimental fast attention kernels (flash / memory-efficient attention)
    os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")
    # Apple: an op MPS lacks runs on the processor instead of failing
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def device():
    """'cuda' (NVIDIA or AMD) | 'xpu' | 'mps' | 'cpu' — AIREMOVE_DEVICE forces one."""
    global _DEVICE
    if _DEVICE is None:
        _gpu_env()
        forced = os.environ.get("AIREMOVE_DEVICE")
        if forced:
            _DEVICE = forced
        else:
            try:
                _DEVICE = system.gpu_summary()[0]
            except Exception:
                _DEVICE = "cpu"
    return _DEVICE


def _free_gpu():
    import gc
    import torch
    gc.collect()
    dev = device()
    if dev == "cuda":
        torch.cuda.empty_cache()
    elif dev == "mps":
        torch.mps.empty_cache()
    elif dev == "xpu":
        torch.xpu.empty_cache()


# ------------------------------------------------------------------------------------------------ what is installed
def sam3_dir():
    """models/sam3 with the SAM 3 weights: the same file LightCraft downloaded for its Object masks, linked (no
    second 3.4 GB copy) when it is there. No config files are needed: transformers' defaults for the SAM 3 tracker
    are this checkpoint's (checked: identical masks)."""
    d = MODELS / "sam3"
    w = d / SAM3_WEIGHTS
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not w.exists():
            lc = system.lightcraft_sam3_dir() / SAM3_WEIGHTS
            if lc.exists():
                system.link_or_copy(lc, w)
    except OSError:
        pass
    return d


def available():
    """Which models are on disk."""
    m = MODELS
    return {
        "sam3": (sam3_dir() / SAM3_WEIGHTS).exists(),
        "lama": (m / "lama" / "lama_fp32.onnx").exists(),
        "sdxl": (m / "sdxl-inpaint" / "model_index.json").exists() and (m / "sdxl-vae-fp16-fix" / "config.json").exists(),
        "flux": (m / "FLUX.1-Fill-dev" / "model_index.json").exists()
        and any((m / "gguf" / f"flux1-fill-dev-{q}.gguf").exists() for q in FLUX_QUANTS),
    }


def usable(model, dev=None):
    """Installed and sensible on this machine: FLUX needs a GPU; SDXL works on the processor but takes minutes."""
    dev = dev or device()
    if not available().get(model):
        return False
    return model != "flux" or dev != "cpu"


# ------------------------------------------------------------------------------------------------ LaMa
def lama(src: Image.Image, mask: Image.Image) -> Image.Image:
    import onnxruntime as ort
    sess = ort.InferenceSession(str(MODELS / "lama" / "lama_fp32.onnx"), providers=["CPUExecutionProvider"])
    img = np.asarray(src.resize((512, 512), Image.LANCZOS)).astype(np.float32) / 255.0
    mk = (np.asarray(mask.resize((512, 512), Image.NEAREST)) > 127).astype(np.float32)
    out = sess.run(None, {"image": (img * (1 - mk[..., None])).transpose(2, 0, 1)[None], "mask": mk[None, None]})[0][0]
    out = out.transpose(1, 2, 0)
    if out.max() <= 2:
        out = out * 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).resize(src.size, Image.LANCZOS)


# ------------------------------------------------------------------------------------------------ SAM 3
class SAM3:
    """Click-to-select with SAM 3 (the tracker half: point prompts), using the same weights LightCraft downloaded.
    On a GPU ~0.25 s per photo and ~0.05 s per click — LightCraft's own Object tool runs a ~35 s detail pass after
    every click."""

    def __init__(self, log=print):
        dev = device()
        import torch
        from transformers import Sam3ImageProcessor, Sam3TrackerConfig, Sam3TrackerModel, Sam3TrackerProcessor
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()  # "sam3_video checkpoint into sam3_tracker" is expected
        path = sam3_dir()
        if not (path / SAM3_WEIGHTS).exists():
            raise FileNotFoundError(_("the SAM 3 model is missing ({file}): download it in LightCraft (Object mask) "
                                      "or with the AI Remove installer", file=path / SAM3_WEIGHTS))
        self.torch, self.dev = torch, dev
        # bfloat16 where the GPU has it; Apple and the processor get float32 (half precision there is slow or lossy)
        self.dtype = torch.bfloat16 if dev in ("cuda", "xpu") else torch.float32
        if (path / "config.json").exists():  # a full Hugging Face download
            self.proc = Sam3TrackerProcessor.from_pretrained(path)
            self.model = Sam3TrackerModel.from_pretrained(path, dtype=self.dtype)
        else:  # LightCraft's copy: the weights only
            self.proc = Sam3TrackerProcessor(image_processor=Sam3ImageProcessor())
            self.model = Sam3TrackerModel.from_pretrained(path, config=Sam3TrackerConfig(), dtype=self.dtype)
        self.model = self.model.to(dev).eval()
        self.img = self.emb = None
        log(f"SAM 3 ready ({dev})")

    def set_image(self, img: Image.Image):
        torch = self.torch
        inputs = self.proc(images=img, return_tensors="pt").to(self.dev)
        with torch.no_grad():
            self.emb = self.model.get_image_embeddings(inputs["pixel_values"].to(self.dtype))
        self.img = img

    def _run(self, pts, labels, logit=None, multi=False):
        torch = self.torch
        pi = self.proc(images=self.img, input_points=[[[[float(x), float(y)] for x, y in pts]]],
                       input_labels=[[[int(v) for v in labels]]], return_tensors="pt").to(self.dev)
        # previous low-res mask (batch, objects, masks, 288, 288) -> the prompt shape (batch, 1, 288, 288)
        kw = {} if logit is None or not USE_MASK_PROMPT else {"input_masks": logit[:, 0, :1]}
        with torch.no_grad():
            out = self.model(input_points=pi["input_points"], input_labels=pi["input_labels"],
                             image_embeddings=self.emb, multimask_output=multi, **kw)
        masks = self.proc.post_process_masks(out.pred_masks.float().cpu(), pi["original_sizes"])[0][0].numpy()
        return out, masks

    def click(self, x: float, y: float):
        """Whole object under the pixel (x, y): of SAM's three hypotheses (part / object / bigger) the largest one
        that is not most of the photo — for removing things the whole object is what is meant.
        Returns (mask, logit); logit is SAM's low-res mask, fed back when the object is refined."""
        out, masks = self._run([(x, y)], [1], multi=True)
        total = masks.shape[-2] * masks.shape[-1]
        areas = [int(m.sum()) for m in masks]
        yi = min(max(int(y), 0), masks.shape[-2] - 1)
        xi = min(max(int(x), 0), masks.shape[-1] - 1)
        # cap: things to remove are rarely >15 % of the frame (beyond that SAM's "bigger" is a wall or the ground)
        ok = [k for k in range(len(masks)) if areas[k] < 0.15 * total and masks[k][yi, xi]]
        k = max(ok, key=lambda i: areas[i]) if ok else int(np.argmax(out.iou_scores[0, 0].float().cpu().numpy()))
        return masks[k].astype(bool), out.pred_masks[:, :, k:k + 1]

    def refine(self, pts, labels, logit=None):
        """The object again with all its points: label 1 = belongs to it, 0 = does not (Alt-click)."""
        out, masks = self._run(pts, labels, logit, multi=False)
        return masks[0].astype(bool), out.pred_masks[:, :, 0:1]

    def unload(self):
        del self.model, self.emb
        _free_gpu()


def _step_callback(progress, total):
    """diffusers callback_on_step_end that reports (steps done, total) to `progress`."""
    def cb(pipe, i, t, kw):
        if progress:
            progress(i + 1, total)
        return kw
    return cb


# ------------------------------------------------------------------------------------------------ SDXL
class SDXL:
    name = "SDXL"

    def __init__(self, log=print):
        dev = device()
        import torch
        from diffusers import StableDiffusionXLInpaintPipeline, AutoencoderKL
        self.torch = torch
        dt = torch.float32 if dev == "cpu" else torch.float16  # the fp16-fix VAE makes half precision safe
        vae = AutoencoderKL.from_pretrained(MODELS / "sdxl-vae-fp16-fix", torch_dtype=dt)
        self.pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            MODELS / "sdxl-inpaint", vae=vae, variant="fp16", torch_dtype=dt).to(dev)
        if dev == "mps":
            self.pipe.enable_attention_slicing()  # lower peak memory on unified-memory Macs
        self.pipe.set_progress_bar_config(disable=True)
        log(f"SDXL ready ({dev})")

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str, seed: int, steps: int = 25,
             strength: float = 0.99, progress=None) -> Image.Image:
        """At strength 1.0 SDXL starts from noise on the photo with the hole masked out (nothing of the removed object
        leaks in); below 1 src must be pre-filled. progress(done, total) per step."""
        S = 1024
        out = self.pipe(prompt=f"{prompt}, {DEFAULT_PROMPT}" if prompt else DEFAULT_PROMPT, negative_prompt=NEGATIVE,
                        image=src.resize((S, S), Image.LANCZOS),
                        mask_image=mask.resize((S, S), Image.NEAREST).filter(ImageFilter.MaxFilter(9)),
                        height=S, width=S, strength=strength, guidance_scale=7.0, num_inference_steps=steps,
                        generator=self.torch.Generator("cpu").manual_seed(seed),
                        callback_on_step_end=_step_callback(progress, max(1, int(steps * strength)))).images[0]
        return out.resize(src.size, Image.LANCZOS)

    def unload(self):
        del self.pipe
        _free_gpu()


# ------------------------------------------------------------------------------------------------ FLUX
class FLUX:
    """FLUX.1 Fill [dev], GGUF-quantized transformer (diffusers dequantizes it layer by layer). ~12 GB on the GPU:
    SDXL and SAM 3 are unloaded first. Text embeddings are computed once per prompt on the processor and cached on
    disk (T5-XXL alone would need ~10 GB of VRAM)."""
    name = "FLUX"

    def __init__(self, log=print):
        dev = device()
        import torch
        from diffusers import FluxFillPipeline, FluxTransformer2DModel, GGUFQuantizationConfig
        from diffusers.utils import logging as dl
        dl.set_verbosity_error()
        self.torch, self.dev, self.repo = torch, dev, MODELS / "FLUX.1-Fill-dev"
        gg = MODELS / "gguf"
        self.quant = next(q for q in FLUX_QUANTS if (gg / f"flux1-fill-dev-{q}.gguf").exists())
        tr = FluxTransformer2DModel.from_single_file(
            str(gg / f"flux1-fill-dev-{self.quant}.gguf"),
            quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16), config=str(self.repo),
            subfolder="transformer", torch_dtype=torch.bfloat16)
        self.pipe = FluxFillPipeline.from_pretrained(self.repo, transformer=tr, text_encoder=None, text_encoder_2=None,
                                                     tokenizer=None, tokenizer_2=None,
                                                     torch_dtype=torch.bfloat16).to(dev)
        self.pipe.vae.enable_tiling()  # no multi-GB activation spike in the VAE
        self.pipe.set_progress_bar_config(disable=True)
        self.steps, self.turbo = FLUX_STEPS, False
        if FLUX_LORA.exists():  # Turbo-Alpha: same quality in half the steps
            try:
                self.pipe.load_lora_weights(str(FLUX_LORA.parent), weight_name=FLUX_LORA.name, adapter_name="turbo")
                self.steps, self.turbo = FLUX_TURBO_STEPS, True
            except Exception as e:
                log(f"FLUX: Turbo LoRA not loaded ({type(e).__name__}: {str(e)[:120]}), using {FLUX_STEPS} steps")
        log(f"FLUX ready ({dev}, {self.quant}, {self.steps} steps{' turbo' if self.turbo else ''})")

    def embeddings(self, prompt, log=print):
        import hashlib
        torch = self.torch
        d = MODELS / "flux_prompts"
        d.mkdir(exist_ok=True)
        f = d / (hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16] + ".pt")
        if not f.exists():
            from diffusers import FluxFillPipeline
            log("FLUX: encoding the prompt on the processor (once per prompt)…")
            enc = FluxFillPipeline.from_pretrained(self.repo, transformer=None, vae=None, torch_dtype=torch.bfloat16)
            with torch.no_grad():
                pe, pooled, _ = enc.encode_prompt(prompt=prompt, prompt_2=prompt, device="cpu", max_sequence_length=256)
            torch.save({"prompt": prompt, "prompt_embeds": pe, "pooled": pooled}, f)
            del enc
            import gc
            gc.collect()
        return torch.load(f)

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str, seed: int, steps: int = None,
             progress=None, log=print) -> Image.Image:
        torch = self.torch
        steps = steps or self.steps
        p = f"{prompt}, {DEFAULT_PROMPT}" if prompt else DEFAULT_PROMPT
        emb = self.embeddings(p, log)
        # only two working sizes: ROCm compiles GPU kernels (the VAE decoder above all) the first time it meets a
        # size — minutes — and caches them; with any multiple of 16 nearly every new area paid that again
        S = FLUX_SIZES[0] if src.width <= (FLUX_SIZES[0] + FLUX_SIZES[1]) // 2 else FLUX_SIZES[1]
        out = self.pipe(prompt_embeds=emb["prompt_embeds"].to(self.dev, torch.bfloat16),
                        pooled_prompt_embeds=emb["pooled"].to(self.dev, torch.bfloat16),
                        image=src.resize((S, S), Image.LANCZOS),
                        mask_image=mask.resize((S, S), Image.NEAREST).filter(ImageFilter.MaxFilter(9)),
                        height=S, width=S, guidance_scale=30.0, num_inference_steps=steps,
                        generator=torch.Generator("cpu").manual_seed(seed),
                        callback_on_step_end=_step_callback(progress, steps)).images[0]
        # give the cached blocks back: with ~10 GB at the peak, leftovers from one variant make the next one
        # spill into shared memory (3-10x slower)
        _free_gpu()
        return out.resize(src.size, Image.LANCZOS)

    def unload(self):
        del self.pipe
        _free_gpu()


# ------------------------------------------------------------------------------------------------ effect-aware removal
# EXPERIMENTAL. These engines remove the object together with its shadow and reflection. Their fill(...) returns
# (image, effect): effect is the region the model decided to change (object + shadow, L mode, src size), which can
# reach beyond the mask — the blend must use it as the hole, or the removed shadow is pasted back.
OSOR_PROMPT = "Remove the instance of object"  # the fixed prompt OSOR was trained with
OSOR_T = 0.4  # its single denoising step starts from 40 % noise on the photo itself (object included)


def _lora_targets(state, prefix):
    """PEFT module names of a raw OSOR state dict ("<prefix><module>.lora_A.default.weight")."""
    return sorted({k[len(prefix):].rsplit(".lora_", 1)[0] for k in state if ".lora_A." in k})


class OSORFlux:
    """OSOR (ECCV 2026) on FLUX.1 Fill [dev]: one step, ~10 GB at the peak (FLUX's quantized transformer). The
    checkpoint is a rank-64 LoRA plus a widened output layer: 64 velocity channels + 4 for the effect alpha."""
    name = "OSOR"

    def __init__(self, log=print):
        dev = device()
        import torch
        from diffusers import FluxFillPipeline, FluxTransformer2DModel, GGUFQuantizationConfig
        from diffusers.utils import logging as dl
        from peft import LoraConfig, inject_adapter_in_model
        dl.set_verbosity_error()
        self.torch, self.dev, self.repo = torch, dev, MODELS / "FLUX.1-Fill-dev"
        gg = MODELS / "gguf"
        quant = next(q for q in FLUX_QUANTS if (gg / f"flux1-fill-dev-{q}.gguf").exists())
        tr = FluxTransformer2DModel.from_single_file(
            str(gg / f"flux1-fill-dev-{quant}.gguf"),
            quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16), config=str(self.repo),
            subfolder="transformer", torch_dtype=torch.bfloat16)
        state = torch.load(MODELS / "osor" / "osor-fluxfill" / "weights" / "fluxfill_phase2.pth", map_location="cpu",
                           weights_only=True)
        pre = "transformer.base_model.model."
        targets = _lora_targets(state, pre)
        inject_adapter_in_model(LoraConfig(r=64, lora_alpha=64, target_modules=targets), tr)
        old = tr.proj_out
        tr.proj_out = torch.nn.Linear(old.in_features, 68, dtype=torch.bfloat16)
        sd = {k[len(pre):]: v.to(torch.bfloat16) for k, v in state.items()}
        missing, unexpected = tr.load_state_dict(sd, strict=False)
        if unexpected or any(".lora_" in k or k.startswith("proj_out") for k in missing):
            raise RuntimeError(f"OSOR: checkpoint does not match ({len(unexpected)} unexpected keys)")
        for n, p in tr.named_parameters():  # PEFT made them float32: the quantized base has no float dtype to follow
            if ".lora_" in n:
                p.data = p.data.to(torch.bfloat16)
        self.pipe = FluxFillPipeline.from_pretrained(self.repo, transformer=tr, text_encoder=None, text_encoder_2=None,
                                                     tokenizer=None, tokenizer_2=None,
                                                     torch_dtype=torch.bfloat16).to(dev)
        self.pipe.vae.enable_tiling()
        log(f"OSOR (FLUX) ready ({dev}, {quant}, {len(targets)} LoRA layers)")

    def embeddings(self, log=print):
        """The fixed prompt, T5 at 512 tokens as in training; encoded once on the processor and cached."""
        torch = self.torch
        d = MODELS / "flux_prompts"
        d.mkdir(exist_ok=True)
        f = d / "osor_flux.pt"
        if not f.exists():
            from diffusers import FluxFillPipeline
            log("OSOR: encoding the prompt on the processor (once)…")
            enc = FluxFillPipeline.from_pretrained(self.repo, transformer=None, vae=None, torch_dtype=torch.bfloat16)
            with torch.no_grad():
                pe, pooled, _ = enc.encode_prompt(prompt=OSOR_PROMPT, prompt_2=OSOR_PROMPT, device="cpu",
                                                  max_sequence_length=512)
            torch.save({"prompt": OSOR_PROMPT, "prompt_embeds": pe, "pooled": pooled}, f)
            del enc
            import gc
            gc.collect()
        return torch.load(f)

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str = "", seed: int = 0, progress=None, log=print):
        torch, pipe, dev = self.torch, self.pipe, self.dev
        emb = self.embeddings(log)
        S = FLUX_SIZES[0] if src.width <= (FLUX_SIZES[0] + FLUX_SIZES[1]) // 2 else FLUX_SIZES[1]
        g = torch.Generator("cpu").manual_seed(seed)
        x = torch.from_numpy(np.array(src.convert("RGB").resize((S, S), Image.LANCZOS))).permute(2, 0, 1)[None]
        x = (x.float() / 127.5 - 1).to(dev, torch.bfloat16)
        m = torch.from_numpy(np.asarray(mask.resize((S, S), Image.NEAREST)) > 127).float()[None, None]
        vae, L = pipe.vae, S // 8
        with torch.no_grad():
            z = vae.encode(x).latent_dist.mode().float()
            z = (z - vae.config.shift_factor) * vae.config.scaling_factor
            zp = pipe._pack_latents(z, 1, 16, L, L)
            mp = m.view(1, L, 8, L, 8).permute(0, 2, 4, 1, 3).reshape(1, 64, L, L)
            mp = pipe._pack_latents(mp, 1, 64, L, L).to(dev)
            noise = torch.randn(zp.shape, generator=g).to(dev)
            zt = (1 - OSOR_T) * zp + OSOR_T * noise
            ids = pipe._prepare_latent_image_ids(1, L // 2, L // 2, dev, torch.bfloat16)
            pe = emb["prompt_embeds"].to(dev, torch.bfloat16)
            out = pipe.transformer(
                hidden_states=torch.cat([zt, zp, mp], dim=2).to(torch.bfloat16),
                timestep=torch.full((1,), OSOR_T, device=dev, dtype=torch.bfloat16),
                guidance=torch.full((1,), 30.0, device=dev, dtype=torch.float32),
                pooled_projections=emb["pooled"].to(dev, torch.bfloat16), encoder_hidden_states=pe,
                txt_ids=torch.zeros(pe.shape[1], 3, device=dev, dtype=torch.bfloat16), img_ids=ids,
                return_dict=False)[0].float()
            if progress:
                progress(1, 1)
            v, a = out[..., :64], out[..., 64:]

            def unpack(p, c):  # (1, tokens, 4c) -> (1, c, L, L)
                return p.view(1, L // 2, L // 2, c, 2, 2).permute(0, 3, 1, 4, 2, 5).reshape(1, c, L, L)
            alpha = torch.sigmoid(unpack(a, 1))
            pred = unpack(zt - OSOR_T * v, 16)
            pred = pred / vae.config.scaling_factor + vae.config.shift_factor
            base = z / vae.config.scaling_factor + vae.config.shift_factor
            img = vae.decode((pred * alpha + base * (1 - alpha)).to(torch.bfloat16)).sample.float()
        img = ((img[0].clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).cpu().numpy()
        eff = (torch.nn.functional.interpolate(alpha, size=(S, S), mode="bilinear")[0, 0] * 255).byte().cpu().numpy()
        _free_gpu()
        return (Image.fromarray(img).resize(src.size, Image.LANCZOS),
                Image.fromarray(eff).resize(src.size, Image.BILINEAR))

    def unload(self):
        del self.pipe
        _free_gpu()


class OSORSDXL:
    """OSOR on SDXL Inpainting: one step at 512 px, ~7 GB at the peak. Rank-256 LoRA on the UNet plus a 5-channel output
    convolution (4 noise channels + the effect alpha). Licence: CreativeML Open RAIL++-M (commercial use allowed)."""
    name = "OSOR-SDXL"
    S = 512  # its training resolution

    def __init__(self, log=print):
        dev = device()
        import torch
        from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel
        from peft import LoraConfig
        self.torch, self.dev = torch, dev
        self.dt = dt = torch.float32 if dev == "cpu" else torch.float16
        unet = UNet2DConditionModel.from_pretrained(MODELS / "sdxl-inpaint", subfolder="unet", variant="fp16",
                                                    torch_dtype=dt)
        state = torch.load(MODELS / "osor" / "osor-sdxlinpainting" / "weights" / "sdxlinpainting_phase2.pth",
                           map_location="cpu", weights_only=True)
        targets = _lora_targets(state, "unet.")
        unet.add_adapter(LoraConfig(r=256, lora_alpha=256, target_modules=targets))
        old = unet.conv_out
        unet.conv_out = torch.nn.Conv2d(old.in_channels, 5, old.kernel_size, padding=old.padding, dtype=dt)
        missing, unexpected = unet.load_state_dict({k[5:]: v.to(dt) for k, v in state.items()}, strict=False)
        if unexpected or any(".lora_" in k or k.startswith("conv_out") for k in missing):
            raise RuntimeError(f"OSOR-SDXL: checkpoint does not match ({len(unexpected)} unexpected keys)")
        self.unet = unet.to(dev).eval()
        self.vae = AutoencoderKL.from_pretrained(MODELS / "sdxl-vae-fp16-fix", torch_dtype=dt).to(dev)
        self.sched = DDPMScheduler.from_pretrained(MODELS / "sdxl-inpaint", subfolder="scheduler")
        self.emb = self._embeddings()
        log(f"OSOR (SDXL) ready ({dev}, {len(targets)} LoRA layers)")

    def _embeddings(self):
        torch = self.torch
        from transformers import CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer
        base = MODELS / "sdxl-inpaint"
        out = []
        for sub, cls in (("", CLIPTextModel), ("_2", CLIPTextModelWithProjection)):
            tok = CLIPTokenizer.from_pretrained(base, subfolder="tokenizer" + sub)
            enc = cls.from_pretrained(base, subfolder="text_encoder" + sub, variant="fp16", torch_dtype=torch.float32)
            ids = tok(OSOR_PROMPT, padding="max_length", max_length=tok.model_max_length, truncation=True,
                      return_tensors="pt").input_ids
            with torch.no_grad():
                o = enc(ids, output_hidden_states=True)
            out.append(o)
            del enc
        pe = torch.cat([out[0].hidden_states[-2], out[1].hidden_states[-2]], dim=-1)
        return pe.to(self.dev, self.dt), out[1].text_embeds.to(self.dev, self.dt)

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str = "", seed: int = 0, progress=None, log=print):
        torch, dev, dt, S = self.torch, self.dev, self.dt, self.S
        g = torch.Generator("cpu").manual_seed(seed)
        x = torch.from_numpy(np.array(src.convert("RGB").resize((S, S), Image.LANCZOS))).permute(2, 0, 1)[None]
        x = (x.float() / 127.5 - 1).to(dev, dt)
        m = torch.from_numpy(np.asarray(mask.resize((S, S), Image.NEAREST)) > 127).float()[None, None]
        sf = self.vae.config.scaling_factor
        with torch.no_grad():
            z = self.vae.encode(x).latent_dist.mode() * sf
            ml = torch.nn.functional.max_pool2d(m, 8).to(dev, dt)
            t = torch.full((1,), int(OSOR_T * 1000), dtype=torch.long)
            noise = torch.randn(z.shape, generator=g).to(dev, dt)
            zt = self.sched.add_noise(z.float().cpu(), noise.float().cpu(), t).to(dev, dt)
            pe, pooled = self.emb
            out = self.unet(torch.cat([zt, ml, z], dim=1), t.to(dev), encoder_hidden_states=pe,
                            added_cond_kwargs={"text_embeds": pooled,
                                               "time_ids": torch.tensor([[S, S, 0, 0, S, S]], device=dev, dtype=dt)},
                            return_dict=False)[0].float()
            if progress:
                progress(1, 1)
            eps, alpha = out[:, :4], torch.sigmoid(out[:, 4:])
            ab = self.sched.alphas_cumprod[t].to(dev).float().view(1, 1, 1, 1)
            x0 = (zt.float() - (1 - ab).sqrt() * eps) / ab.sqrt()
            lat = x0 * alpha + z.float() * (1 - alpha)
            img = self.vae.decode((lat / sf).to(dt)).sample.float()
        img = ((img[0].clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).cpu().numpy()
        eff = (torch.nn.functional.interpolate(alpha, size=(S, S), mode="bilinear")[0, 0] * 255).byte().cpu().numpy()
        _free_gpu()
        return (Image.fromarray(img).resize(src.size, Image.LANCZOS),
                Image.fromarray(eff).resize(src.size, Image.BILINEAR))

    def unload(self):
        del self.unet, self.vae
        _free_gpu()


def _cv2_shim():
    """ObjectClear's fusion imports OpenCV for five calls; without opencv in the venv, the same with scipy."""
    import sys
    import types
    from scipy import ndimage as ndi
    cv2 = types.ModuleType("cv2")
    cv2.THRESH_BINARY, cv2.INTER_NEAREST, cv2.MORPH_ELLIPSE = 0, 0, 2
    cv2.threshold = lambda a, t, mx, _type: (t, np.where(a > t, mx, 0).astype(a.dtype))
    cv2.resize = lambda a, size, interpolation=0: np.asarray(
        Image.fromarray(a.astype(np.float32), "F").resize(size, Image.NEAREST))

    def ellipse(_shape, ksize):
        w, h = ksize
        yy, xx = np.mgrid[:h, :w]
        return ((((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2) <= 1).astype(np.uint8)
    cv2.getStructuringElement = ellipse
    cv2.dilate = lambda a, k, iterations=1: ndi.grey_dilation(a, footprint=k.astype(bool))
    cv2.GaussianBlur = lambda a, ksize, sigmaX=0: ndi.gaussian_filter(a, sigmaX, truncate=(ksize[0] // 2) / sigmaX)
    sys.modules["cv2"] = cv2


class ObjectClear:
    """ObjectClear (CVPR 2026, NTU S-Lab): SDXL fine-tuned to remove objects with their effects; the object is also
    shown to it through a CLIP image encoder, and an attention map of object + effects guides the final fusion.
    Trained at 512 px, 20 steps. Licence: S-Lab 1.0, NON-commercial. Code: models/objectclear/code."""
    name = "ObjectClear"
    S = 512

    def __init__(self, log=print):
        import sys
        dev = device()
        import torch
        code = str(MODELS / "objectclear" / "code")
        if code not in sys.path:
            sys.path.insert(0, code)
        try:
            import cv2  # noqa: F401
        except ImportError:
            _cv2_shim()
        from objectclear.pipelines import ObjectClearPipeline
        self.torch, self.dev = torch, dev
        dt = torch.float32 if dev == "cpu" else torch.float16
        self.pipe = ObjectClearPipeline.from_pretrained_with_custom_modules(
            str(MODELS / "objectclear"), torch_dtype=dt, variant="fp16" if dt == torch.float16 else None,
            apply_attention_guided_fusion=True).to(dev)
        self.pipe.set_progress_bar_config(disable=True)
        log(f"ObjectClear ready ({dev})")

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str = "", seed: int = 0, steps: int = 20,
             guidance: float = 2.5, progress=None, log=print):
        S = self.S
        res = self.pipe(prompt="remove the instance of object", image=src.convert("RGB").resize((S, S), Image.LANCZOS),
                        mask_image=mask.resize((S, S), Image.NEAREST), num_inference_steps=steps,
                        guidance_scale=guidance, height=S, width=S, return_attn_map=True,
                        generator=self.torch.Generator(self.dev).manual_seed(seed),
                        callback_on_step_end=_step_callback(progress, steps))
        eff = res.attns[0].convert("L") if getattr(res, "attns", None) else mask
        _free_gpu()
        return res.images[0].resize(src.size, Image.LANCZOS), eff.resize(src.size, Image.BILINEAR)

    def unload(self):
        del self.pipe
        _free_gpu()
