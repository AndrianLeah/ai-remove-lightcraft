"""Put a traced artwork (an SVG exported by VectorCraft, any size, square) into the icon tile: viewBox 0 0 512 512,
rounded square rx=112 that clips everything, the field colour full-bleed behind. assemble_icon.py TRACED.svg OUT.svg"""
import re
import sys
import xml.etree.ElementTree as ET

FIELD = "#f5c518"
src, dst = sys.argv[1], sys.argv[2]
ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
root = ET.parse(src).getroot()
vb = [float(v) for v in re.split(r"[ ,]+", root.get("viewBox").strip())]
s = 512.0 / max(vb[2], vb[3])
ns = "{http://www.w3.org/2000/svg}"
defs, body = [], []
for child in list(root):
    tag = child.tag.replace(ns, "")
    if tag == "defs":
        defs.append(ET.tostring(child, encoding="unicode"))
    elif tag not in ("title", "desc", "metadata"):
        body.append(ET.tostring(child, encoding="unicode"))
inner = "".join(body)
out = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512" width="512" height="512">
<title>AI Remove</title>
{"".join(defs)}
<defs><clipPath id="tile"><rect width="512" height="512" rx="112"/></clipPath></defs>
<g clip-path="url(#tile)">
<rect width="512" height="512" fill="{FIELD}"/>
<g transform="scale({s:.6f}) translate({-vb[0]:.3f} {-vb[1]:.3f})">{inner}</g>
</g>
</svg>
'''
out = out.replace(' xmlns="http://www.w3.org/2000/svg"', "", out.count(' xmlns="http://www.w3.org/2000/svg"') - 1) \
    if False else out
open(dst, "w", encoding="utf-8").write(out)
print("assembled", dst, f"scale {s:.4f}")
