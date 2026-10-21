"""Engines for AI Remove: SAM 3 (selection), LaMa (ONNX, processor), SDXL Inpainting and FLUX.1 Fill (diffusers),
RORem (SDXL Inpainting retrained to remove: its UNet in SDXL's pipeline), two that remove an object together with its
shadow and reflection: OSOR (a mode of the FLUX engine: the same transformer with OSOR's adapter) and ObjectClear (its
own SDXL-based pipeline), and Qwen-Image 2.1, which removes the selection by name.

The accelerator is whatever PyTorch finds: NVIDIA (CUDA), AMD (ROCm, reported by torch as "cuda"), Intel Arc (xpu),
Apple Silicon (mps) — else the processor, where only LaMa is practical. On a 16 GB card SDXL, FLUX and ObjectClear
don't fit together: the session unloads one before loading another."""
import os
import numpy as np
from PIL import Image, ImageFilter

import model_files as mf
import system
from i18n import _

ROOT = system.ROOT
MODELS = mf.models_dir()  # the install's models; a model the user already had elsewhere is where mf.part_dir says
USE_MASK_PROMPT = True  # refine SAM objects with their previous mask as a prompt (see SAM3.refine)
DEFAULT_PROMPT = "empty background, seamless continuation of the surrounding scene, photograph, natural light"
NEGATIVE = ("person, people, human, man, woman, child, figure, statue, animal, text, watermark, logo, "
            "blurry, deformed, painting, illustration")
FLUX_QUANTS = mf.FLUX_QUANTS
FLUX_SIZES, FLUX_STEPS, FLUX_TURBO_STEPS = (512, 768), 16, 8
SDXL_STEPS, SDXL_GUIDED_STEPS = 12, 5  # DPM++ steps; classifier-free guidance on the first 5 only
SDXL_CFG_INPUTS = ["prompt_embeds", "add_text_embeds", "add_time_ids", "mask", "masked_image_latents"]
SDXL_HOLD = 0.5  # share of the steps a held region (SDXL.fill hold=) follows its pre-fill
SAM3_WEIGHTS = mf.SAM3_WEIGHTS
# Describe (SAM3.describe): an instance SAM 3 finds counts above this score, as in LightCraft's Describe; where it is
# the strongest instance and its own logit is above DESCRIBE_NEAR, the semantic mask joins it (describe_masks)
DESCRIBE_SCORE, DESCRIBE_NEAR = 0.5, -4.0
# RORem's authors' prompt: with it and without classifier-free guidance it removes best (their README)
ROREM_PROMPT = "4K, high quality, masterpiece, Highly detailed, Sharp focus, Professional, photorealistic, realistic"
OSOR_PROMPT = "Remove the instance of object"  # the fixed prompt OSOR was trained with
OSOR_T = 0.4  # its single denoising step starts from 40 % noise on the photo itself (object included)
QWEN_SIZE = 1024  # on the area's short side: an oblong area keeps its shape (qwen_dims)
QWEN_COND_SIZE, QWEN_MASK_SIZE, QWEN_NAME_SIZE = 1024, 512, 768  # the photo, the hole and the picture it is named in
QWEN_ASK = ("The area outlined in red in this photo will be erased. Name the object that the red outline traces "
            "(not what is behind it). Answer with a short noun phrase only, such as \"the man with a backpack\", "
            "\"the street sign\" or \"the parked car\".")
QWEN_REMOVE = ("Remove {what} from the photo and fill the area with the background that naturally continues the "
               "surrounding scene. Keep everything else exactly as it is. Do not add any person or object.")
QWEN_LOCK = True  # outside the hole the latents follow the photo's at every step (the edit cannot drift there)
# 4 steps instead of Turbo's own 8: lightx2v's schedule for its 4-step Lightning LoRA, shifted by the picture's size as
# that LoRA's scheduler does (about 1, 0.86, 0.67, 0.4 at 1024 px), on Turbo alone. Measured on 5 removals, 16 variants
# each way, at 100 % after the write-back: the same content and detail as 8 steps, 24 s instead of 39 per variant. The
# Lightning LoRA itself (on Qwen-Image 2.1 or on Turbo) added fake texture, broke railings and drew a column back
QWEN_SIGMAS = (1.0, 0.75, 0.5, 0.25)

_DEVICE = None


def _gpu_env():
    # AMD (ROCm): the experimental fast attention kernels (flash / memory-efficient attention)
    os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")
    # AMD (ROCm): a convolution's kernel comes from MIOpen's database or its heuristics, not from timing them all the
    # first time a size is seen: 1-2 minutes per VAE size, and Qwen-Image draws an oblong area in the area's own shape
    # (4-5 minutes the first time for each). Measured with an empty database: SDXL's steps as fast as with tuned kernels
    os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
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


def qwen_dims(w, h, side=QWEN_SIZE, area=False):
    """(width, height) at which Qwen-Image draws or reads a w x h picture: `side` px on its short side, or (area) as
    many pixels as a side x side square, as Qwen's own pipeline sizes its condition pictures. Its shape is kept, in
    multiples of 32 px (Qwen3-VL reads 2 x 2 latents of 16 px as one image slot). A square: side x side."""
    f = side / ((w * h) ** 0.5 if area else min(w, h))
    return max(32, round(w * f / 32) * 32), max(32, round(h * f / 32) * 32)


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
    second 3.2 GB copy) when it is there — or the user's own folder the installer found it in. No config files are
    needed: transformers' defaults for the SAM 3 tracker are this checkpoint's (checked: identical masks)."""
    d = mf.part_dir("sam3")
    if d != MODELS / "sam3":
        return d
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


def installed(model):
    """The model's files are there (model_files: in models/ or in the user's own folder), the checks the installer
    makes too. OSOR runs on FLUX and RORem on SDXL's files: they need FLUX and SDXL as well."""
    if model == "sam3":
        return mf.part_ok("sam3", sam3_dir())
    return mf.has(model) and {"osor": mf.has("flux"), "rorem": mf.has("sdxl")}.get(model, True)


def available():
    """Which models are on disk."""
    return {m: installed(m) for m in mf.MODELS}


def model_folders():
    """{part: folder} of the parts used from the user's own folders (the rest are in models/)."""
    return {p: str(mf.part_dir(p)) for p in mf.recorded() if mf.part_dir(p) != MODELS / p}


def usable(model, dev=None):
    """Installed and sensible on this machine: FLUX (and OSOR, which runs on it) and Qwen-Image need a GPU; SDXL,
    RORem and ObjectClear work on the processor but take minutes."""
    dev = dev or device()
    if not installed(model):
        return False
    return model not in ("flux", "osor", "qwen") or dev != "cpu"


SHADOW_MODELS = ("osor", "objectclear")  # remove the object together with its shadow and reflection


# ------------------------------------------------------------------------------------------------ LaMa
_LAMA = None


def lama(src: Image.Image, mask: Image.Image) -> Image.Image:
    """LaMa at its fixed 512 px. The ONNX session is made once (~12 s of a ~14 s first call; later ones ~1.6 s)."""
    global _LAMA
    if _LAMA is None:
        import onnxruntime as ort
        _LAMA = ort.InferenceSession(str(mf.part_dir("lama") / "lama_fp32.onnx"), providers=["CPUExecutionProvider"])
    sess = _LAMA
    img = np.asarray(src.resize((512, 512), Image.LANCZOS)).astype(np.float32) / 255.0
    mk = (np.asarray(mask.resize((512, 512), Image.NEAREST)) > 127).astype(np.float32)
    out = sess.run(None, {"image": (img * (1 - mk[..., None])).transpose(2, 0, 1)[None], "mask": mk[None, None]})[0][0]
    out = out.transpose(1, 2, 0)
    if out.max() <= 2:
        out = out * 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).resize(src.size, Image.LANCZOS)


# ------------------------------------------------------------------------------------------------ SAM 3
def describe_masks(inst, scores, semantic, size, min_score=DESCRIBE_SCORE, near=DESCRIBE_NEAR):
    """SAM 3's text detection as one bool mask per instance found, at size=(w, h); returns (masks, their scores).
    inst: (n, h, w) instance logits, scores: (n,), semantic: (h, w) logits, at the model's resolution (288 x 288).

    An instance's own mask (logit > 0) leaves holes where SAM 3 is unsure inside it, and a seam where two instances
    touch: both fade there. As LightCraft 0.11 does (its #1963), where an instance is the strongest one and near (its
    own logit above `near`) it takes the semantic mask too, which is sure inside and runs on across that seam. For
    removing, its own mask stays as well: a pixel too many is filled, one too few is left in the photo."""
    scores = np.asarray(scores, np.float32)
    keep = np.nonzero(scores > min_score)[0]
    if not len(keep):
        return [], scores[:0]
    m = np.asarray(inst, np.float32)[keep]
    s = np.asarray(semantic, np.float32)
    strongest = m.argmax(axis=0)
    masks = []
    for j in range(len(m)):
        joined = np.where((strongest == j) & (m[j] > near), np.maximum(m[j], s), m[j])
        masks.append(np.asarray(Image.fromarray(joined).resize(size, Image.BILINEAR)) > 0)
    return masks, scores[keep]


class SAM3:
    """Click-to-select with SAM 3 (the tracker half: point prompts), using the same weights LightCraft downloaded.
    On a GPU ~0.25 s per photo and ~0.05 s per click — LightCraft's own Object tool runs a ~35 s detail pass after
    every click. describe() selects by text with the other half, the detector, loaded the first time."""

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
        self.path, self.detector, self.det_proc = path, None, None
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

    def describe(self, text, log=print):
        """Every instance of `text` (in English: "person", "car", "sign") in the photo set_image was given, one bool
        mask each, with their scores (describe_masks). ~0.3 s on a GPU; the first call loads the detector."""
        torch = self.torch
        if self.detector is None:
            self._load_detector(log)
        inputs = self.det_proc(images=self.img, text=text, return_tensors="pt").to(self.dev)
        with torch.no_grad():
            o = self.detector(pixel_values=inputs["pixel_values"].to(self.dtype), input_ids=inputs["input_ids"],
                              attention_mask=inputs["attention_mask"])
        scores = o.pred_logits.float().sigmoid()[0]
        if o.presence_logits is not None:  # whether the phrase is in the photo at all
            scores = scores * o.presence_logits.float().sigmoid()[0]
        keep = torch.nonzero(scores > DESCRIBE_SCORE).flatten()  # only those leave the GPU
        return describe_masks(o.pred_masks[0, keep].float().cpu().numpy(), scores[keep].cpu().numpy(),
                              o.semantic_seg[0, 0].float().cpu().numpy(), self.img.size)

    def _load_detector(self, log=print):
        """SAM 3's detector, next to the tracker. Their image encoders are the same weights but for the neck: each
        part found identical, tensor by tensor, is the tracker's own (~0.9 GB less on the GPU). The text needs the
        tokenizer: the full download's, else built from vocab.json and merges.txt (LightCraft keeps those)."""
        import time
        from transformers import CLIPTokenizer, Sam3Config, Sam3ImageProcessor, Sam3Model, Sam3Processor
        torch, t0 = self.torch, time.time()
        full = (self.path / "config.json").exists()
        det = (Sam3Model.from_pretrained(self.path, dtype=self.dtype) if full else
               Sam3Model.from_pretrained(self.path, config=Sam3Config(), dtype=self.dtype))
        shared = []
        for name, part in det.vision_encoder.named_children():
            mine = getattr(self.model.vision_encoder, name, None)
            if mine is None:
                continue
            a, b = part.state_dict(), mine.state_dict()
            if a.keys() == b.keys() and all(torch.equal(a[k].to(b[k].device, b[k].dtype), b[k]) for k in a):
                setattr(det.vision_encoder, name, mine)
                shared.append(name)
        self.detector = det.to(self.dev).eval()
        if (self.path / "tokenizer.json").exists() or (self.path / "tokenizer_config.json").exists():
            self.det_proc = Sam3Processor.from_pretrained(self.path)
        else:
            vocab = next((d for d in (self.path, system.lightcraft_sam3_dir())
                          if (d / "vocab.json").exists() and (d / "merges.txt").exists()), None)
            if vocab is None:
                raise FileNotFoundError(_("Describe needs SAM 3's text files (vocab.json and merges.txt), which come "
                                          "with the model: run the AI Remove installer again"))
            # from the folder: transformers 5 no longer reads files given to the constructor (checked: the same
            # token ids as the full download's tokenizer)
            tok = CLIPTokenizer.from_pretrained(vocab, model_max_length=32, pad_token="<|endoftext|>")
            self.det_proc = Sam3Processor(image_processor=Sam3ImageProcessor(), tokenizer=tok)
        log(f"SAM 3 Describe ready in {time.time() - t0:.1f}s "
            f"(shared with the click model: {', '.join(shared) or 'none'})")

    def unload(self):
        del self.model, self.emb
        self.detector = self.det_proc = None
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
    S = 1024  # its working size
    PROMPT, NEGATIVE, GUIDANCE = DEFAULT_PROMPT, NEGATIVE, 7.0  # what every fill is told (a typed prompt goes first)
    TEXT = True  # a typed prompt (the window's field, a mask's "Remove: <text>") is put before PROMPT

    def __init__(self, log=print, unet=None):
        """unet: another UNet for SDXL Inpainting's pipeline (RORem), given its folder and the dtype it gets."""
        dev = device()
        import torch
        from diffusers import (StableDiffusionXLInpaintPipeline, AutoencoderKL, DPMSolverMultistepScheduler,
                               UNet2DConditionModel)
        self.torch = torch
        dt = torch.float32 if dev == "cpu" else torch.float16  # the fp16-fix VAE makes half precision safe
        vae = AutoencoderKL.from_pretrained(mf.part_dir("sdxl-vae-fp16-fix"), torch_dtype=dt)
        own = {} if unet is None else {"unet": UNet2DConditionModel.from_pretrained(unet, torch_dtype=dt)}
        self.pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            mf.part_dir("sdxl-inpaint"), vae=vae, variant="fp16", torch_dtype=dt, **own).to(dev)
        if dev == "mps":
            self.pipe.enable_attention_slicing()  # lower peak memory on unified-memory Macs
        # DPM++ 2M with Karras sigmas: in 12 steps the same fills (same seed, same picture) the model's own Euler
        # sampler gives in 25 — measured on the same areas and seeds. Few-step LoRAs (SDXL-Lightning) were faster
        # still, but with this inpainting UNet they blurred the hole or invented things in it.
        self.pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            self.pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True)
        self.pipe.set_progress_bar_config(disable=True)
        self.masked = (None, None)  # (key, latents) of the last removal's photo with the hole blanked out
        self.held = (None, None)  # (key, latents) of the last held pre-fill (fill hold=)
        log(f"{self.name} ready ({dev})")

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
             strength: float = 0.99, progress=None, hold=None) -> Image.Image:
        """At strength 1.0 SDXL starts from noise on the photo with the hole masked out (nothing of the removed object
        leaks in); below 1 src must be pre-filled. progress(done, total) per step.
        hold=(image, region): at strength 1, the region of the hole (bool, src size: the sky it continues) follows
        `image` for the first SDXL_HOLD of the steps, then SDXL finishes it freely. What goes where is settled in the
        first steps, so nothing is drawn into that sky (a bush where a hat stood against it, an animal on a
        skyline, the mottled ghost of the object), and the sky still meets the rest of the fill."""
        S = self.S
        image = src.resize((S, S), Image.LANCZOS)
        mask_image = mask.resize((S, S), Image.NEAREST).filter(ImageFilter.MaxFilter(9))
        cb = _step_callback(progress, max(1, int(steps * strength)), SDXL_GUIDED_STEPS)
        inputs = SDXL_CFG_INPUTS
        if hold is not None and strength >= 1.0:
            cb = self._hold(cb, hold[0].resize((S, S), Image.LANCZOS), hold[1], seed, steps)
            inputs = SDXL_CFG_INPUTS + ["latents"]
        out = self.pipe(prompt=f"{prompt}, {self.PROMPT}" if prompt and self.TEXT else self.PROMPT,
                        negative_prompt=self.NEGATIVE,
                        image=image, mask_image=mask_image, masked_image_latents=self.masked_latents(image, mask_image),
                        height=S, width=S, strength=strength, guidance_scale=self.GUIDANCE, num_inference_steps=steps,
                        generator=self.torch.Generator("cpu").manual_seed(seed),
                        callback_on_step_end=cb, callback_on_step_end_tensor_inputs=inputs).images[0]
        return out.resize(src.size, Image.LANCZOS)

    def _hold(self, cb, image, region, seed, steps):
        """The step callback `cb`, which also puts the latents of `region` back on `image`'s — noised to the next
        step's level — after each of the first SDXL_HOLD of the steps. The pre-fill's latents are encoded once per
        removal (same image for every variant)."""
        import hashlib
        torch, pipe = self.torch, self.pipe
        S = image.width
        key = hashlib.sha1(image.tobytes()).digest()
        if self.held[0] != key:
            x = pipe.image_processor.preprocess(image, height=S, width=S).to(pipe.device, pipe.vae.dtype)
            with torch.no_grad():
                self.held = (key, pipe.vae.encode(x).latent_dist.mode() * pipe.vae.config.scaling_factor)
        lat = self.held[1]
        noise = torch.randn(lat.shape, generator=torch.Generator("cpu").manual_seed(seed + 1)).to(lat.device, lat.dtype)
        k = np.asarray(Image.fromarray(region.astype(np.uint8) * 255).resize((S // 8, S // 8), Image.BILINEAR))
        km = torch.from_numpy(k.astype(np.float32) / 255.0).to(lat.device, lat.dtype)[None, None]
        last = int(round(SDXL_HOLD * steps))

        def held(p, i, t, kw):
            out = cb(p, i, t, kw)
            if i + 1 < last:
                # DPM++'s add_noise noises to the scheduler's current step: after step i that is step i + 1
                ref = p.scheduler.add_noise(lat, noise, p.scheduler.timesteps[i + 1:i + 2])
                out = dict(out, latents=km * ref + (1 - km) * kw["latents"])
            return out
        return held

    def unload(self):
        del self.pipe
        _free_gpu()


class RORem(SDXL):
    """RORem (CVPR 2025, PolyU and OPPO; its RORem-mixed release, 512 and 1024 px): SDXL Inpainting retrained only to
    remove, on removals people checked by hand. Only its UNet differs: its text encoders and VAE are SDXL Inpainting's
    (checked tensor by tensor), so it runs in SDXL's pipeline with SDXL's files, with everything SDXL does here
    (upright, 12 DPM++ steps at 1024 px, the held sky). Its authors' settings: their prompt, no classifier-free
    guidance — ~1 s less per variant than SDXL, the same fills as with SDXL's prompt and guidance, measured.
    Where SDXL drew a person back (one of two people side by side, a woman's bag left outside the selection) or odd
    things (an owl next to a backpack), in 11 variants of 12, RORem drew none in 12 (nor in 18 more, with SDXL's
    settings or at 512 px). On a pole across a floor it left a seam and the pole's base as a smudge, and up a path it
    drew a rock face: SDXL stays the default.
    Licence: Apache-2.0, on SDXL Inpainting's CreativeML Open RAIL++-M (commercial use allowed)."""
    name = "RORem"
    PROMPT, NEGATIVE, GUIDANCE = ROREM_PROMPT, None, 1.0
    # no typed text, from any door (window, --auto, MCP): without guidance it would barely steer the fill, and RORem
    # was measured with its authors' prompt alone; the window's field says so (ui.PROMPT_MODE)
    TEXT = False

    def __init__(self, log=print):
        super().__init__(log, unet=mf.part_dir("rorem") / "unet")


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
        self.torch, self.dev, self.repo = torch, dev, mf.part_dir("FLUX.1-Fill-dev")
        gg = mf.part_dir("gguf")
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
        lora = mf.part_dir("flux-turbo-alpha") / mf.TURBO_WEIGHTS  # alimama Turbo-Alpha
        if lora.exists():  # Turbo-Alpha: same quality in half the steps
            try:
                self.pipe.load_lora_weights(str(lora.parent), weight_name=lora.name, adapter_name="turbo")
                self.steps, self.turbo = FLUX_TURBO_STEPS, True
            except Exception as e:
                log(f"FLUX: Turbo LoRA not loaded ({type(e).__name__}: {str(e)[:120]}), using {FLUX_STEPS} steps")
        self.proj_flux = self.proj_osor = None  # output layers of FLUX and of OSOR (once OSOR is loaded)
        log(f"FLUX ready ({dev}, {self.quant}, {self.steps} steps{' turbo' if self.turbo else ''})")

    def embeddings(self, prompt, log=print, tokens=256):
        import hashlib
        torch = self.torch
        d = MODELS / "flux_prompts"  # in the install's models, also when FLUX is in the user's own folder
        d.mkdir(parents=True, exist_ok=True)
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
        state = torch.load(mf.part_dir("osor") / mf.OSOR_WEIGHTS, map_location="cpu", weights_only=True)
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
             progress=None, log=print, strength: float = 1.0, size: int = None) -> Image.Image:
        """strength < 1: src's hole holds a fill to redraw (its layout stays, its detail is drawn anew). size: one of
        FLUX_SIZES (default: the one nearer src's)."""
        torch = self.torch
        steps = steps or self.steps
        p = f"{prompt}, {DEFAULT_PROMPT}" if prompt else DEFAULT_PROMPT
        emb = self.embeddings(p, log)
        # only two working sizes, both square: ROCm compiles GPU kernels (the VAE decoder above all) the first time it
        # meets a size — minutes — and caches them; with any multiple of 16 nearly every new area paid that again.
        # Oblong sizes (1024 x 512) were also slower per step than 768 x 768 once compiled, measured
        S = size or (FLUX_SIZES[0] if src.width <= (FLUX_SIZES[0] + FLUX_SIZES[1]) // 2 else FLUX_SIZES[1])
        out = self.pipe(prompt_embeds=emb["prompt_embeds"].to(self.dev, torch.bfloat16),
                        pooled_prompt_embeds=emb["pooled"].to(self.dev, torch.bfloat16),
                        image=src.resize((S, S), Image.LANCZOS),
                        mask_image=mask.resize((S, S), Image.NEAREST).filter(ImageFilter.MaxFilter(9)),
                        height=S, width=S, guidance_scale=30.0, num_inference_steps=steps, strength=strength,
                        generator=torch.Generator("cpu").manual_seed(seed),
                        callback_on_step_end=_step_callback(progress, max(1, int(steps * strength)))).images[0]
        # give the cached blocks back: with ~10 GB at the peak, leftovers from one variant make the next one
        # spill into shared memory (3-10x slower)
        _free_gpu()
        return out.resize(src.size, Image.LANCZOS)

    def unload(self):
        del self.pipe
        _free_gpu()


# ------------------------------------------------------------------------------------------------ Qwen-Image 2.1
_QWEN_LAYERS = None


def _qwen_layers():
    """(FP8Linear, InRAM) for Qwen3-VL. FP8Linear: nn.Linear stored as FP8 (e4m3) with one scale per 128 x 128 block —
    the format of Qwen's FP8 releases — and computed in bfloat16: half the memory of bf16 weights, and no FP8
    arithmetic needed on the GPU."""
    global _QWEN_LAYERS
    if _QWEN_LAYERS is None:
        import torch

        class FP8Linear(torch.nn.Module):
            def __init__(self, weight, scale):
                super().__init__()
                self.register_buffer("weight", weight)
                self.register_buffer("scale", scale)

            def forward(self, x):
                o, i = self.weight.shape
                w = self.weight.to(x.dtype)
                if o % 128 == 0 and i % 128 == 0:  # every layer of Qwen3-VL-8B: one temporary, not a scale matrix too
                    w = (w.view(o // 128, 128, i // 128, 128) * self.scale.to(x.dtype)[:, None, :, None]).view(o, i)
                else:
                    w = w * self.scale.to(x.dtype).repeat_interleave(128, 0)[:o].repeat_interleave(128, 1)[:, :i]
                return torch.nn.functional.linear(x, w)

        class InRAM(torch.nn.Module):
            """A token embedding (ids -> vectors) or an output head (vector -> logits) kept in RAM: 1.2 GB each that
            the GPU does not need — a lookup, and the head only for the last token while generating."""
            def __init__(self, weight, head):
                super().__init__()
                self.w, self.head = weight, head  # a plain attribute: .to(device) leaves it in RAM

            def forward(self, x):
                if self.head:
                    return torch.nn.functional.linear(x.to("cpu", self.w.dtype), self.w).to(x.device)
                return torch.nn.functional.embedding(x.cpu(), self.w).to(x.device)
        _QWEN_LAYERS = FP8Linear, InRAM
    return _QWEN_LAYERS


def _qwen_text_encoder(dev):
    """Qwen3-VL-8B-Instruct from Qwen's FP8 files onto the GPU (~8 GB): FP8 layers stay FP8, the rest is bfloat16,
    the token embedding and the output head stay in RAM (te.lm_head is the identity: the pipeline reads hidden states;
    te.head is the real one, for naming). Read through RAM: safetensors straight onto the GPU stalled on ROCm/Windows.
    Its peak is what decides the card: with the head and the embedding on the GPU (~12 GB) next to what the desktop
    keeps there, an RX 7800 XT spilled into shared memory and the reading took 50 s instead of 15."""
    import json
    from contextlib import ExitStack
    import torch
    from accelerate import init_empty_weights
    from accelerate.utils import set_module_tensor_to_device
    from safetensors import safe_open
    from transformers import Qwen3VLConfig, Qwen3VLForConditionalGeneration
    d = mf.part_dir("qwen3-vl-8b-fp8")
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    cfg.pop("quantization_config", None)  # loaded here, not by transformers (its FP8 path wants FP8 maths)
    with init_empty_weights():
        te = Qwen3VLForConditionalGeneration._from_config(Qwen3VLConfig.from_dict(cfg), dtype=torch.bfloat16)
    where = json.loads((d / "model.safetensors.index.json").read_text(encoding="utf-8"))["weight_map"]
    fp8, in_ram = _qwen_layers()
    ram = {"lm_head.weight": ("lm_head", True), "model.language_model.embed_tokens.weight":
           ("model.language_model.embed_tokens", False)}
    with ExitStack() as stack:
        files = {f: stack.enter_context(safe_open(str(d / f), framework="pt", device="cpu"))
                 for f in sorted(set(where.values()))}
        for k, f in where.items():
            if k.endswith("_scale_inv"):
                continue
            if k in ram:
                parent, child = ram[k][0].rpartition(".")[::2]
                setattr(te.get_submodule(parent) if parent else te, child,
                        in_ram(files[f].get_tensor(k).to(torch.bfloat16), ram[k][1]))
                continue
            t = files[f].get_tensor(k).to(dev)
            if k + "_scale_inv" in where:
                parent, child = k[:-len(".weight")].rsplit(".", 1)
                scale = files[where[k + "_scale_inv"]].get_tensor(k + "_scale_inv").to(dev)
                setattr(te.get_submodule(parent), child, fp8(t, scale))
            else:
                set_module_tensor_to_device(te, k, dev, value=t.to(torch.bfloat16) if t.is_floating_point() else t)
    te.head, te.lm_head = te.lm_head, torch.nn.Identity()
    return te.to(dev).eval()


class Qwen:
    """Qwen-Image-2.1-Turbo (Alibaba, 2026): a 7B image model that generates and edits at up to 2048 px, distilled to
    8 steps, run here in 4 (QWEN_SIGMAS). Its transformer is GGUF-quantized (~4.2 GB at Q4_K_M); its text encoder,
    Qwen3-VL-8B (~8 GB on the GPU in FP8), reads the prompt and the condition pictures together. The two don't fit on a 16 GB card at once: the encoder runs once per
    removal while the transformer waits in RAM, then is freed.

    It has no inpainting mode, so a removal is an edit: Qwen3-VL first names what is selected ("the woman and her
    handbag"), then the transformer is told to remove that, seeing the photo and the hole as a second picture. Told only
    to fill a grey hole, or to remove "what the mask marks", it drew a person back into a person-shaped hole or copied
    the object. Outside the hole the latents are held on the photo's at every step (QWEN_LOCK). One latent is 16 x 16
    px: its working size of 1024 px is 1.8x FLUX's 768.
    Licence: Qwen Research License, NON-commercial (like FLUX.1 Fill dev). Qwen3-VL: Apache 2.0."""
    name = "Qwen"

    def __init__(self, log=print):
        dev = device()
        import torch
        from diffusers import (FlowMatchEulerDiscreteScheduler, GGUFQuantizationConfig, QwenImage21Pipeline,
                               QwenImage21Transformer2DModel)
        from diffusers.quantizers.gguf.utils import GGUFLinear, GGUFParameter, dequantize_gguf_tensor
        from diffusers.utils import logging as dl
        from transformers.utils import logging as hf_logging
        dl.set_verbosity_error()
        hf_logging.set_verbosity_error()
        self.torch, self.dev, self.repo = torch, dev, mf.part_dir("qwen-image-2.1-turbo")
        gg = mf.part_dir("qwen-image-2.1-turbo-gguf")
        self.quant = next(q for q in mf.QWEN_QUANTS if (gg / mf.QWEN_GGUF.format(q)).exists())
        tr = QwenImage21Transformer2DModel.from_single_file(
            str(gg / mf.QWEN_GGUF.format(self.quant)),
            quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16), config=str(self.repo),
            subfolder="transformer", torch_dtype=torch.bfloat16)
        # diffusers dequantizes GGUF weights only inside Linear layers; a bf16 norm weight (txt_in.text_norm) would
        # stay raw bytes
        for mod in tr.modules():
            if not isinstance(mod, GGUFLinear):
                for n, p in list(mod.named_parameters(recurse=False)):
                    if isinstance(p, GGUFParameter):
                        setattr(mod, n, torch.nn.Parameter(dequantize_gguf_tensor(p).to(torch.bfloat16),
                                                           requires_grad=False))
        self.pipe = QwenImage21Pipeline.from_pretrained(self.repo, transformer=tr, text_encoder=None,
                                                        torch_dtype=torch.bfloat16).to(dev)
        self.pipe.set_progress_bar_config(disable=True)
        # QWEN_SIGMAS shifted by the picture's size (Turbo's own 8 are fixed)
        self.pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(self.pipe.scheduler.config,
                                                                          use_dynamic_shifting=True)
        # the VAE in 512 px tiles: a 1024 px decode in one piece peaks at ~11 GB, which spills the card's memory
        self.pipe.vae.enable_tiling(512, 512, 384, 384)
        self.cond = {}  # key -> condition of the last removals (squares of an oblong area): the encoder runs once
        self.names = {}  # key -> what Qwen3-VL saw in an oblong area's selection (named once, for all its squares)
        self.what = None  # what Qwen3-VL saw in the last removal's selection
        self.drawn = None  # (width, height) the last fill was drawn at
        log(f"Qwen-Image ready ({dev}, {self.quant}, {len(QWEN_SIGMAS)} steps)")

    def _latents(self, img):
        """An RGB(A) PIL image -> its packed, normalized latents (1, tokens, 64)."""
        pipe = self.pipe
        x = pipe.image_processor.preprocess(img.convert("RGBA"), width=img.width, height=img.height).unsqueeze(2)
        z = pipe._encode_vae_image(x.to(self.dev, pipe.vae.dtype), None)
        return pipe._pack_latents(z, 1, z.shape[1], z.shape[3], z.shape[4])

    @staticmethod
    def _inputs(src, mask, S):
        """The picture and the (grown) hole the transformer works on: S px on the short side (qwen_dims)."""
        size = qwen_dims(*src.size, S)
        return (src.convert("RGB").resize(size, Image.LANCZOS),
                mask.resize(size, Image.NEAREST).filter(ImageFilter.MaxFilter(9)))

    def _name(self, te, image, hole):
        """What is selected, in a few words, asked to Qwen3-VL with the selection outlined in red. A red tint over a
        thin pole in front of columns was named "the column base"; outlined, "the floor lamp"."""
        from scipy import ndimage as ndi
        torch, proc = self.torch, self.pipe.processor
        f = QWEN_NAME_SIZE / max(image.size)  # an oblong area keeps its shape
        S = (round(image.width * f), round(image.height * f))
        shown = np.array(image.resize(S, Image.LANCZOS))
        m = np.asarray(hole.resize(S, Image.NEAREST)) > 127
        shown[ndi.binary_dilation(m, iterations=3) & ~ndi.binary_erosion(m)] = (255, 0, 0)
        shown = Image.fromarray(shown)
        msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": QWEN_ASK}]}]
        inputs = proc(text=[proc.apply_chat_template(msgs, add_generation_prompt=True)], images=[shown],
                      return_tensors="pt").to(self.dev)
        te.lm_head = te.head  # logits, for the last token only (generate asks for no more)
        try:
            with torch.no_grad():
                ids = te.generate(**inputs, max_new_tokens=16, do_sample=False)
        finally:
            te.lm_head = torch.nn.Identity()
        what = proc.batch_decode(ids[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
        what = (what.splitlines()[0].strip(" .\"'") if what else "") or "the object"  # quotes or dots alone: no name
        return what[0].lower() + what[1:] if what.split(" ", 1)[0] in ("The", "A", "An") else what

    def _key(self, image, hole, prompt, what=None):
        """The cache key of a condition: its pictures, the prompt and the name given for it (None: its own)."""
        import hashlib
        return hashlib.sha1(image.tobytes() + hole.tobytes() + prompt.encode("utf-8") + b"\0"
                            + (what or "").encode("utf-8")).digest()

    def condition(self, image, hole, prompt, log=print, what=None):
        """Prompt embeddings, image-slot mask, latents and latent shapes of the condition pictures, once per removal
        (the same for every variant). A prompt names what to remove (when Qwen3-VL got it wrong); without one
        Qwen3-VL names it in this picture, or `what` is the name it gave the whole area (Qwen.prepare)."""
        key = self._key(image, hole, prompt, what)
        if key not in self.cond:
            self._read([(image, hole, what)], prompt, log)
        *cond, self.what = self.cond[key]
        return cond

    def _read(self, jobs, prompt, log, name=None):
        """One encoder session: the transformer waits in RAM while Qwen3-VL is brought to the GPU (~5-7 s) and
        names the selection in `name` (image, hole) when given, then reads each job (image, hole, what) into
        self.cond; what None: the name read in `name`, else named in its own picture. Returns the name read in
        `name`."""
        import time
        torch, pipe = self.torch, self.pipe
        t0 = time.time()
        pipe.transformer.to("cpu")
        _free_gpu()
        named, read = None, []
        try:
            te = pipe.text_encoder = _qwen_text_encoder(self.dev)
            if name is not None:
                named = self._name(te, *name)
            for image, hole, what in jobs:
                key = self._key(image, hole, prompt, what or named)
                what = prompt.strip() or what or named or self._name(te, image, hole)
                # an oblong area's pictures have as many pixels as a square's: the transformer's cache of them (read at
                # every step) stays as large, while the area itself is drawn with QWEN_SIZE on its short side
                C, M = min(*image.size, QWEN_COND_SIZE), QWEN_MASK_SIZE
                photo = image.resize(qwen_dims(*image.size, C, area=True), Image.LANCZOS)
                images = [photo] + ([Image.merge("RGB", [hole.resize(qwen_dims(*hole.size, M, area=True),
                                                                      Image.BILINEAR)] * 3)] if M else [])
                text = QWEN_REMOVE.format(what=what)
                with torch.no_grad():
                    pe, _mask, slots = pipe._get_qwen_prompt_embeds(text, [im.convert("RGBA") for im in images],
                                                                    self.dev)
                read.append((key, images, pe, slots, what))
        finally:
            pipe.text_encoder = te = None  # no reference left: ~8 GB to give back before the transformer returns
            _free_gpu()
            pipe.transformer.to(self.dev)
        f = pipe.vae_scale_factor
        keep = max(0, 4 - len(read))  # the last removals' conditions stay, and all of this one's squares
        self.cond = dict(list(self.cond.items())[max(0, len(self.cond) - keep):]) if keep else {}
        for key, images, pe, slots, what in read:
            with torch.no_grad():
                lat = torch.cat([self._latents(im) for im in images], dim=1)
            _free_gpu()
            shapes = [(1, im.height // f, im.width // f) for im in images]
            self.cond[key] = (pe.to(torch.bfloat16), slots, lat, shapes, what)
        if read:
            n = f" ({len(read)} squares)" if len(read) > 1 else ""
            log(f"Qwen-Image: {QWEN_REMOVE.format(what=read[-1][-1])!r}, read in {time.time() - t0:.1f}s{n}")
        else:
            log(f"Qwen-Image: named {named!r} in {time.time() - t0:.1f}s")
        return named

    def prepare(self, area, mask, squares, prompt, log=print, size=None):
        """A removal filled in squares (an area longer than a square): what is selected is named once, in the whole
        area. Square by square, each one was named for what was left in it ("the woman with a bag", then "the
        woman with a handbag"), and each square that sees the earlier squares' fill took its own encoder session
        (~15 s) in every variant. Here each square's condition picture is the area as it is, not the earlier
        squares' fill, so it is the same for every variant: one encoder session per removal reads them all.
        Outside its hole a square still follows the squares filled before it (QWEN_LOCK).
        area, mask: PIL, upright; squares: [(image, mask)], crops of the area as it is. Returns the name, for
        Qwen.fill(what=)."""
        S = size or QWEN_SIZE
        f = S / max(area.size)
        size = (round(area.width * f), round(area.height * f))
        whole = area.convert("RGB").resize(size, Image.LANCZOS)
        hole = mask.resize(size, Image.NEAREST).filter(ImageFilter.MaxFilter(9))
        nkey = self._key(whole, hole, "")
        what = prompt.strip() or self.names.get(nkey)
        jobs = [self._inputs(img, m, S) + (what,) for img, m in squares]
        missing = [j for j in jobs if what is None or self._key(j[0], j[1], prompt, what) not in self.cond]
        if missing:
            named = self._read(missing, prompt, log, name=None if what else (whole, hole))
            if what is None:
                what = named
                self.names = dict(list(self.names.items())[-7:])
                self.names[nkey] = named
        self.what = what
        return what

    def fill(self, src: Image.Image, mask: Image.Image, prompt: str, seed: int, progress=None, log=print,
             size: int = None, seen: Image.Image = None, what: str = None) -> Image.Image:
        """In the shape of src (S px on its short side, qwen_dims): an oblong area in one pass, without squares.
        seen: the condition picture when it is not src (a square of an oblong area: the area as it is, while src
        has the earlier squares' fill); what: the selection's name (Qwen.prepare)."""
        torch, pipe, dev = self.torch, self.pipe, self.dev
        from diffusers.models.transformers.transformer_qwenimage21 import QwenImage21KVCache
        from diffusers.pipelines.qwenimage21.pipeline_qwenimage21 import calculate_shift, retrieve_timesteps
        S = size or QWEN_SIZE
        image, hole = self._inputs(src, mask, S)
        self.drawn = image.size
        pe, slots, cond_lat, shapes = self.condition(image if seen is None else self._inputs(seen, mask, S)[0], hole,
                                                     prompt, log, what)
        f = pipe.vae_scale_factor
        Lh, Lw = image.height // f, image.width // f
        g = torch.Generator("cpu").manual_seed(seed)
        with torch.no_grad():
            eps = torch.randn((1, 1, 64, Lh, Lw), generator=g)
            noise = pipe._pack_latents(eps, 1, 64, Lh, Lw).to(dev, torch.bfloat16)
            z0 = self._latents(image) if QWEN_LOCK else None
            # a latent is free where any pixel of its 16 x 16 cell is in the (grown) hole
            k = torch.from_numpy(np.asarray(hole) > 127).float()[None, None]
            free = torch.nn.functional.max_pool2d(k, f).reshape(1, Lh * Lw, 1).to(dev, torch.bfloat16)
            _free_gpu()
            sc = pipe.scheduler.config
            mu = calculate_shift(Lh * Lw, sc.get("base_image_seq_len", 256), sc.get("max_image_seq_len", 4096),
                                 sc.get("base_shift", 0.5), sc.get("max_shift", 1.15))
            timesteps, n = retrieve_timesteps(pipe.scheduler, None, dev, sigmas=list(QWEN_SIGMAS), mu=mu)
            pipe.scheduler.set_begin_index(0)
            slots = torch.cat([slots, slots.new_ones(1, Lh * Lw // 4)], dim=1)
            cache = QwenImage21KVCache(len(pipe.transformer.transformer_blocks))
            latents = noise
            for i, t in enumerate(timesteps):
                v = pipe.transformer(hidden_states=torch.cat([cond_lat, latents], dim=1),
                                     timestep=t.expand(1).to(torch.bfloat16) / 1000, encoder_hidden_states=pe,
                                     img_shapes=[shapes + [(1, Lh, Lw)]], img_mask=slots, kv_cache=cache,
                                     kv_cache_mode="extract" if i == 0 else "cached", return_dict=False)[0]
                latents = pipe.scheduler.step(v[:, -Lh * Lw:], t, latents, return_dict=False)[0]
                if i == 0:  # the first step ran the whole sequence (text, pictures, target): give its memory back
                    _free_gpu()
                if z0 is not None:
                    s = pipe.scheduler.sigmas[i + 1].to(dev, torch.bfloat16)
                    latents = free * latents + (1 - free) * ((1 - s) * z0 + s * noise)
                if progress:
                    progress(i + 1, n)
            del cache
            _free_gpu()
            vae = pipe.vae
            z = pipe._unpack_latents(latents, image.height, image.width, f).to(vae.dtype)
            mean = torch.tensor(vae.config.latents_mean).view(1, -1, 1, 1, 1).to(dev, z.dtype)
            std = torch.tensor(vae.config.latents_std).view(1, -1, 1, 1, 1).to(dev, z.dtype)
            out = vae.decode(z * std + mean, return_dict=False)[0][:, :, 0]
            out = pipe.image_processor.postprocess(out, output_type="pil")[0].convert("RGB")
        _free_gpu()
        return out.resize(src.size, Image.LANCZOS)

    def unload(self):
        del self.pipe
        self.cond = {}
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
        code = str(mf.part_dir("objectclear/code"))
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
            str(mf.part_dir("objectclear")), torch_dtype=dt, variant="fp16", apply_attention_guided_fusion=True).to(dev)
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
