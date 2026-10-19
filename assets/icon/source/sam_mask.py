"""The figure's mask with SAM 3: the union of the largest hypothesis under each click.
Runs with an AI Remove install (AIREMOVE_HOME, default ~/AIRemove):

    ~/AIRemove/venv/bin/python sam_mask.py IN.png OUT.png "x,y;x,y"     (clicks as fractions of the image)
"""
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("AIREMOVE_HOME") or Path.home() / "AIRemove").expanduser()
sys.path.insert(0, str(HOME / "airemove"))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402
import engines  # noqa: E402
import system  # noqa: E402

im = Image.open(sys.argv[1]).convert("RGB")
sam = engines.SAM3(print)
sam.set_image(im)
W, H = im.size
fig = np.zeros((H, W), bool)
for c in sys.argv[3].split(";"):
    x, y = (float(v) for v in c.split(","))
    out, masks = sam._run([(x * W, y * H)], [1], multi=True)
    fig |= masks[int(np.argmax([m.sum() for m in masks]))].astype(bool)
fig = ndi.binary_fill_holes(ndi.binary_opening(fig, iterations=2))
Image.fromarray(fig.astype(np.uint8) * 255).save(sys.argv[2])
print(f"mask {fig.mean() * 100:.0f}%")
system.hard_exit(0)
