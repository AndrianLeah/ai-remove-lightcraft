""""Draw something new" (generative fill) end to end, without LightCraft and without FLUX, for the CI runners:
tools/ci_smoke.py remove DIR runs this after ci_reflections.py, with the install's own Python (DIR: an install with LaMa
only).

The photo is ci_removal.py's synthetic raw DNG, a portrait one: LightCraft's export is turned 90 degrees, so the
sensor holds it on its side — what decides how FLUX sees an area. A stand-in for FLUX is put where the session keeps
the engine (engines.FLUX's embeddings() and fill()): it records what it is asked and draws horizontal stripes in the
hole of the picture it gets, which tells afterwards which way up it saw it. The rest is the app's own code: a removal
that draws ("Draw in the selection": Session.new_removal draw=True), its variants ("Fill 1"), the blend, "Save in
LightCraft" writing the fill into the sensor data, the project reopened.

Checks:
- a drawing removal has a square area, is of its own kind ("draw") and refuses an empty prompt;
- FLUX gets the prompt alone (none of the removal's words, in its fill and in the prompt encoded), the area upright
  (as the photo is seen), in one pass at full strength;
- the stripes come back across the photo's upright rows: drawn upright, turned back to the sensor's side;
- the blend adds no texture copied from around the hole, while a removal's one-pass fill still gets it;
- it gets no "Full detail", nor squares, and how much it is enlarged is recorded;
- a removal's FLUX fill is as before: the removal's words, the area on its side;
- saved, the fill is in the sensor data where the area is and nowhere far from it;
- the project keeps the drawing removal: reopened, it is of the "draw" kind again with its "Fill 1".
Exit status 1 at the first check that fails.

  ci_fill.py DIR [--keep FOLDER]    FOLDER: where the photo, base.png, the DNG and the project are left
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_removal as cr  # noqa: E402  (its synthetic raw, base.png, stand-in LightCraft, Session and checks)
from ci_removal import Failed, expect  # noqa: E402

PROMPT = "a wooden bench"
STRIPE = 12  # the stand-in's stripes: this many pixels high, across the picture it is given


class StandInFLUX:
    """engines.FLUX as the Session uses it: embeddings() and fill() recorded; fill() returns the picture with the hole
    (mask white) painted in horizontal stripes, light and dark, across the picture as it was given."""

    def __init__(self):
        self.encoded, self.calls = [], []

    def embeddings(self, prompt, log=print, tokens=256):
        self.encoded.append(prompt)

    def fill(self, src, mask, prompt, seed, steps=None, progress=None, log=print, strength=1.0, size=None,
             draw=False):
        self.calls.append({"src": np.asarray(src).copy(), "prompt": prompt, "draw": draw, "strength": strength,
                           "size": size})
        a = np.asarray(src.convert("RGB")).copy()
        hole = np.asarray(mask.convert("L")) > 127
        rows = (np.arange(a.shape[0]) // STRIPE) % 2 == 0
        a[hole & rows[:, None]] = (200, 150, 90)
        a[hole & ~rows[:, None]] = (60, 40, 30)
        return Image.fromarray(a)

    def unload(self):
        pass


def ellipse(size, box):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse(box, fill=255)
    return np.asarray(m) > 127


def run(d, out):
    sys.path.insert(0, str(d / "airemove"))
    import airemove as ar
    from rawdng import XYZD50_TO_SRGB

    ar.measured = lambda key, seconds: None  # the stand-in's times are not FLUX's: the install's estimates stay
    photos, work = out / "photos", out / "work"
    photos.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    photo, export, base_png = photos / "CI-0003.dng", work / "source.dng", work / "base.png"
    rgb = cr.scene()
    cfa0 = cr.write_raw(photo, rgb, XYZD50_TO_SRGB)
    shutil.copyfile(photo, export)
    cr.develop(rgb).save(base_png)
    lc = cr.StandIn(ar.LC)
    s = cr.session(ar, lc.lc, photo, export, base_png, work / "s1")
    expect(s.t[0] in (1, 3), f"a portrait photo: the sensor holds it on its side ({s.t})")
    flux = s.flux = StandInFLUX()
    textures = []
    seamless = ar.blend.seamless

    def recorded(*a, **k):
        textures.append(k.get("texture", True))
        return seamless(*a, **k)
    ar.blend.seamless = recorded

    # a drawing removal: square, its own kind, a prompt needed
    expect(ar.model_kind("fill") == "draw" and "fill" in ar.DRAW_MODELS, "\"fill\" is the model that draws")
    r = s.new_removal(ellipse(s.base.size, (120, 160, 240, 340)), draw=True)
    h, w = r.reg_mask.shape
    expect(r.fill and r.kind() == "draw" and h == w, f"a drawing removal, kind {r.kind()}, its area {w}x{h}: square")
    try:
        s.run_model(r, "fill", "   ")
        expect(False, "an empty prompt is refused")
    except ar.Fail as e:
        expect(not r.candidates and not flux.calls, f"an empty prompt is refused, nothing drawn ({e})")

    # the prompt alone, the area upright, one pass
    label, im = s.run_model(r, "fill", f"  {PROMPT} ")
    c = flux.calls[-1]
    expect(label == "Fill 1" and len(flux.calls) == 1, f"one pass, one variant: {label}")
    expect(c["prompt"] == PROMPT and c["draw"] and flux.encoded[-1] == PROMPT and ar.engines.DEFAULT_PROMPT not in
           " ".join(flux.encoded), f"FLUX gets the prompt alone: {c['prompt']!r}, encoded {flux.encoded[-1]!r}")
    expect(np.array_equal(c["src"], np.asarray(s._up(r.src))) and c["strength"] == 1.0 and c["size"] is None,
           "FLUX sees the area upright, as the photo is seen, at full strength in its own size")
    up = np.asarray(s._up(im)).astype(np.float64).mean(axis=2)
    inner = s._up(r.reg_mask.astype(np.uint8)) > 0
    from scipy import ndimage as ndi
    inner = ndi.binary_erosion(inner, iterations=8)
    dy = np.abs(np.diff(up, axis=0))[inner[1:] & inner[:-1]].mean()
    dx = np.abs(np.diff(up, axis=1))[inner[:, 1:] & inner[:, :-1]].mean()
    expect(dy > 5 * dx, f"the stripes come back across the photo's upright rows (steps {dy:.1f} down, {dx:.1f} across)")
    expect(textures[-1] is False, "the blend copies no texture from around the hole into what is drawn")
    expect(s.refine_check(r) == (False, "draw") and s.tile_plan(r, "fill") is None
           and s.tile_plan(r, "fill", refine=True) is None, "no \"Full detail\", no squares")
    f = s.enlarged(r, "fill")
    expect(abs(r.scale["Fill 1"] - f) < 1e-9 and f > 0, f"how much it is enlarged is recorded: {f:.2f}x")

    # a removal's FLUX fill, as before: the removal's words, the area on its side, texture in one pass
    r2 = s.new_removal(ellipse(s.base.size, (300, 520, 400, 620)))
    s.run_model(r2, "flux", "")
    c2 = flux.calls[-1]
    expect(r2.kind() == "remove" and not c2["draw"] and np.array_equal(c2["src"], np.asarray(r2.src))
           and flux.encoded[-1] == ar.engines.DEFAULT_PROMPT and textures[-1] is True,
           "a removal's FLUX fill is as before: the removal's words, the area on its side, texture added")

    # saved: the fill is in the sensor data, where the area is
    r.chosen = 0
    s.removals.remove(r2)
    dng, __, __ = s.write_all()
    raw = ar.RawDNG(str(dng))
    cfa = raw.cfa.copy()
    raw.close()
    y0, y1, x0, x1 = r.box
    changed = cfa != cfa0
    expect(changed[y0:y1, x0:x1].mean() > 0.05 and not changed[:max(0, y0 - 64)].any() and
           not changed[y1 + 64:].any(), f"saved: the fill is in the sensor data in its area "
                                        f"({changed[y0:y1, x0:x1].mean():.0%} of it), nothing far from it")

    # the project reopened
    s.save_project()
    s2 = cr.session(ar, lc.lc, photo, export, base_png, work / "s2")
    r3 = next((x for x in s2.removals if x.id == r.id), None)
    expect(r3 is not None and r3.fill and r3.kind() == "draw" and [lb for lb, __ in r3.candidates] == ["Fill 1"],
           "reopened, it draws again: kind \"draw\", its variant \"Fill 1\"")
    s2.close()
    s.close()
    ar.blend.seamless = seamless


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", help="install folder")
    ap.add_argument("--keep", help="leave the files in this folder")
    a = ap.parse_args()
    d = Path(a.dir).expanduser().resolve()
    out = Path(a.keep).resolve() if a.keep else Path(tempfile.mkdtemp(prefix="airemove-ci-"))
    print(f"fill {d} (files in {out})", flush=True)
    try:
        run(d, out)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    finally:
        if not a.keep:
            shutil.rmtree(out, ignore_errors=True)
    print("  ok   \"Draw something new\" end to end", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
