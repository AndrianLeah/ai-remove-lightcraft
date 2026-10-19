"""Engines for AI Remove: SAM 3 (selection), LaMa (ONNX, processor), SDXL Inpainting and FLUX.1 Fill (diffusers),
and two that remove an object together with its shadow and reflection: OSOR (a mode of the FLUX engine: the same
transformer with OSOR's adapter) and ObjectClear (its own SDXL-based pipeline).

The accelerator is whatever PyTorch finds: NVIDIA (CUDA), AMD (ROCm, reported by torch as "cuda"), Intel Arc (xpu),
Apple Silicon (mps) — else the processor, where only LaMa is practical. On a 16 GB card SDXL, FLUX and ObjectClear
don't fit together: the session unloads one before loading another."""
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
SDXL_STEPS, SDXL_GUIDED_STEPS = 12, 5  # DPM++ steps; classifier-free guidance on the first 5 only
SDXL_CFG_INPUTS = ["prompt_embeds", "add_text_embeds", "add_time_ids", "mask", "masked_image_latents"]
SAM3_WEIGHTS = "model.safetensors"
OSOR_WEIGHTS = Path("osor") / "osor-fluxfill" / "weights" / "fluxfill_phase2.pth"  # in MODELS
OSOR_PROMPT = "Remove the instance of object"  # the fixed prompt OSOR was trained with
OSOR_T = 0.4  # its single denoising step starts from 40 % noise on the photo itself (object included)

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
    flux = ((m / "FLUX.1-Fill-dev" / "model_index.json").exists()
            and any((m / "gguf" / f"flux1-fill-dev-{q}.gguf").exists() for q in FLUX_QUANTS))
    return {
        "sam3": (sam3_dir() / SAM3_WEIGHTS).exists(),
        "lama": (m / "lama" / "lama_fp32.onnx").exists(),
        "sdxl": (m / "sdxl-inpaint" / "model_index.json").exists() and (m / "sdxl-vae-fp16-fix" / "config.json").exists(),
        "flux": flux,
        "osor": flux and (m / OSOR_WEIGHTS).exists(),
        "objectclear": (m / "objectclear" / "model_index.json").exists()
        and (m / "objectclear" / "code" / "objectclear" / "pipelines" / "pipeline_objectclear.py").exists(),
    }


def usable(model, dev=None):
    """Installed and sensible on this machine: FLUX (and OSOR, which runs on it) needs a GPU; SDXL and ObjectClear
    work on the processor but take minutes."""
    dev = dev or device()
    if not available().get(model):
        return False
    return model not in ("flux", "osor") or dev != "cpu"


SHADOW_MODELS = ("osor", "objectclear")  # remove the object together with its shadow and reflection


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


def _step_callback(progress, total, guided=0):
    """diffusers callback_on_step_end that reports (steps done, total) to `progress`. With `guided`, SDXL's
    classifier-free guidance ends after that many steps: by then the negative prompt has done its work (what goes in
    the hole is decided), and every later step is one UNet pass instead of two — the conditional half of the batched
    inputs (SDXL_CFG_INPUTS) is kept. Same detail in the result, measured."""
    def cb(pipe, i, t, kw):
        if progress:
            progress(i + 1, total)
        if guided and i + 1 == guided and pipe.do_classifier_free_guidance:
            pipe._guidance_scale = 0.0  # set again by the next call
            return {k: kw[k].chunk(2)[1] for k in SDXL_CFG_INPUTS}
        return kw
    return cb


# ------------------------------------------------------------------------------------------------ SDXL
class SDXL:
    name = "SDXL"

    def __init__(self, log=print):
        dev = device()
        import torch
        from diffusers import StableDiffusionXLInpaintPipeline, AutoencoderKL, DPMSolverMultistepScheduler
        self.torch = torch
        dt = torch.float32 if dev == "cpu" else torch.float16  # the fp16-fix VAE makes half precision safe
        vae = AutoencoderKL.from_pretrained(MODELS / "sdxl-vae-fp16-fix", torch_dtype=dt)
        self.pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            MODELS / "sdxl-inpaint", vae=vae, variant="fp16", torch_dtype=dt).to(dev)
        if dev == "mps":
            self.pipe.enable_attention_slicing()  # lower peak memory on unified-memory Macs
        # DPM++ 2M with Karras sigmas: in 12 steps the same fills (same seed, same picture) the model's own Euler
        # sampler gives in 25 — measured on the same areas and seeds. Few-step LoRAs (SDXL-Lightning) were faster
        # still, but with this inpainting UNet they blurred the hole or invented things in it.
        self.pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            self.pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True)
        self.pipe.set_progress_bar_config(disable=True)
        self.masked = (None, None)  # (key, latents) of the last removal's photo with the hole blanked out
        log(f"SDXL ready ({dev})")

    def masked_latents(self, image: Image.Image, mask: Image.Image):
        """The VAE latents of the photo with the hole blanked out, which the inpainting UNet sees next to the noise.
        They are the same for every variant of a removal, so they are encoded once: ~1.3 s of a ~7.3 s variant on an
        RX 7800 XT. The pipeline would sample the latent distribution; its mean is used here (the spread is below one
        fp16 step: the fills look the same, measured)."""
        import hashlib
        torch, pipe = self.torch, self.pipe
        key = hashlib.sha1(image.tobytes() + mask.tobytes()).digest()
        if self.masked[0] != key:
            init = pipe.image_processor.preprocess(image, height=image.height, width=image.width)
            hole = pipe.mask_processor.preprocess(mask, height=mask.height, width=mask.width)
            masked = (init * (hole < 0.5)).to(pipe.device, pipe.vae.dtype)
            with torch.no_grad():
                lat = pipe.vae.encode(masked).latent_dist.mode() * pipe.vae.config.scaling_factor
            self.masked = (key, lat)
        return self.masked[1]

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str, seed: int, steps: int = SDXL_STEPS,
             strength: float = 0.99, progress=None) -> Image.Image:
        """At strength 1.0 SDXL starts from noise on the photo with the hole masked out (nothing of the removed object
        leaks in); below 1 src must be pre-filled. progress(done, total) per step."""
        S = 1024
        image = src.resize((S, S), Image.LANCZOS)
        mask_image = mask.resize((S, S), Image.NEAREST).filter(ImageFilter.MaxFilter(9))
        cb = _step_callback(progress, max(1, int(steps * strength)), SDXL_GUIDED_STEPS)
        out = self.pipe(prompt=f"{prompt}, {DEFAULT_PROMPT}" if prompt else DEFAULT_PROMPT, negative_prompt=NEGATIVE,
                        image=image, mask_image=mask_image, masked_image_latents=self.masked_latents(image, mask_image),
                        height=S, width=S, strength=strength, guidance_scale=7.0, num_inference_steps=steps,
                        generator=self.torch.Generator("cpu").manual_seed(seed),
                        callback_on_step_end=cb, callback_on_step_end_tensor_inputs=SDXL_CFG_INPUTS).images[0]
        return out.resize(src.size, Image.LANCZOS)

    def unload(self):
        del self.pipe
        _free_gpu()


# ------------------------------------------------------------------------------------------------ FLUX
class FLUX:
    """FLUX.1 Fill [dev], GGUF-quantized transformer (diffusers dequantizes it layer by layer). ~12 GB on the GPU:
    SDXL and SAM 3 are unloaded first. Text embeddings are computed once per prompt on the processor and cached on
    disk (T5-XXL alone would need ~10 GB of VRAM).

    OSOR (ECCV 2026) runs on the same transformer: its adapter (a rank-64 LoRA, loaded next to Turbo) and its own
    output layer (64 velocity channels + 4 for the "effect" alpha: object + shadow + reflection). Switching between
    FLUX and OSOR is instant and costs ~0.6 GB more than FLUX alone."""
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
        self.proj_flux = self.proj_osor = None  # output layers of FLUX and of OSOR (once OSOR is loaded)
        log(f"FLUX ready ({dev}, {self.quant}, {self.steps} steps{' turbo' if self.turbo else ''})")

    def embeddings(self, prompt, log=print, tokens=256):
        import hashlib
        torch = self.torch
        d = MODELS / "flux_prompts"
        d.mkdir(exist_ok=True)
        name = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16] + ("" if tokens == 256 else f"-{tokens}")
        f = d / (name + ".pt")
        if not f.exists():
            from diffusers import FluxFillPipeline
            log("FLUX: encoding the prompt on the processor (once per prompt)…")
            enc = FluxFillPipeline.from_pretrained(self.repo, transformer=None, vae=None, torch_dtype=torch.bfloat16)
            with torch.no_grad():
                pe, pooled, _ = enc.encode_prompt(prompt=prompt, prompt_2=prompt, device="cpu",
                                                  max_sequence_length=tokens)
            torch.save({"prompt": prompt, "prompt_embeds": pe, "pooled": pooled}, f)
            del enc
            import gc
            gc.collect()
        return torch.load(f)

    # -------------------------------------------------------------- OSOR on the same transformer
    def osor_loaded(self):
        return self.proj_osor is not None

    def load_osor(self, log=print):
        """OSOR's adapter and output layer, once. The released checkpoint is a raw PEFT state dict: its LoRA keys
        become diffusers' ("transformer.<module>.lora_A.weight"), its proj_out a second output layer."""
        if self.proj_osor is not None:
            return
        torch = self.torch
        state = torch.load(MODELS / OSOR_WEIGHTS, map_location="cpu", weights_only=True)
        pre = "transformer.base_model.model."
        lora = {"transformer." + k[len(pre):].replace(".default.", "."): v.to(torch.bfloat16)
                for k, v in state.items() if ".lora_" in k}
        self.pipe.load_lora_weights(lora, adapter_name="osor")
        tr = self.pipe.transformer
        proj = torch.nn.Linear(tr.proj_out.in_features, 68, dtype=torch.bfloat16)
        proj.load_state_dict({"weight": state[pre + "proj_out.weight"], "bias": state[pre + "proj_out.bias"]})
        self.proj_flux, self.proj_osor = tr.proj_out, proj.to(self.dev)
        self._use(osor=False)
        log(f"OSOR ready on FLUX ({len(lora) // 2} LoRA layers)")

    def _use(self, osor):
        """The transformer as FLUX Fill (Turbo) or as OSOR."""
        if self.proj_osor is None:
            return
        pipe = self.pipe
        pipe.enable_lora()
        if osor:
            pipe.set_adapters(["osor"])
        elif self.turbo:
            pipe.set_adapters(["turbo"])
        else:
            pipe.disable_lora()
        pipe.transformer.proj_out = self.proj_osor if osor else self.proj_flux

    def fill_osor(self, src: Image.Image, mask: Image.Image, seed: int = 0, progress=None, log=print):
        """OSOR: one denoising step on the photo with the object still in it. Returns (image, effect): effect (L,
        src size) is the region OSOR changed — the object with its shadow and reflection — and can reach beyond
        the mask."""
        torch, pipe, dev = self.torch, self.pipe, self.dev
        self.load_osor(log)
        emb = self.embeddings(OSOR_PROMPT, log, tokens=512)
        self._use(osor=True)
        S = FLUX_SIZES[0] if src.width <= (FLUX_SIZES[0] + FLUX_SIZES[1]) // 2 else FLUX_SIZES[1]
        g = torch.Generator("cpu").manual_seed(seed)
        x = torch.from_numpy(np.array(src.convert("RGB").resize((S, S), Image.LANCZOS))).permute(2, 0, 1)[None]
        x = (x.float() / 127.5 - 1).to(dev, torch.bfloat16)
        m = torch.from_numpy(np.asarray(mask.resize((S, S), Image.NEAREST)) > 127).float()[None, None]
        vae, L = pipe.vae, S // 8
        try:
            with torch.no_grad():
                z = vae.encode(x).latent_dist.mode().float()
                z = (z - vae.config.shift_factor) * vae.config.scaling_factor
                zp = pipe._pack_latents(z, 1, 16, L, L)
                mp = m.view(1, L, 8, L, 8).permute(0, 2, 4, 1, 3).reshape(1, 64, L, L)  # 8x8 mask pixels per latent
                mp = pipe._pack_latents(mp, 1, 64, L, L).to(dev)
                noise = torch.randn(zp.shape, generator=g).to(dev)
                zt = (1 - OSOR_T) * zp + OSOR_T * noise
                pe = emb["prompt_embeds"].to(dev, torch.bfloat16)
                out = pipe.transformer(
                    hidden_states=torch.cat([zt, zp, mp], dim=2).to(torch.bfloat16),
                    timestep=torch.full((1,), OSOR_T, device=dev, dtype=torch.bfloat16),
                    guidance=torch.full((1,), 30.0, device=dev, dtype=torch.float32),
                    pooled_projections=emb["pooled"].to(dev, torch.bfloat16), encoder_hidden_states=pe,
                    txt_ids=torch.zeros(pe.shape[1], 3, device=dev, dtype=torch.bfloat16),
                    img_ids=pipe._prepare_latent_image_ids(1, L // 2, L // 2, dev, torch.bfloat16),
                    return_dict=False)[0].float()
                if progress:
                    progress(1, 1)
                v, a = out[..., :64], out[..., 64:]

                def unpack(p, c):  # (1, tokens, 4c) -> (1, c, L, L)
                    return p.view(1, L // 2, L // 2, c, 2, 2).permute(0, 3, 1, 4, 2, 5).reshape(1, c, L, L)
                alpha = torch.sigmoid(unpack(a, 1))
                pred = unpack(zt - OSOR_T * v, 16) / vae.config.scaling_factor + vae.config.shift_factor
                base = z / vae.config.scaling_factor + vae.config.shift_factor
                img = vae.decode((pred * alpha + base * (1 - alpha)).to(torch.bfloat16)).sample.float()
        finally:
            self._use(osor=False)
        img = ((img[0].clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).cpu().numpy()
        eff = (torch.nn.functional.interpolate(alpha, size=(S, S), mode="bilinear")[0, 0] * 255).byte().cpu().numpy()
        _free_gpu()
        return (Image.fromarray(img).resize(src.size, Image.LANCZOS),
                Image.fromarray(eff).resize(src.size, Image.BILINEAR))

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


# ------------------------------------------------------------------------------------------------ ObjectClear
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
    Trained at 512 px, 20 steps, ~3 s on a 7800 XT, ~8 GB. Licence: S-Lab 1.0, NON-commercial. Its pipeline code is
    downloaded by the installer into models/objectclear/code (not shipped with AI Remove: same licence)."""
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
        dt = torch.float32 if dev == "cpu" else torch.float16  # only the fp16 files are installed: upcast on the CPU
        self.pipe = ObjectClearPipeline.from_pretrained_with_custom_modules(
            str(MODELS / "objectclear"), torch_dtype=dt, variant="fp16", apply_attention_guided_fusion=True).to(dev)
        self.pipe.set_progress_bar_config(disable=True)
        log(f"ObjectClear ready ({dev})")

    def fill(self, src: Image.Image, mask: Image.Image, seed: int = 0, steps: int = 20, guidance: float = 2.5,
             progress=None, log=print):
        """Returns (image, effect): effect (L, src size) is its attention map of the object and its effects."""
        S = self.S
        res = self.pipe(prompt="remove the instance of object", image=src.convert("RGB").resize((S, S), Image.LANCZOS),
                        mask_image=mask.resize((S, S), Image.NEAREST), num_inference_steps=steps,
                        guidance_scale=guidance, height=S, width=S, return_attn_map=True,
                        generator=self.torch.Generator("cpu").manual_seed(seed),
                        callback_on_step_end=_step_callback(progress, steps))
        eff = res.attns[0].convert("L") if getattr(res, "attns", None) else mask
        _free_gpu()
        return res.images[0].resize(src.size, Image.LANCZOS), eff.resize(src.size, Image.BILINEAR)

    def unload(self):
        del self.pipe
        _free_gpu()
