"""Raster icons from airemove.svg, like LightCraft's packaging/icons.sh: full-bleed tile for Windows and Linux,
Apple's transparent margin (an 824/1024 body) for macOS. Needs: pip install resvg-py pillow

The artwork: airemove.vectorcraft (VectorCraft) / airemove.svg; how it was made is in README.md.

  airemove-1024.png        store/docs size
  airemove-256.png         window icon (the AI Remove window uses it on every OS)
  airemove.ico             Windows (16-256 px): Start menu shortcut, LightCraft launcher
  airemove-macos-1024.png  macOS body with margin; airemove.icns from it
  hicolor/<n>x<n>/apps/airemove.png + hicolor/scalable/apps/airemove.svg   Linux icon theme

A photo's project (.airemove files), from airemove-project.svg (48 px and up) and airemove-project-small.svg (16-32
px), which source/project_icon.py makes from airemove.svg:

  airemove-project.ico     Windows (16-256 px): the file type's icon
  airemove-project.icns    macOS: the app's document type (copied into the app as project.icns)
  hicolor/<n>x<n>/mimetypes/airemove-project.png   Linux
The two SVGs are working files, like the .vectorcraft ones: the packages carry these outputs only.

  python build_icons.py [app] [project]   both when neither is given
"""
import io
import shutil
import sys
from pathlib import Path

import resvg_py
from PIL import Image

HERE = Path(__file__).resolve().parent
SVG = HERE / "airemove.svg"
PROJECT, PROJECT_SMALL = HERE / "airemove-project.svg", HERE / "airemove-project-small.svg"
SIZES = [16, 24, 32, 48, 64, 128, 256]  # .ico
THEME = (16, 24, 32, 48, 64, 128, 256, 512)  # hicolor


def render(size, svg=SVG):
    data = resvg_py.svg_to_bytes(svg_path=str(svg), width=size, height=size)
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def app_icons():
    big = render(1024)
    big.save(HERE / "airemove-1024.png")
    render(256).save(HERE / "airemove-256.png")
    # each size rendered from the vector (sharper than resampling one bitmap)
    frames = {s: render(s) for s in SIZES}
    frames[256].save(HERE / "airemove.ico", sizes=[(s, s) for s in SIZES],
                     append_images=[frames[s] for s in SIZES[:-1]])
    mac = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    body = render(824)
    mac.paste(body, (100, 100), body)
    mac.save(HERE / "airemove-macos-1024.png")
    mac.save(HERE / "airemove.icns")
    for s in THEME:
        d = HERE / "hicolor" / f"{s}x{s}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        render(s).save(d / "airemove.png")
    d = HERE / "hicolor" / "scalable" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SVG, d / "airemove.svg")


def project_icons():
    def draw(s):  # the page carries its own margin: no Apple one
        return render(s, PROJECT_SMALL if s <= 32 else PROJECT)
    frames = {s: draw(s) for s in SIZES}
    frames[256].save(HERE / "airemove-project.ico", sizes=[(s, s) for s in SIZES],
                     append_images=[frames[s] for s in SIZES[:-1]])
    # .icns holds 32 (16 pt on a Retina screen) to 1024: the small drawing at 32, the full one above
    draw(1024).save(HERE / "airemove-project.icns", append_images=[draw(s) for s in (32, 64, 128, 256, 512)])
    for s in THEME:  # PNGs only: a file's icon is never shown larger than 512 px, and the SVG is 1.2 MB
        d = HERE / "hicolor" / f"{s}x{s}" / "mimetypes"
        d.mkdir(parents=True, exist_ok=True)
        draw(s).save(d / "airemove-project.png")


def main():
    which = sys.argv[1:] or ["app", "project"]
    if "app" in which:
        app_icons()
    if "project" in which:
        project_icons()
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
