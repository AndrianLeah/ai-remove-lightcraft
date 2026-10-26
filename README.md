<p align="center">
  <img src="assets/icon/airemove-256.png" width="128" alt="AI Remove icon: an engraved raccoon">
</p>

<h1 align="center">AI Remove for LightCraft and Chromaforge</h1>

Remove objects and people from photos with local AI, from inside [LightCraft](https://github.com/storytold/lightcraft)
or [Chromaforge](https://github.com/emmertex/lightcraft-classic), or on its own — like Lightroom's Generative Remove,
but on your own computer. From a RAW the result goes back into a **RAW DNG**, so you keep developing it like any raw
file. From a JPEG, PNG, TIFF, WebP, HEIC or AVIF it is a copy in the same format.

It works the same way in both apps, in one of them or in both at once: the installer asks which to set up (see
[LightCraft and Chromaforge](#lightcraft-and-chromaforge)).

[Italiano](README.it.md)

> AI Remove is an **unofficial** plug-in. It is not made, sponsored or endorsed by the ArtCraft team, who make
> LightCraft, nor by Chromaforge's contributors.

## How it works

1. In LightCraft or Chromaforge, select a photo and press **Ctrl+Shift+X** (**Cmd+Shift+X** on a Mac). On Windows the
   **AI Remove panel** opens beside the app's window and works on the mask you select in the app (see
   [The panel](#the-panel)). Its **Full window** button opens AI Remove's window, where the steps below happen. On
   macOS and Linux the window opens directly.
2. Click what should go: SAM 3 selects the whole object. Alt/Option+click takes a part out, Shift+click adds one, and
   the brush and eraser handle the rest. Or **describe** it: type "people" (in English) and SAM 3 selects every
   person in the photo, each on its own, so a right-click drops one you want to keep.
3. Select everything in one go, describing it as many times as you like ("person", then "bag", then "sign") and
   fixing it with the brush and eraser. To remove the objects' shadows or reflections too, press **Include the
   shadow**: it adds them to the selection, in blue.
4. **Split into parts** cuts the selection into parts sized for the models: things far apart (a person on the left, a
   sign on the right) become parts of their own, numbered on the photo, while a crowd or a person and their shadow
   stay one, as long as their area stays small enough for the models to draw it sharp (a crowd becomes several
   parts, filled one after another). Select each part, choose its model (the menu says what each one is good for, and
   what it is not for: FLUX Fill draws people back into a crowd) and press **Generate**, or **Generate all** for the
   rest. Pick the best variant of each. **Remove selection** does all of it at once, with one model for every part.
   On a long removal (a pole, a cable, a railing), **Full detail** redraws the chosen variant at the photo's own
   resolution.
5. **Save to LightCraft** or **Save to Chromaforge** (the button names the app the photo came from) writes
   `<name>-AIRemove.dng` (from a JPEG: `<name>-AIRemove.jpg`, and so on), stacked on the original with the same
   development.

**Reflections in glass.** For a photo through a shop window or a display case, choose **DAI** under *Remove
reflections* in the model menu and press **Remove reflections**: with nothing selected it works on the whole photo,
with a selection only there, fading out around it. Like Lightroom's Remove Reflections, it takes away the light the
glass reflects (the street seen in the window, the veil over what is behind it), and it takes it off the raw values
themselves: nothing is redrawn, every detail and the sensor's own noise stay. **Strength**, under the result, sets
how much of it goes (0 to 150 %, 75 % at first), and the photo follows as you drag it.

**Draw something new (generative fill).** Choose **Generative fill** under *Draw something new* in the model menu,
select where it goes, write what to draw in English ("a wooden bench", "a lemon tree in a terracotta pot", "white
clouds") and press **Draw in the selection**.
- **The model:** FLUX Fill draws it with the photo's light and focus.
- **The result:** it is written into the RAW like a removal's fill: a DNG that develops like the original.
- **The selection is the shape it fills:** for something that stands, select down to the ground, or it floats.
- **It draws no shadow on the ground.**
- **Large selections:** a large selection is drawn smaller than the photo and looks soft at 100 %. The note under the
  variant says how much; a smaller selection draws it sharper.

Every removal stays editable: regenerate it, pick another variant or delete it whenever you like. Everything lives in
one project file next to the photo (`<photo>.airemove`). The original is never modified.

**On its own.** AI Remove also works on a photo that is in neither app: open it from the Start menu, Applications or
the app menu with the apps closed (or no photo selected in them) and it asks for a file; **Open photo…** in the
window opens another one. **Save as DNG** (or **Save as JPEG**…) writes the result next to the photo, and nothing is
imported anywhere.
- **A RAW:** LightCraft or Chromaforge must be installed, not open. AI Remove reads the RAW through its command line,
  with its default development.
- **A JPEG, PNG, TIFF, WebP, HEIC or AVIF:** shown as it is, without either app.

**Ordinary pictures** keep what they had: the colour profile, the EXIF and the XMP. The EXIF loses only its small
embedded preview, which would still show what was removed.
- **JPEG** is saved with the original's own compression settings: pixels outside the removal move by a level or two,
  invisibly.
- **PNG, TIFF and lossless WebP** are saved losslessly; 16-bit TIFFs stay 16-bit.
- **HEIC** loses its depth map and other extra images.
- A 16-bit colour PNG, a CMYK picture or an animated one does not open (the message says what to do).

## The panel

On Windows, Ctrl+Shift+X opens a small panel attached to LightCraft's or Chromaforge's window. It removes, fills and
takes reflections away using the app's own masks, without leaving the app.

- **Where it sits:** docked at the app's right edge. It stays above the app, and only above it, and moves and minimizes
  with it. Drag it by its header to put it elsewhere: it opens there the next time. A double-click on the header docks
  it again, and **–** folds it. Ctrl+Shift+X again brings it forward.
- **The selection is the app's mask.** Select a mask in the app and the panel takes it. It can be an Object mask made
  with one click of the app's SAM 3, a brush, a gradient… In *Reflections* the panel works on the whole photo, as
  Lightroom's Remove Reflections does.
- **The window's tabs:**
  - **Remove** has the model menu, with ⓘ *What it does*;
  - **Fill** asks what to draw (required);
  - **Reflections** runs DAI, then *Strength* under the result.

  Enter generates, Esc stops, and ← → go through the variants.
- **The result shows on the photo in the app.** The chosen variant is drawn over the photo in the app's own view, as
  its Layout Image. This works while the photo is shown whole (Detail view, Fit, not cropping). Hold **Original**, or
  `\`, to compare.
- **One removal per mask.** Each mask keeps its variants while the panel is open, and *On this photo* lists them.
  **Save to LightCraft** (or Chromaforge) writes every chosen variant into one DNG, stacked on the original, and the
  next save updates it. The masks used as selections are not carried into the DNG.
- **Split into masks.** It turns a mask of several pieces, or of several Object clicks, into one mask per part in the
  app ("Distractions 1", "Distractions 2"…). Each part is then a selection with its own model. Objects close together
  stay in one mask, because each would show in the other's fill. One Undo in the app takes it back.
- **Full window** opens AI Remove's window on the same photo. It has the same removals and variants, and the models
  are already loaded. Use it for what the panel doesn't do: SAM 3 clicks, the brush, Describe, *Include the shadow*,
  *Split into parts*. **Back to the panel** returns with what you did there.
- **Prefer the window?** In the window, the language button at the top right (`EN ▾`) has *Ctrl+Shift+X in
  LightCraft opens the panel*: untick it. On macOS and Linux it starts unticked. Tick it there and the panel opens
  as an ordinary window beside the app.

The apps have no plug-in panels, so the panel is a window of its own over the app. It reads the app's state about
every second and a half. The preview on the photo is not drawn in these cases, and the panel says so:
- zoomed in, or while cropping;
- with a Geometry transform (Upright, perspective).

Save is not affected. The first time the panel reads a photo, the photo's crop disappears for a moment.

## Features

- **One-click selection** with SAM 3, refined with more clicks, a brush and an eraser.
- **Select by describing:** "people", "car", "sign" selects every instance at once, a crowd included. SAM 3 looks at
  the whole photo and at overlapping tiles of it, each near its own size, so people far away are found too (on a
  park photo: 98 people instead of 39; ~1–2 s on a GPU). Where two people touch, no strip between them is left out:
  like the apps' own Describe masks, each person's mask is joined by SAM 3's semantic mask where that person is the
  nearest.
- **Four fill models, each with a job.** LaMa: quick, on the processor, small things on plain backgrounds and
  cables. RORem (the default): people and objects, SDXL Inpainting retrained only to remove, so it draws no one back;
  commercial use allowed. FLUX.1 Fill [dev] with Turbo-Alpha: architecture and large areas, the most realistic, but
  not for people. Qwen-Image 2.1 (optional, 16 GB GPUs): people and objects on complex backgrounds; it first names
  everything selected ("the woman and her handbag"; what you described, such as "person", "bag", "umbrella", is
  named too), then removes it by name and redraws the scene behind it.
- **Remove reflections,** like Lightroom's: DAI (Dereflection Any Image, AAAI 2026) finds the light a pane of glass
  reflects over the photo, in a few seconds on a GPU, and AI Remove subtracts it from the RAW's own values, so the
  photo keeps all of its detail. **Strength**, a slider under the result, says how much of what DAI found goes,
  from 0 to 150 %, and the photo follows as you drag it. It starts at 75 %, which came closest to Lightroom's own
  result on a shop window (measured against the reflection Lightroom took away, which it stores in its `.acr` file).
- **Generative fill,** like Photoshop's, but into the RAW: FLUX Fill draws what you describe where you select.
  - **How FLUX sees the area:** upright, as the photo is seen, with your prompt alone, in one pass. On its side, as
    removals show it, a lemon tree in a pot came out as broken pots in 2 variants of 2. Upright it was drawn in 2 of 2.
  - **On your photos:** a man walking a dog, a pot with a plant, clouds and a tram out of focus all took the photo's
    light and blur.
- **Shadows and reflections.** "Include the shadow" adds the selected objects' shadows to the selection, so every
  model removes them: SAM 3 finds the shadows that touch them (a long shadow at a low sun), and OSOR, if installed,
  what goes with each object (its shadow, its reflection), part by part.
- **Writes a real RAW.** The fill is converted back into the camera's linear space and re-mosaicked into the Bayer data
  with matching sensor noise, so the DNG develops like the original.
- **Seamless blending:** a Poisson membrane plus texture transfer from the ring around the hole.
- **Long removals stay sharp.** A pole as tall as the photo, a cable or a railing is filled in tiles along it, each
  close to the model's own size, so the fill is not a small picture enlarged; thin ones also get a LaMa variant, which
  continues what is behind them best. **Full detail** redraws the chosen variant the same way, at the photo's
  resolution, keeping what it shows.
- **One selection for the whole photo.** Far-apart parts of it are removed separately, each in an area of its own
  near the model's size: a tourist on one side and a sign on the other are each filled as sharp as if selected
  alone. Parts that would see each other (a person and their shadow, a crowd) stay one removal, and each part sees
  the ones before it already filled. **Split into parts** shows the parts first, so each gets the model that suits
  it: RORem for the people, LaMa for a sign on a wall, FLUX Fill for a piece of architecture.
- **Each model says what it is not for,** in the menu, so the choice is an informed one: FLUX Fill draws people back
  into a crowd, LaMa blurs large areas, RORem can leave a seam along a pole.
- **Editable removals,** each with its own variants, kept in a project file; reopening a photo brings them back.
- **LightCraft and Chromaforge,** one or both, open at the same time if you like.
- **Windows, macOS (Apple Silicon) and Linux,** on NVIDIA, AMD (ROCm), Intel Arc or Apple GPUs. It falls back to
  the processor without one.
- **English and Italian.** More languages are one catalog file away (see [Languages](#languages)).
- **An MCP server,** so an AI assistant can install, configure and use it (see [For AI assistants](#for-ai-assistants)).

## LightCraft and Chromaforge

[Chromaforge](https://github.com/emmertex/lightcraft-classic) (first named "LightCraft Classic") is a fork of
[LightCraft](https://github.com/storytold/lightcraft) with the Lightroom Classic layout. AI Remove works the same way
in both: Ctrl/Cmd+Shift+X, the result stacked on the original, its masks named "Remove" as the starting selection, SAM 3
shared with the app's Object masks. What differs is only how AI Remove reaches each one:

| | LightCraft | Chromaforge |
|---|---|---|
| Get it | [getartcraft.com](https://getartcraft.com) | [its releases](https://github.com/emmertex/lightcraft-classic/releases) |
| Control channel | port 7980, `LIGHTCRAFT_CONTROL_PORT` | port 7981, `LIGHTCRAFT_CLASSIC_CONTROL_PORT` |
| Password on the channel | none | a token the app writes in its settings folder at every start (`control-token-<port>`); AI Remove reads it there |
| Settings folder (Windows) | `%APPDATA%\LightCraft` | `%APPDATA%\LightCraft Classic` |
| Command line, for a RAW on its own | `lightcraft-cli` | `lightcraft-classic-cli` (used when LightCraft is not installed) |

The installer asks which to set up: **LightCraft, Chromaforge or both** (the ones installed are the default), and
`--apps` answers without the question. The two ports let both be open together: AI Remove asks each open app which
photo it has selected, so Ctrl/Cmd+Shift+X opens the photo of the app you pressed it in. Started from the menu with
both open, it takes LightCraft's active photo (Chromaforge's when LightCraft has none); `--app chromaforge` takes
Chromaforge's. Installed Chromaforge later?
Run the configuration again: `--configure-lightcraft --apps chromaforge`.

**Chromaforge's Subject model, if you install it.** Chromaforge can use BiRefNet for its Subject and Background
masks. On Windows and Linux it runs on the processor, about 10 s each time a photo with such a mask (Lightroom's
"Select Subject" ones included, when imported from XMP) is redrawn, and AI Remove waits for it when it reads that
photo. To turn it off, close Chromaforge and rename the `models\birefnet` folder in its settings folder (for example
to `birefnet.disabled`): those masks then use the app's own quick analysis.

## Requirements

- **LightCraft** or **Chromaforge** installed, or both (see [LightCraft and Chromaforge](#lightcraft-and-chromaforge)).
- **Windows 10/11** with NVIDIA, AMD Radeon RX 7000/9000 or Intel Arc graphics. Without a GPU only LaMa is practical.
- **macOS 12+** on Apple Silicon (M1 or later; 16 GB of memory recommended). Intel Macs are not supported.
- **Linux x86-64** with NVIDIA, or AMD with ROCm.
- **Disk:** 5 to 30 GB, depending on the models.
- **Internet:** while installing. Afterwards only a check for a new AI Remove on GitHub, at most once a day: it
  sends nothing about you or your photos, and `"update_check": false` in `work/settings.json` turns it off.

## Install

Download a package from the releases, or clone this repository, then run the installer for your system:

| System | How |
|---|---|
| **Windows** | Double-click `Install on Windows.cmd`. If SmartScreen appears, choose *More info* > *Run anyway* (the script is not signed). |
| **macOS** | In Terminal, type `sh `, drag `Install on Mac.command` into the window and press Return. A double-click is blocked because the script is not signed by Apple; *System Settings > Privacy & Security > Open Anyway* also works. |
| **Linux** | `sh "Install on Linux.sh"` |

The installer:

1. detects the GPU and picks the right PyTorch build;
2. asks which app to set up: LightCraft, Chromaforge or both;
3. asks which models to install, showing what each one is for, its size and its licence. A model you already have
   on disk can be used from its folder instead of being downloaded again (see below);
4. puts a private Python 3.12, PyTorch and the models in `~/AIRemove`;
5. creates the **AI Remove** app with its icon (Start menu, Applications, or the app menu);
6. sets up each app chosen: it enables its local control channel, makes AI Remove its external editor, and assigns
   Ctrl/Cmd+Shift+X.

**Restart the app once afterwards:** it reads the control-channel setting only when it starts.

Non-interactive install:

```bash
sh installer/bootstrap.sh --yes --models lama,sam3,rorem --apps both
```

On Windows:

```bash
powershell -ExecutionPolicy Bypass -File installer\bootstrap.ps1 --yes --models lama,sam3,rorem --apps both
```

Other options:

| Option | Does |
|---|---|
| `--dir DIR` | Install somewhere other than `~/AIRemove` |
| `--apps lightcraft\|chromaforge\|both\|none` | The apps to set up, without the question (with `--yes` and no `--apps`: the ones chosen last time, else the ones installed) |
| `--hf-token TOKEN` | Token for the gated models (SAM 3, FLUX) |
| `--torch cuda\|rocm\|rocm-win\|xpu\|mps\|cpu` | Override the detected PyTorch build |
| `--model-dir MODEL=FOLDER` | Use a model you already have on disk, where it is (see below); once per model |
| `--models-from OTHER/models` | Reuse another install's models (linked, no extra space) |
| `--no-lightcraft` | Leave the apps' settings alone (`--apps none`) |
| `--configure-lightcraft` | Only set up the apps (for example after closing one, or after installing Chromaforge) |
| `--status` | Print a JSON report |
| `--uninstall [--keep-models]` | Remove AI Remove |

### Hugging Face token

SAM 3 is the same model LightCraft and Chromaforge use for their Object masks. When either has already downloaded it,
AI Remove links that copy and downloads nothing.

**FLUX**, and SAM 3 when neither app has it, are gated:

1. accept the licence on [facebook/sam3](https://huggingface.co/facebook/sam3) or
   [black-forest-labs/FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev);
2. create a *Read* token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) and paste it when
   the installer asks.

AI Remove does not keep the token: it is used for the download only. The MCP server passes it to the installer in a
temporary file, and the installer deletes that file as soon as it has read it.

### Models you already have

If a model is already on your disk, answer its question with its folder instead of *y*: you can drag the folder into
the installer's window. Any of these works:

- another AI Remove install, or its `models` folder;
- a Hugging Face cache (`~/.cache/huggingface/hub`), where the models are kept as `models--<org>--<name>`;
- ComfyUI's `models` folder (FLUX's GGUF in `models/unet`);
- the model's own folder.

The installer looks a few levels down, checks the files the same way the app does, and tells you what it found. A part
it does not find there is downloaded, for example FLUX's text encoders when only its GGUF is in ComfyUI. What it found is
used where it is: nothing is copied, and uninstalling AI Remove leaves that folder alone. The folders are recorded in
`airemove.json` (`model_paths`), so keep them where they are.

Without questions: `--model-dir flux=D:\ComfyUI\models --model-dir rorem=~/.cache/huggingface/hub`.

## Models

| Model | Best for | Not for | Size | Licence |
|---|---|---|---|---|
| LaMa | Small and medium objects on plain backgrounds; runs on the processor in seconds | Large areas and structures (doors, windows): it blurs them | 0.2 GB | Apache-2.0 |
| RORem (with SDXL Inpainting's files) | People and objects, the default: SDXL Inpainting retrained only to remove, no person or odd object drawn back where SDXL draws one; ~7 s per variant on a GPU | Long thin holes (a pole): it can leave a seam, LaMa or FLUX are cleaner | 11.6 GB (SDXL 6.8 + RORem 4.8) | Apache-2.0, on SDXL Inpainting's CreativeML Open RAIL++-M |
| FLUX.1 Fill [dev] + Turbo | The most realistic (light, perspective, architecture); large or hard areas; needs a 12+ GB GPU. Also **Generative fill** (Draw something new): what you describe, drawn in the selection | People: in a street or a crowd it draws people back where they were. Drawing: no shadow on the ground; large selections come out soft | 16.4 GB | FLUX.1 [dev] Non-Commercial |
| SAM 3 | One-click selection, and selecting by describing ("people"); without it: the brush | | 3.2 GB (0 if LightCraft or Chromaforge has it) | SAM License (Meta) |
| OSOR (optional, on FLUX) | Finds the shadows and reflections next to what you select, for "Include the shadow" (with SAM 3) | | 0.6 GB | FLUX.1 [dev] Non-Commercial |
| Qwen-Image 2.1 Turbo (optional) | People and objects on complex backgrounds (a person in front of steps, a pole across columns): it names the selection and removes it by name; ~30 s per variant at 1024 px; needs an NVIDIA or AMD GPU with 16 GB | When in a hurry: about a minute for a removal's first variant | 14.4 GB | Qwen Research License (non-commercial); its text encoder Qwen3-VL: Apache-2.0 |
| DAI (optional) | Reflections in glass, "Remove reflections": the whole photo or a selection, a few seconds on a GPU; the reflection is taken off the raw values, nothing is redrawn | Filling anything; a sharp, bright reflection (trees mirrored in a window, the sky in a puddle) is only partly taken away | 5.7 GB | Apache-2.0, a fine-tune of Stable Diffusion 2 (CreativeML Open RAIL++-M) |

The installer shows the same descriptions, sizes and licences (from `airemove/model_files.py`).

**Retired models.** SDXL Inpainting is no longer in the menu: it drew a person or an odd object back where RORem drew
none (11 of 12 test removals against 0), and RORem, which runs on its files, does its job. ObjectClear is gone: at
512 px its fills were always soft, and "Include the shadow" with RORem or FLUX does the same sharper. Updating removes
its folder from AI Remove's own models (7.3 GB). OSOR is no longer a fill model of the menu: it finds the shadows for
"Include the shadow". Projects keep the variants these models made, and `--auto sdxl` / `--auto osor` still work.

**Commercial use.** FLUX, OSOR and Qwen-Image are for non-commercial use only. They are fine for your own photos, but
not for paid work or clients without a licence from their makers: Black Forest Labs for FLUX and OSOR, Alibaba's Qwen
team for Qwen-Image. For paid work, use LaMa or RORem (with SDXL's usage restrictions), and DAI for reflections (with
Stable Diffusion 2's). FLUX's licence also asks you to check its results before sharing them, and to say they were
edited with AI where the law requires it. This is a summary, not legal advice: the licences themselves decide.

An optional prompt **in English** guides FLUX, for example "old plaster wall" or "dark doorway". For Qwen-Image it
names what to remove, when it recognised it wrongly ("the lamp post"). For Generative fill it is required: what to
draw ("a wooden bench").

## Using it

| | Windows / Linux | Mac |
|---|---|---|
| Select an object | click | click |
| Select every instance of something | type it under the tools ("people"), Enter | type it under the tools ("people"), Return |
| Take a part out / add a part | Alt+click / Shift+click | Option+click / Shift+click |
| SAM click / Brush / Eraser | S / B / E | S / B / E |
| Brush / Eraser size | Alt+wheel, `+` `−` or `[` `]` | Option+wheel, `+` `−` or `[` `]` |
| Drop an object from the selection | right-click | right-click (or Control+click) |
| Zoom | Ctrl+wheel, Ctrl+`+` `−` (`+` `−` alone with SAM click), `0` = fit | Cmd+wheel, Cmd+`+` `−` (`+` `−` alone with SAM click), `0` = fit |
| Pan | wheel, middle button, Space+drag | two fingers, Space+drag |
| Undo | Ctrl+Z | Cmd+Z |
| Compare with the original | hold "Original" or `\` | hold "Original" or `\` |
| Remove selection | Enter | Enter |
| Stop generating (the variants already made stay) | Esc | Esc |
| Previous / next variant | ← / → | ← / → |
| Delete a variant | right-click it | right-click (or Ctrl+click) it |

AI Remove also opens from the Start menu, Applications or the app menu: on the active photo of LightCraft or
Chromaforge when one is open, otherwise on a photo you choose ([on its own](#how-it-works)). On a Mac you can also
drop a photo on its icon.

**Headless.** A mask named `Remove` (or `Rimuovi`, or `Remove: <English prompt>`) on the photo, in LightCraft or
Chromaforge, is the starting selection. `airemove-cli --auto rorem` fills it without opening the window, writes the
result, and prints it as JSON (`--app lightcraft|chromaforge` picks the app when both are open).
`airemove-cli --auto dai` removes the reflections from it, or from the whole photo when it has no such mask, at 75 %;
`dai100` takes away all of what DAI found, `dai40` 40 % (0 to 150). `airemove-cli --auto fill` draws what the mask's
name says (`Remove: a wooden bench`) into the mask, as one removal.

### Files it writes

| File | Where | What |
|---|---|---|
| `<name>-AIRemove.dng` (a picture: `.jpg`, `.png`… as the original) | next to the original, stacked with it in LightCraft or Chromaforge (on its own: only next to it) | the retouched photo |
| `<photo name>.airemove` | next to the photo | the project: every removal and its variants. Double-click it to open the photo in AI Remove |
| `install.log`, `work/last-run.log` | in `~/AIRemove` | logs |

## Languages

AI Remove speaks **English** (the source language) and **Italian**. It picks the language in this order:

1. the `AIREMOVE_LANG` environment variable;
2. the language chosen in the window's top bar (the `EN ▾` button);
3. LightCraft's own language, else Chromaforge's;
4. the system's language;
5. English.

Translations are `airemove/locales/<code>.json` catalogs that map each English text to its translation, the way
LightCraft and Chromaforge do it. To add a language:

1. copy `airemove/locales/it.json` to `<code>.json` and translate its values, keeping the `{fields}`;
2. add the code and the language's own name to `LANGUAGES` in `airemove/i18n.py`;
3. run `python tools/i18n_check.py`. It lists missing or unused texts and broken placeholders, and `--update` adds
   new texts to every catalog.

## For AI assistants

- `mcp/` holds an MCP server that uses only the Python standard library. It works before AI Remove is installed, and
  can check the computer, install, set up LightCraft and/or Chromaforge, open the app and run headless removals.
  Setup is in [mcp/README.md](mcp/README.md).
- Agents with a shell should read [AGENTS.md](AGENTS.md).

## Uninstall

| System | How |
|---|---|
| **Windows** | *Settings > Apps > AI Remove for LightCraft and Chromaforge* |
| **macOS** | `Uninstall AI Remove.command` in `~/AIRemove` |
| **Linux** | `uninstall.sh` in `~/AIRemove` |

Uninstalling removes the app, its models and the settings it added to LightCraft and Chromaforge. Your photos, the
DNGs it made and the `.airemove` projects stay.

## Privacy and security

Your photos never leave your computer. The only request to the internet after the install is the daily check for a
new version (above). AI Remove drives LightCraft and Chromaforge through their control channels, which only accept
connections from your own computer (127.0.0.1):
- **LightCraft's** (port 7980) has **no password**: while LightCraft runs, any program on your computer can drive it.
- **Chromaforge's** (port 7981) asks for a token it writes in its settings folder, so only programs that can read
  that folder can drive it.

Uninstalling turns the channels off.

## Development

| Path | What |
|---|---|
| `airemove/` | The app: `airemove.py` (session, the bridge to LightCraft and Chromaforge, RAW pipeline, CLI), `ui.py` (Tk window), `engines.py` (SAM 3, LaMa, SDXL, FLUX), `model_files.py` (each model's files, sizes and licence, and where they are), `rawdng.py` (DNG read/write, sensor noise), `imagefile.py` (JPEG, PNG, TIFF, WebP, HEIC, AVIF read/write, with the same calls), `blend.py` (seamless blending), `project.py` (`.airemove` files), `system.py` (per-OS paths; `Host`: each app's ports, token, settings and command line), `i18n.py` + `locales/` (translations) |
| `installer/` | `bootstrap.ps1` / `bootstrap.sh` (fetch uv, then run `install.py`), `install.py` (standard library only), `fetch_models.py` |
| `mcp/` | The MCP server and its launchers |
| `assets/icon/` | The icon, and how it was made ([assets/icon/README.md](assets/icon/README.md)) |
| `tools/` | `build_dist.py` (release packages), `check_dist.py` (checks them), `i18n_check.py` (translation catalogs), `ci_smoke.py` and `ci_removal.py` (CI: a real install, then one removal end to end), `ci_fill.py` (CI: Generative fill with a stand-in FLUX), `ci_status.py` (CI: the install's status file read while it is written) |

Run from source with an install's Python:

```bash
~/AIRemove/venv/bin/python airemove/airemove.py --check
```

Build the release zips into `dist/` and check them:

```bash
python tools/build_dist.py
python tools/check_dist.py
```

Releases are built by GitHub Actions (`.github/workflows/release.yml`). Set `VERSION` in `airemove/system.py`, then
push a tag `v<VERSION>`: the workflow builds the four packages from the tag, checks them, writes `SHA256SUMS` and
attaches everything to a draft release. Write its notes on GitHub, then publish it.

## Licences

The code and the icon are under MIT ([LICENSE.txt](LICENSE.txt)). The models are downloaded from their publishers
under their own licences, and none is bundled. Details: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
