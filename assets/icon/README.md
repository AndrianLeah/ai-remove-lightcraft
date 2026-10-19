# AI Remove icon

A **raccoon**, frontal head-and-shoulders portrait with an alert gaze. Its black "bandit mask" recalls LightCraft's
masks, and it is the thief that takes things out of the picture.

It is drawn in the style of the Crafting Apps icons:

- an engraving, like a postage stamp;
- the animal in paper, with ink line work and a crisp ink contour;
- a full-bleed colour field;
- no roundel or border.

It is not an ArtCraft mark and uses none of them.

## Palette (exactly three colours)

| Colour | Hex | Used for |
|---|---|---|
| Ink | `#0b0b0c` | line work, the mask, the contour |
| Paper | `#efe9dc` | the animal |
| AI Remove yellow | `#f5c518` | the field |

## Geometry

The icon is drawn on `viewBox="0 0 512 512"`, as a rounded-square tile with `rx=112`, clipped.

- **macOS** files add Apple's transparent margin (an 824/1024 body).
- **Windows and Linux** files use the full-bleed tile.

## How it was made

1. **Tone.** A raccoon portrait was generated locally with FLUX.1 Fill [dev] (GGUF Q4_K_S + Turbo-Alpha) and the
   "Perfect Ink Drawing (Engraving Style)" LoRA (openrail++). This is `source/flux-raccoon.png`, made by
   `source/flux_ink.py`. Its fur is a fine stipple, so it is used **only for its tones**.
2. **Figure.** SAM 3 cut the figure out (`source/sam_mask.py`). It was then cropped tight, as in the family:
   - ears near the top;
   - shoulders leaving the bottom edge.

   The results are `source/tone.png` and `source/mask.png`.
3. **Engraving.** `source/engrave_lines.py` draws the hatching, the way the Crafting Apps icons use lines: for
   shadow and depth only.

   - The lit parts stay clean paper: the white muzzle, the brows and the rims of the ears.
   - The head turns into shadow towards its outline, so the lines gather on its flanks and give it volume.
   - The lines are evenly spaced streamlines (Jobard–Lefer). They grow out of the middle of the nose like fur and bend
     with the shading's isophotes.
   - Each line swells in the shadows and breaks off as the tone lightens.

   It also adds:

   - solid ink for the mask, eyes and ear hollows, with the eye glints kept in paper;
   - the ink contour;
   - shoulders that flare out to the edge.

   The mouth and the nose are drawn, not left to the hatching: the fur lines would just meet at a point under the
   nose. Their shapes are in `source/features.txt`:

   - line 1: the mouth strokes (philtrum and lips); the hatching stops short of them;
   - line 2: the shine on the nose;
   - line 3: the nose outline.

   The result is `source/engraved-2048.png`. The command used (the last three numbers are: lighter than 0.55 stays
   paper, rim shadow 0.45, width curve 1.0):

   ```bash
   python engrave_lines.py tone.png mask.png engraved-2048.png 9 0.16 5 0.501,0.554 0.35 0.62 0.10 \
     "$(sed -n 1p features.txt)" 6.5 "$(sed -n 2p features.txt)" 0.52 "$(sed -n 3p features.txt)" 0.55 0.45 1.0
   ```

4. **Vector.** VectorCraft traced it with *Object > Image Trace*, logo mode, with the three colours as logo colours.
5. **Tile.** `source/round_svg.py` and `source/assemble_icon.py` put the trace into the 512 tile, giving
   `airemove.svg`. `airemove.vectorcraft` is that file, as the editable VectorCraft document.

## Regenerate the files

Edit `airemove.vectorcraft` in VectorCraft and export it as `airemove.svg`. Then run `python build_icons.py`. It needs
`pip install resvg-py pillow` and writes:

- the PNGs;
- `airemove.ico`;
- `airemove.icns`;
- `hicolor/`.
