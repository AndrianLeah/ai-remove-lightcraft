"""Raster icons from airemove.svg, like LightCraft's packaging/icons.sh: full-bleed tile for Windows and Linux,
Apple's transparent margin (an 824/1024 body) for macOS. Needs: pip install resvg-py pillow

The artwork: airemove.vectorcraft (VectorCraft) / airemove.svg; how it was made is in README.md.

  airemove-1024.png        store/docs size
  airemove-256.png         window icon (the AI Remove window uses it on every OS)
  airemove.ico             Windows (16-256 px): Start menu shortcut, LightCraft launcher
  airemove-macos-1024.png  macOS body with margin; airemove.icns from it
  hicolor/<n>x<n>/apps/airemove.png + hicolor/scalable/apps/airemove.svg   Linux icon theme
"""
import io
import shutil
from pathlib import Path

import resvg_py
from PIL import Image

HERE = Path(__file__).resolve().parent
SVG = HERE / "airemove.svg"


def render(size):
    data = resvg_py.svg_to_bytes(svg_path=str(SVG), width=size, height=size)
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def main():
    big = render(1024)
    big.save(HERE / "airemove-1024.png")
    render(256).save(HERE / "airemove-256.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    # each size rendered from the vector (sharper than resampling one bitmap)
    frames = {s: render(s) for s in sizes}
    frames[256].save(HERE / "airemove.ico", sizes=[(s, s) for s in sizes],
                     append_images=[frames[s] for s in sizes[:-1]])
    mac = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    body = render(824)
    mac.paste(body, (100, 100), body)
    mac.save(HERE / "airemove-macos-1024.png")
    mac.save(HERE / "airemove.icns")
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        d = HERE / "hicolor" / f"{s}x{s}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        render(s).save(d / "airemove.png")
    d = HERE / "hicolor" / "scalable" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SVG, d / "airemove.svg")
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
