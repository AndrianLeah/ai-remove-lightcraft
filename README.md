<p align="center">
  <img src="assets/icon/airemove-256.png" width="128" alt="AI Remove icon: an engraved raccoon">
</p>

<h1 align="center">AI Remove 2.0 beta</h1>

<p align="center"><b>Local AI for the Craft apps: removes objects, people and reflections from photos, on your own
computer.</b></p>

> **This is the 2.0 beta,** on the `openai-server` branch, and it is not released yet. The current release is 1.6, the
> plug-in for LightCraft and Chromaforge ([its README](https://github.com/AndrianLeah/ai-remove-lightcraft/blob/main/README.md)).
> 1.x installs are not offered the beta by their update check.

AI Remove 2.0 is a **local AI provider for the Craft apps' shared AI layer,**
[craft-ai-integrations](https://github.com/storytold/craft-ai-integrations). In that layer you connect a Craft app to
an AI service, for example with an OpenAI key. AI Remove connects the same way, as an OpenAI-compatible server, but it
runs on your own computer. The apps' tools for removing and filling can then use LaMa, RORem, FLUX Fill, Qwen-Image and
DAI on your graphics card:
- no account;
- no cost per picture;
- no photo leaves your computer.

Everything 1.x does is still here. [The AI Remove window](#the-ai-remove-window) opens from LightCraft or Chromaforge
with Ctrl/Cmd+Shift+X, or on its own, and from a RAW it writes a RAW DNG.

[Italiano](README.it.md)

> AI Remove is **unofficial**. It is not made, sponsored or endorsed by the ArtCraft team (storytold), who make the
> Craft apps and craft-ai-integrations, nor by Chromaforge's contributors.

## How 2.0 works

```
Craft app: a Remove or Fill tool
   │  the picture, a mask (and a prompt)
   ▼
craft-ai-integrations: a custom OpenAI-compatible connection
   │  POST http://127.0.0.1:7990/v1/images/edits
   ▼
AI Remove (airemove-cli --serve): LaMa, RORem, FLUX Fill, Qwen-Image, DAI on your GPU
   │  the whole picture, the same size, changed only where the mask is
   ▼
back in the app
```

1. [Install](#install) AI Remove and the models you want.
2. [Start the server](#start-the-server): `airemove-cli --serve`.
3. [Connect it](#connect-it-to-a-craft-app): in the Craft apps' AI setup, add a custom OpenAI-compatible connection to
   `http://127.0.0.1:7990/v1` and declare its models.

The work behind each request is the same as in the window:
- the same models;
- the same planning of the area;
- long areas filled in tiles along them;
- the same seamless blending.

**Pixels, not the RAW.** The app sends the photo as it renders it, and gets pixels back. Writing the result back
into the RAW, as a DNG with the camera's own data, stays the window's job:
- OpenAI's image API has no room for a RAW;
- the Craft layer's OpenAI adapter sends only PNG, JPEG or WebP.

How a removal stays non-destructive over a RAW is then up to the app.

## Status

- **Done in this beta:**
  - the server, its models and its security;
  - an end-to-end CI test, with requests built the way craft-ai-integrations' OpenAI adapter builds them;
  - every model run on real photos.
- **Not tried yet:** inside a Craft app. craft-ai-integrations is the shared layer its developers are building for the
  Craft apps; which app uses it, and when, is up to them.
- **Waiting on craft-ai-integrations:**
  - Its *Remove objects* tool is the one listed for LightCraft's Generative remove and PhotoCraft's Remove tool. It
    sends a picture and a mask without a prompt, but the layer currently requires a prompt for the models of a custom
    connection. AI Remove's models will show up there once the prompt is optional for them. The change has been
    suggested upstream.
  - A tool for reflections, for the `dai-…` models, has been suggested too.
  - Its adapter refuses a returned image over 32 MiB. A PNG passes that at about 30 megapixels, so for larger photos
    the app should ask for `output_format` `webp` or `jpeg`. Alternatively, the adapter could hand large results over
    as files, as its ComfyUI adapter does.

## Start the server

```bash
~/AIRemove/venv/bin/airemove-cli --serve --port 7990 --key-file ~/airemove-server.key
```

On Windows: `%USERPROFILE%\AIRemove\venv\Scripts\airemove-cli.exe --serve`. `--port` (7990 by default) and
`--key-file` are optional. Once it listens, it prints one JSON line with its address and the models this computer
runs. Ctrl+C stops it.

- **The key:** with `--key-file`, every request needs `Authorization: Bearer <key>`, where the key is the file's
  content. Keep the file where only you can read it. The key never goes on the command line, where other programs
  could see it.
- **Memory:** the models stay loaded on the graphics card between requests; stop the server to free it. One request
  runs at a time, and the others wait.

## Connect it to a Craft app

In craft-ai-integrations' setup, add a **custom OpenAI-compatible connection**:

| Setting | Value |
|---|---|
| Name | AI Remove |
| Server address | `http://127.0.0.1:7990/v1` (plain HTTP is accepted for this computer's own address) |
| Provider identifier | `ai-remove` |
| Key | the one in your key file, or none |
| Models | `lama`, `rorem`, `flux` and `qwen`, declared as **image inpainting**; `dai-50`, `dai-75`, `dai-100` and `dai-125`, declared as **image editing** |

The connection's **Test** lists the models: `GET /v1/models` answers with the ones that are installed and can run on
this computer. With a key, Test also asks once without it, and the server's refusal confirms that the key is
enforced.

## Models

| Model | Server id | Best for | Not for | Size | Licence |
|---|---|---|---|---|---|
| LaMa | `lama` | Small and medium objects on plain backgrounds; runs on the processor in seconds | Large areas and structures (doors, windows): it blurs them | 0.2 GB | Apache-2.0 |
| RORem (with SDXL Inpainting's files) | `rorem` | People and objects, the default: SDXL Inpainting retrained only to remove, no person or odd object drawn back where SDXL draws one; ~7 s per variant on a GPU | Long thin holes (a pole): it can leave a seam, LaMa or FLUX are cleaner | 11.6 GB (SDXL 6.8 + RORem 4.8) | Apache-2.0, on SDXL Inpainting's CreativeML Open RAIL++-M |
| FLUX.1 Fill [dev] + Turbo | `flux` | The most realistic (light, perspective, architecture); large or hard areas; needs a 12+ GB GPU | People: in a street or a crowd it draws people back where they were | 16.4 GB | FLUX.1 [dev] Non-Commercial |
| Qwen-Image 2.1 Turbo (optional) | `qwen` | People and objects on complex backgrounds (a person in front of steps, a pole across columns): it names the selection and removes it by name; ~30 s per variant at 1024 px; needs an NVIDIA or AMD GPU with 16 GB | When in a hurry: about a minute for a removal's first variant | 14.4 GB | Qwen Research License (non-commercial); its text encoder Qwen3-VL: Apache-2.0 |
| DAI (optional) | `dai-50`, `dai-75`, `dai-100`, `dai-125`: how much of the reflection it found is taken away | Reflections in glass: the whole picture or a masked area, a few seconds on a GPU; the reflection is taken off the pixel values, nothing is redrawn | Filling anything; a sharp, bright reflection (trees mirrored in a window, the sky in a puddle) is only partly taken away | 5.7 GB | Apache-2.0, a fine-tune of Stable Diffusion 2 (CreativeML Open RAIL++-M) |
| SAM 3 | (the window) | One-click selection, and selecting by describing ("people"); without it: the brush | | 3.2 GB (0 if LightCraft or Chromaforge has it) | SAM License (Meta) |
| OSOR (optional, on FLUX) | (the window) | Finds the shadows and reflections next to what you select, for "Include the shadow" (with SAM 3) | | 0.6 GB | FLUX.1 [dev] Non-Commercial |

The installer shows the same descriptions, sizes and licences (from `airemove/model_files.py`).

**The prompt.**
- **Through the server,** the request's prompt goes to FLUX ("old plaster wall", "dark doorway"). LaMa, RORem and
  Qwen-Image ignore it: Qwen-Image names what it removes by itself.
- **In the window,** an optional prompt **in English** guides FLUX. For Qwen-Image it names what to remove, when the
  model recognised it wrongly ("the lamp post").

**Retired models.**
- **SDXL Inpainting** is no longer in the menu: it drew a person or an odd object back where RORem drew none (11 of 12
  test removals against 0). RORem runs on its files and does its job.
- **ObjectClear** is gone: at 512 px its fills were always soft, and "Include the shadow" with RORem or FLUX does the
  same, sharper. Updating removes its folder from AI Remove's own models (7.3 GB).
- **OSOR** is no longer a fill model of the menu: it finds the shadows for "Include the shadow".

Projects keep the variants these models made, and `--auto sdxl` / `--auto osor` still work.

**Commercial use.** FLUX, OSOR and Qwen-Image are for non-commercial use only. They are fine for your own photos, but
not for paid work or clients without a licence from their makers: Black Forest Labs for FLUX and OSOR, Alibaba's Qwen
team for Qwen-Image. For paid work, use LaMa or RORem (with SDXL's usage restrictions), and DAI for reflections (with
Stable Diffusion 2's). FLUX's licence also asks you to check its results before sharing them, and to say they were
edited with AI where the law requires it. This is a summary, not legal advice: the licences themselves decide.

## The server's API

`airemove-cli --serve` answers a small part of OpenAI's image API.

| Request | Answer |
|---|---|
| `GET /v1/models` | the models this computer runs, as OpenAI lists models |
| `POST /v1/images/edits` | the edited picture |
| `GET /health` | `{"ok": true, "version": …}` |

The paths also work without `/v1`.

- **The request** is `POST /v1/images/edits` in multipart/form-data, as OpenAI's, with these fields:
  - `model`;
  - `image`, or the first `image[]` (PNG, JPEG or WebP; transparency is kept);
  - `mask`;
  - `prompt`;
  - `n` (1 to 4 variants; LaMa and DAI always give one);
  - `output_format`: `png` (the default), `jpeg` or `webp`;
  - `output_compression`: a JPEG's or WebP's quality, 0 to 100 (100 by default; a WebP at 100 is lossless).
- **The answer** is `{"created": …, "output_format": …, "data": [{"b64_json": …}]}`: the whole picture at its size,
  unchanged away from the removal (but for a JPEG's or a lossy WebP's own loss). Links (`response_format=url`) are not
  offered.
- **The answer's size:**
  - a PNG takes about 1.1 bytes per pixel: about 17 MiB for a 13-megapixel photo;
  - a lossless WebP takes about a quarter less;
  - a JPEG at 95 takes about a quarter of the PNG.
- **The mask** follows OpenAI's convention when it has transparency: transparent = the area to change. Otherwise, white
  = the area. A mask of another size is scaled to the picture. The fill models need one; DAI works on the whole
  picture without one.
- **Errors** come in OpenAI's shape, `{"error": {"message", "type", "param", "code"}}`. The codes are `missing_mask`,
  `invalid_mask`, `model_not_found` and `invalid_api_key`, and the HTTP status says the rest (403, 404, 411, 413).
- **Limits:**
  - pictures up to 100 megapixels, in 8 bits per channel;
  - requests up to 256 MiB;
  - one job at a time, on the graphics card: the others wait. The models stay loaded between jobs.
- **Times** for a 13-megapixel photo on a 16 GB AMD card, model loading included:
  - LaMa: about 20 s;
  - DAI: about 25 s;
  - RORem: about 45 s;
  - FLUX and Qwen-Image: about a minute.
- **Security:**
  - it listens on 127.0.0.1 only;
  - it answers only requests addressed to `127.0.0.1:<port>` or `localhost:<port>`, so a web page cannot reach it by
    renaming a site's address;
  - it answers no request from a browser page (one with an `Origin`);
  - with `--key-file` it wants the key, compared in constant time.

## Requirements

- **For the server:** no other app. To use it from an app, you need a Craft app with craft-ai-integrations, or any
  program that speaks OpenAI's image edits.
- **For the window:** LightCraft or Chromaforge, or both. You need one of them for Ctrl/Cmd+Shift+X and for RAWs; a
  JPEG, PNG, TIFF, WebP, HEIC or AVIF opens without them (see
  [LightCraft and Chromaforge](#lightcraft-and-chromaforge)).
- **Windows 10/11** with NVIDIA, AMD Radeon RX 7000/9000 or Intel Arc graphics. Without a GPU only LaMa is practical.
- **macOS 12+** on Apple Silicon (M1 or later; 16 GB of memory recommended). Intel Macs are not supported.
- **Linux x86-64** with NVIDIA, or AMD with ROCm.
- **Disk:** 5 to 30 GB, depending on the models.
- **Internet:** while installing. Afterwards only a check for a new AI Remove on GitHub, at most once a day: it
  sends nothing about you or your photos, and `"update_check": false` in `work/settings.json` turns it off.

## Install

There is no 2.0 package yet: clone this branch, then run the installer for your system.

```bash
git clone -b openai-server https://github.com/AndrianLeah/ai-remove-lightcraft.git
```

| System | How |
|---|---|
| **Windows** | Double-click `Install on Windows.cmd`. If SmartScreen appears, choose *More info* > *Run anyway* (the script is not signed). |
| **macOS** | In Terminal, type `sh `, drag `Install on Mac.command` into the window and press Return. A double-click is blocked because the script is not signed by Apple; *System Settings > Privacy & Security > Open Anyway* also works. |
| **Linux** | `sh "Install on Linux.sh"` |

Already on 1.x? Run it on the same folder: it updates the app and keeps the models you have.

The installer:

1. detects the GPU and picks the right PyTorch build;
2. asks which app to set up for the window: LightCraft, Chromaforge, both, or neither (enough for the server alone);
3. asks which models to install, showing what each one is for, its size and its licence. A model you already have
   on disk can be used from its folder instead of being downloaded again (see below);
4. puts a private Python 3.12, PyTorch and the models in `~/AIRemove`;
5. creates the **AI Remove** app with its icon (Start menu, Applications, or the app menu);
6. sets up each app chosen: it enables its local control channel, makes AI Remove its external editor, and assigns
   Ctrl/Cmd+Shift+X. **Restart that app once afterwards:** it reads the control-channel setting only when it starts.

Non-interactive install, for the server alone:

```bash
sh installer/bootstrap.sh --yes --models lama,rorem,dai --apps none
```

On Windows:

```bash
powershell -ExecutionPolicy Bypass -File installer\bootstrap.ps1 --yes --models lama,rorem,dai --apps none
```

Other options:

| Option | Does |
|---|---|
| `--dir DIR` | Install somewhere other than `~/AIRemove` |
| `--apps lightcraft\|chromaforge\|both\|none` | The apps to set up for the window, without the question (with `--yes` and no `--apps`: the ones chosen last time, else the ones installed) |
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

## The AI Remove window

Everything 1.x does, unchanged in 2.0.

### How the window works

1. In LightCraft or Chromaforge, select a photo and press **Ctrl+Shift+X** (**Cmd+Shift+X** on a Mac).
2. Click what should go: SAM 3 selects the whole object. Alt/Option+click takes a part out, Shift+click adds one, and
   the brush and eraser handle the rest. Or **describe** it: type "people" (in English) and SAM 3 selects every
   person in the photo, each on its own, so a right-click drops one you want to keep.
3. Select everything in one go, describing it as many times as you like ("person", then "bag", then "sign") and
   fixing it with the brush and eraser. To remove the objects' shadows or reflections too, press **Include the
   shadow**: it adds them to the selection, in blue.
4. **Split into parts** cuts the selection into parts sized for the models:
   - things far apart (a person on the left, a sign on the right) become parts of their own, numbered on the photo;
   - a crowd, or a person and their shadow, stays one part, as long as its area stays small enough for the models to
     draw it sharp. A larger crowd becomes several parts, filled one after another.

   Select each part, choose its model and press **Generate**, or **Generate all** for the rest. The menu says what
   each model is good for, and what it is not for: FLUX Fill draws people back into a crowd. Pick the best variant
   of each part. **Remove selection** does all of it at once, with one model for every part. On a long removal (a
   pole, a cable, a railing), **Full detail** redraws the chosen variant at the photo's own resolution.
5. **Save to LightCraft** or **Save to Chromaforge** (the button names the app the photo came from) writes
   `<name>-AIRemove.dng` (from a JPEG: `<name>-AIRemove.jpg`, and so on), stacked on the original with the same
   development.

**Reflections in glass.** For a photo through a shop window or a display case, choose **DAI** under *Remove
reflections* in the model menu and press **Remove reflections**. With nothing selected it works on the whole photo,
with a selection only there, fading out around it. Like Lightroom's Remove Reflections, it takes away the light the
glass reflects (the street seen in the window, the veil over what is behind it). It takes that light off the raw values
themselves: nothing is redrawn, and every detail and the sensor's own noise stay. **Strength**, under the result, sets
how much of it goes (0 to 150 %, 75 % at first), and the photo follows as you drag it.

Every removal stays editable: regenerate it, pick another variant or delete it whenever you like. Everything lives in
one project file next to the photo (`<photo>.airemove`). The original is never modified.

**On its own.** The window also works on a photo that is in neither app. Open AI Remove from the Start menu,
Applications or the app menu with the apps closed (or no photo selected in them), and it asks for a file; **Open
photo…** in the window opens another one. **Save as DNG** (or **Save as JPEG**…) writes the result next to the photo,
and nothing is imported anywhere.
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

### What the window does

- **One-click selection** with SAM 3, refined with more clicks, a brush and an eraser.
- **Select by describing:** "people", "car" or "sign" selects every instance at once, a crowd included.
  - SAM 3 looks at the whole photo and at overlapping tiles of it, each near its own size, so people far away are
    found too. On a park photo it found 98 people instead of 39, in about 1–2 s on a GPU.
  - Where two people touch, no strip between them is left out. Like the apps' own Describe masks, each person's mask
    is joined by SAM 3's semantic mask where that person is the nearest.
- **Four fill models, each with a job:**
  - **LaMa:** quick, on the processor; small things on plain backgrounds, and cables.
  - **RORem** (the default): people and objects. It is SDXL Inpainting retrained only to remove, so it draws no one
    back. Commercial use is allowed.
  - **FLUX.1 Fill [dev]** with Turbo-Alpha: architecture and large areas, the most realistic, but not for people.
  - **Qwen-Image 2.1** (optional, 16 GB GPUs): people and objects on complex backgrounds. It first names everything
    selected ("the woman and her handbag"; what you described, such as "person", "bag" or "umbrella", is named too),
    then removes it by name and redraws the scene behind it.
- **Remove reflections,** like Lightroom's:
  - DAI (Dereflection Any Image, AAAI 2026) finds the light a pane of glass reflects over the photo, in a few seconds
    on a GPU, and AI Remove subtracts it from the RAW's own values, so the photo keeps all of its detail.
  - **Strength**, a slider under the result, says how much of what DAI found goes, from 0 to 150 %, and the photo
    follows as you drag it.
  - It starts at 75 %, which came closest to Lightroom's own result on a shop window. That was measured against the
    reflection Lightroom took away, which it stores in its `.acr` file.
- **Shadows and reflections.** "Include the shadow" adds the selected objects' shadows to the selection, so every
  model removes them. SAM 3 finds the shadows that touch them (a long shadow at a low sun). OSOR, if installed, finds
  what goes with each object (its shadow, its reflection), part by part.
- **Writes a real RAW.** The fill is converted back into the camera's linear space and re-mosaicked into the Bayer data
  with matching sensor noise, so the DNG develops like the original.
- **Seamless blending:** a Poisson membrane plus texture transfer from the ring around the hole.
- **Long removals stay sharp.** A pole as tall as the photo, a cable or a railing is filled in tiles along it, each
  close to the model's own size, so the fill is not a small picture enlarged. Thin ones also get a LaMa variant, which
  continues what is behind them best. **Full detail** redraws the chosen variant the same way, at the photo's
  resolution, keeping what it shows.
- **One selection for the whole photo:**
  - Far-apart parts of it are removed separately, each in an area of its own near the model's size: a tourist on one
    side and a sign on the other are each filled as sharp as if selected alone.
  - Parts that would see each other (a person and their shadow, a crowd) stay one removal, and each part sees the ones
    before it already filled.
  - **Split into parts** shows the parts first, so each gets the model that suits it: RORem for the people, LaMa for a
    sign on a wall, FLUX Fill for a piece of architecture.
- **Each model says what it is not for,** in the menu, so the choice is an informed one: FLUX Fill draws people back
  into a crowd, LaMa blurs large areas, RORem can leave a seam along a pole.
- **Editable removals,** each with its own variants, kept in a project file; reopening a photo brings them back.
- **LightCraft and Chromaforge,** one or both, open at the same time if you like.
- **Windows, macOS (Apple Silicon) and Linux,** on NVIDIA, AMD (ROCm), Intel Arc or Apple GPUs. It falls back to
  the processor without one.
- **English and Italian.** More languages are one catalog file away (see [Languages](#languages)).
- **An MCP server,** so an AI assistant can install, configure and use it (see [For AI assistants](#for-ai-assistants)).

### Shortcuts

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

AI Remove also opens from the Start menu, Applications or the app menu. It works on the active photo of LightCraft or
Chromaforge when one is open, otherwise on a photo you choose ([on its own](#how-the-window-works)). On a Mac you can
also drop a photo on its icon.

**Headless.** A mask named `Remove` (or `Rimuovi`, or `Remove: <English prompt>`) on the photo, in LightCraft or
Chromaforge, is the starting selection.
- `airemove-cli --auto rorem` fills it without opening the window, writes the result, and prints it as JSON.
  `--app lightcraft|chromaforge` picks the app when both are open.
- `airemove-cli --auto dai` removes the reflections from it, or from the whole photo when it has no such mask, at
  75 %. `dai100` takes away all of what DAI found, `dai40` 40 % (0 to 150).

### Files it writes

| File | Where | What |
|---|---|---|
| `<name>-AIRemove.dng` (a picture: `.jpg`, `.png`… as the original) | next to the original, stacked with it in LightCraft or Chromaforge (on its own: only next to it) | the retouched photo |
| `<photo name>.airemove` | next to the photo | the project: every removal and its variants. Double-click it to open the photo in AI Remove |
| `install.log`, `work/last-run.log` | in `~/AIRemove` | logs |

The server writes nothing next to your photos: it answers with the picture, and its temporary files are deleted after
each request.

### LightCraft and Chromaforge

[Chromaforge](https://github.com/emmertex/lightcraft-classic) (first named "LightCraft Classic") is a fork of
[LightCraft](https://github.com/storytold/lightcraft) with the Lightroom Classic layout. The window works the same way
in both:
- Ctrl/Cmd+Shift+X;
- the result stacked on the original;
- its masks named "Remove" as the starting selection;
- SAM 3 shared with the app's Object masks.

What differs is only how AI Remove reaches each one:

| | LightCraft | Chromaforge |
|---|---|---|
| Get it | [getartcraft.com](https://getartcraft.com) | [its releases](https://github.com/emmertex/lightcraft-classic/releases) |
| Control channel | port 7980, `LIGHTCRAFT_CONTROL_PORT` | port 7981, `LIGHTCRAFT_CLASSIC_CONTROL_PORT` |
| Password on the channel | none | a token the app writes in its settings folder at every start (`control-token-<port>`); AI Remove reads it there |
| Settings folder (Windows) | `%APPDATA%\LightCraft` | `%APPDATA%\LightCraft Classic` |
| Command line, for a RAW on its own | `lightcraft-cli` | `lightcraft-classic-cli` (used when LightCraft is not installed) |

The installer asks which to set up: **LightCraft, Chromaforge or both** (the ones installed are the default), and
`--apps` answers without the question.
- **Both open:** the two ports let both be open together. AI Remove asks each open app which photo it has selected,
  so Ctrl/Cmd+Shift+X opens the photo of the app you pressed it in.
- **Started from the menu with both open:** it takes LightCraft's active photo (Chromaforge's when LightCraft has
  none); `--app chromaforge` takes Chromaforge's.
- **Installed Chromaforge later?** Run the configuration again: `--configure-lightcraft --apps chromaforge`.

**Chromaforge's Subject model, if you install it.** Chromaforge can use BiRefNet for its Subject and Background
masks. On Windows and Linux it runs on the processor: about 10 s each time a photo with such a mask is redrawn
(Lightroom's "Select Subject" ones included, when imported from XMP), and AI Remove waits for it when it reads that
photo. To turn it off, close Chromaforge and rename the `models\birefnet` folder in its settings folder (for example
to `birefnet.disabled`): those masks then use the app's own quick analysis.

## Languages

AI Remove speaks **English** (the source language) and **Italian**. It picks the language in this order:

1. the `AIREMOVE_LANG` environment variable;
2. the language chosen in the window's top bar (the `EN ▾` button);
3. LightCraft's own language, else Chromaforge's;
4. the system's language;
5. English.

The server's answers and errors are in English, as OpenAI's are.

Translations are `airemove/locales/<code>.json` catalogs that map each English text to its translation, the way
LightCraft and Chromaforge do it. To add a language:

1. copy `airemove/locales/it.json` to `<code>.json` and translate its values, keeping the `{fields}`;
2. add the code and the language's own name to `LANGUAGES` in `airemove/i18n.py`;
3. run `python tools/i18n_check.py`. It lists missing or unused texts and broken placeholders, and `--update` adds
   new texts to every catalog.

## For AI assistants

- `mcp/` holds an MCP server that uses only the Python standard library. It works before AI Remove is installed. It
  can check the computer, install, set up LightCraft and/or Chromaforge, open the app and run headless removals.
  Setup is in [mcp/README.md](mcp/README.md).
- Agents with a shell should read [AGENTS.md](AGENTS.md), which also covers starting the server.

## Uninstall

| System | How |
|---|---|
| **Windows** | *Settings > Apps > AI Remove for LightCraft and Chromaforge* |
| **macOS** | `Uninstall AI Remove.command` in `~/AIRemove` |
| **Linux** | `uninstall.sh` in `~/AIRemove` |

Uninstalling removes the app, its models and the settings it added to LightCraft and Chromaforge. Your photos, the
DNGs it made and the `.airemove` projects stay. Remove the custom connection from the Craft apps' AI setup yourself.

## Privacy and security

Your photos never leave your computer. The only request to the internet after the install is the daily check for a
new version (above).

**The server** runs only while you run it, and only for this computer:
- it listens on 127.0.0.1;
- it answers neither web pages nor requests addressed to another name;
- with `--key-file`, it answers only programs that send its key.

Without a key, any program on your computer can use it while it runs.

**The window** drives LightCraft and Chromaforge through their control channels, which only accept connections from
your own computer (127.0.0.1):
- **LightCraft's** (port 7980) has **no password**: while LightCraft runs, any program on your computer can drive it.
- **Chromaforge's** (port 7981) asks for a token it writes in its settings folder, so only programs that can read
  that folder can drive it.

Uninstalling turns the channels off.

## Development

| Path | What |
|---|---|
| `airemove/` | The app. See the list below. |
| `installer/` | `bootstrap.ps1` / `bootstrap.sh` (fetch uv, then run `install.py`), `install.py` (standard library only), `fetch_models.py` |
| `mcp/` | The MCP server and its launchers |
| `assets/icon/` | The icon, and how it was made ([assets/icon/README.md](assets/icon/README.md)) |
| `tools/` | See the list below. |

`airemove/`:
- `server.py`: the local OpenAI-compatible server, 2.0;
- `airemove.py`: the session, the bridge to LightCraft and Chromaforge, the RAW pipeline and the CLI;
- `ui.py`: the Tk window;
- `engines.py`: SAM 3, LaMa, SDXL, FLUX;
- `model_files.py`: each model's files, sizes and licence, and where they are;
- `rawdng.py`: DNG read/write, sensor noise;
- `imagefile.py`: JPEG, PNG, TIFF, WebP, HEIC and AVIF read/write, with the same calls;
- `blend.py`: seamless blending;
- `project.py`: `.airemove` files;
- `system.py`: per-OS paths; `Host`, each app's ports, token, settings and command line;
- `i18n.py` and `locales/`: translations.

`tools/`:
- `build_dist.py`: release packages; `check_dist.py` checks them;
- `i18n_check.py`: translation catalogs;
- `ci_smoke.py` and `ci_removal.py`: CI, a real install, then one removal end to end;
- `ci_server.py`: CI, the server, asked as craft-ai-integrations' OpenAI adapter asks it;
- `ci_status.py`: CI, the install's status file read while it is written.

Run from source with an install's Python:

```bash
~/AIRemove/venv/bin/python airemove/airemove.py --check
~/AIRemove/venv/bin/python airemove/airemove.py --serve
```

Build the release zips into `dist/` and check them:

```bash
python tools/build_dist.py
python tools/check_dist.py
```

Releases are built by GitHub Actions (`.github/workflows/release.yml`). Set `VERSION` in `airemove/system.py`, then
push a tag `v<VERSION>`. The workflow builds the four packages from the tag, checks them, writes `SHA256SUMS` and
attaches everything to a draft release. Write its notes on GitHub, then publish it.

A 2.0 pre-release is tagged from this branch (`v2.0.0-beta.1`): the workflow marks it as a pre-release, and 1.x's
update check, which reads only the latest full release, does not offer it.

## Licences

The code and the icon are under MIT ([LICENSE.txt](LICENSE.txt)). The models are downloaded from their publishers
under their own licences, and none is bundled. Details: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
