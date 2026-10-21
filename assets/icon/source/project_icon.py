"""The icon of a photo's project (.airemove files): a sheet of paper with a folded corner and the app's tile in the
middle, in the icon's three colours. Built from airemove.svg, so the raccoon is the same drawing.
  project_icon.py APP.svg OUT.svg [small] [face]
small: the version for 16-32 px, a thicker outline and a bigger tile (the fine lines of the full one vanish there);
face: the raccoon's face only in the tile."""
import re
import sys

INK, PAPER, FOLD = "#0b0b0c", "#efe9dc", "#d6ccb6"  # FOLD: the paper in the fold's shade


def build(app_svg, small=False, face=False):
    """face: the tile shows the raccoon's face only (eyes and mask, 1.8x), which still reads at 16 px."""
    s = open(app_svg, encoding="utf-8").read()
    tile = s[s.index('<g clip-path="url(#tile)">'):s.rindex("</svg>")]  # the field and the raccoon, clipped
    if face:  # the drawing's own group, enlarged around the eyes, inside the same clip
        tile = re.sub(r'<g transform="(scale\([^"]+)">',
                      r'<g transform="translate(256 236) scale(1.8) translate(-256 -236) \1">', tile, count=1)
    stroke, r = (30, 30) if small else (14, 20)  # outline, page corner radius
    x0, x1, y0, y1, fold = 72, 440, 16, 496, 104  # the page (512 grid), the fold's size
    side = 312 if small else 272  # the tile, centred under the fold
    tx, ty = (x0 + x1 - side) / 2, (y0 + fold + y1 - side) / 2 - (8 if small else 4)
    page = (f"M{x0 + r} {y0} H{x1 - fold} L{x1} {y0 + fold} V{y1 - r} Q{x1} {y1} {x1 - r} {y1} H{x0 + r} "
            f"Q{x0} {y1} {x0} {y1 - r} V{y0 + r} Q{x0} {y0} {x0 + r} {y0} Z")
    corner = f"M{x1 - fold} {y0} V{y0 + fold - r} Q{x1 - fold} {y0 + fold} {x1 - fold + r} {y0 + fold} H{x1} Z"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512" width="512" height="512">
<title>AI Remove project</title>
<defs><clipPath id="tile"><rect width="512" height="512" rx="112"/></clipPath></defs>
<path d="{page}" fill="{PAPER}" stroke="{INK}" stroke-width="{stroke}" stroke-linejoin="round"/>
<path d="{corner}" fill="{FOLD}" stroke="{INK}" stroke-width="{stroke}" stroke-linejoin="round"/>
<g transform="translate({tx:.1f} {ty:.1f}) scale({side / 512:.6f})">
{tile}</g>
</svg>
'''


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(build(sys.argv[1], small="small" in sys.argv[3:], face="face" in sys.argv[3:]))
    print("written", sys.argv[2])
