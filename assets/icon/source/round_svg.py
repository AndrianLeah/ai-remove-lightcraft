"""Round path coordinates to one decimal (inside d="..." only): round_svg.py IN OUT"""
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
def fix(m):
    d = re.sub(r"(-?\d+\.\d)\d+", r"\1", m.group(1))
    d = re.sub(r"(\d)\.0(?![\d])", r"\1", d)
    return 'd="' + d + '"'
s = re.sub(r'd="([^"]*)"', fix, s)
open(sys.argv[2], "w", encoding="utf-8").write(s)
