"""The icon's tone source: a raccoon portrait from FLUX.1 Fill [dev] (full mask on a blank canvas = plain generation)
with the "Perfect Ink Drawing (Engraving Style)" LoRA (trigger 1NK_H4TCH1NG, openrail++). Its fine stipple is not
used as such: engrave_lines.py redraws it with clean lines from its tones.

Runs with an AI Remove install that has FLUX (AIREMOVE_HOME, default ~/AIRemove), the LoRA in
<install>/models/loras/perfect-ink-engraving:

    ~/AIRemove/venv/bin/python flux_ink.py OUTDIR first_seed count lora_weight [steps]
"""
import os
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("AIREMOVE_HOME") or Path.home() / "AIRemove").expanduser()
sys.path.insert(0, str(HOME / "airemove"))
import engines  # noqa: E402
import system  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

out, seed0, n, wt = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
steps = int(sys.argv[5]) if len(sys.argv) > 5 else 12
os.makedirs(out, exist_ok=True)
P = 768
LORA = HOME / "models" / "loras" / "perfect-ink-engraving"
PROMPT = ("App icon: a raccoon, head and shoulders portrait, facing the viewer with an alert gaze, ears up, black "
          "bandit mask around the eyes, on a flat golden yellow background. 1NK_H4TCH1NG, engraving style, clean ink "
          "drawing: evenly spaced parallel hatching lines that follow the form and only describe the shading, crisp "
          "black ink contour, cream paper, no messy marks, like a postage stamp engraving. Exactly three colours: "
          "black ink, cream paper, golden yellow.")
canvas = Image.new("RGB", (P, P), (245, 197, 24))
mask = Image.new("L", (P, P), 255)

eng = engines.FLUX(print)
eng.pipe.load_lora_weights(str(LORA), weight_name="perfect-ink-drawing-engraving-style.safetensors", adapter_name="ink")
eng.pipe.set_adapters(["turbo", "ink"], adapter_weights=[1.0, wt])
emb = eng.embeddings(PROMPT, print)
for s in range(seed0, seed0 + n):
    t0 = time.time()
    im = eng.pipe(prompt_embeds=emb["prompt_embeds"].to(eng.dev, torch.bfloat16),
                  pooled_prompt_embeds=emb["pooled"].to(eng.dev, torch.bfloat16),
                  image=canvas, mask_image=mask, height=P, width=P, guidance_scale=30.0,
                  num_inference_steps=steps, generator=torch.Generator("cpu").manual_seed(s)).images[0]
    im.save(os.path.join(out, f"ink-{wt:g}-{s:03d}.png"))
    print(f"seed {s}: {time.time() - t0:.0f}s", flush=True)
    engines._free_gpu()
system.hard_exit(0)
