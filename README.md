<p align="center">
  <img src="assets/icon/airemove-256.png" width="128" alt="AI Remove icon: an engraved raccoon">
</p>

<h1 align="center">AI Remove for LightCraft</h1>

Remove objects and people from RAW photos with local AI, from inside
[LightCraft](https://github.com/storytold/lightcraft) — like Lightroom's Generative Remove, but on your own computer.
The result goes back into a **RAW DNG**, so you keep developing it like any raw file.

[Italiano](README.it.md)

> AI Remove is an **unofficial** plug-in. It is not made, sponsored or endorsed by the ArtCraft team, who make
> LightCraft.

## How it works

1. In LightCraft, select a raw photo and press **Ctrl+Shift+X** (**Cmd+Shift+X** on a Mac).
2. Click what should go: SAM 3 selects the whole object. Alt/Option+click takes a part out, Shift+click adds one, and
   the brush and eraser handle the rest.
3. **Remove selection** generates a few variants with the model you chose. Pick the best one. To remove the
   object's shadow or reflection too, press **Include the shadow** first: it adds them to the selection, in blue.
   On a long removal (a pole, a cable, a railing), **Full detail** redraws the chosen variant at the photo's own
   resolution.
4. **Save to LightCraft** writes `<name>-AIRemove.dng`, stacked on the original with the same development.

Every removal stays editable: regenerate it, pick another variant or delete it whenever you like. Everything lives in
one project file next to the raw (`<raw>.airemove`). The original raw is never modified.

## Features

- **One-click selection** with SAM 3, refined with more clicks, a brush and an eraser.
- **Three fill models.** LaMa is fast and runs on the processor. SDXL Inpainting makes generative variants. FLUX.1 Fill
  [dev] with Turbo-Alpha is the most realistic.
- **Shadows and reflections (optional).** OSOR and ObjectClear remove an object together with its shadow and
  reflection, though only the object is selected. "Include the shadow" uses OSOR to add the shadow to the selection,
  so every model removes it.
- **Writes a real RAW.** The fill is converted back into the camera's linear space and re-mosaicked into the Bayer data
  with matching sensor noise, so the DNG develops like the original.
- **Seamless blending:** a Poisson membrane plus texture transfer from the ring around the hole.
- **Long removals stay sharp.** A pole as tall as the photo, a cable or a railing is filled in tiles along it, each
  close to the model's own size, so the fill is not a small picture enlarged; thin ones also get a LaMa variant, which
  continues what is behind them best. **Full detail** redraws the chosen variant the same way, at the photo's
  resolution, keeping what it shows.
- **Editable removals,** each with its own variants, kept in a project file; reopening a photo brings them back.
- **Windows, macOS (Apple Silicon) and Linux,** on NVIDIA, AMD (ROCm), Intel Arc or Apple GPUs. It falls back to
  the processor without one.
- **English and Italian.** More languages are one catalog file away (see [Languages](#languages)).
- **An MCP server,** so an AI assistant can install, configure and use it (see [For AI assistants](#for-ai-assistants)).

## Requirements

- **LightCraft** installed ([getartcraft.com](https://getartcraft.com)).
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
2. asks which models to install, showing what each one is for, its size and its licence. A model you already have
   on disk can be used from its folder instead of being downloaded again (see below);
3. puts a private Python 3.12, PyTorch and the models in `~/AIRemove`;
4. creates the **AI Remove** app with its icon (Start menu, Applications, or the app menu);
5. sets LightCraft up: it enables LightCraft's local control channel (`LIGHTCRAFT_CONTROL_PORT`), makes AI Remove its
   external editor, and assigns Ctrl/Cmd+Shift+X.

**Restart LightCraft once afterwards:** it reads the control-channel setting only when it starts.

Non-interactive install:

```bash
sh installer/bootstrap.sh --yes --models lama,sam3,sdxl
```

On Windows:

```bash
powershell -ExecutionPolicy Bypass -File installer\bootstrap.ps1 --yes --models lama,sam3,sdxl
```

Other options:

| Option | Does |
|---|---|
| `--dir DIR` | Install somewhere other than `~/AIRemove` |
| `--hf-token TOKEN` | Token for the gated models (SAM 3, FLUX) |
| `--torch cuda\|rocm\|rocm-win\|xpu\|mps\|cpu` | Override the detected PyTorch build |
| `--model-dir MODEL=FOLDER` | Use a model you already have on disk, where it is (see below); once per model |
| `--models-from OTHER/models` | Reuse another install's models (linked, no extra space) |
| `--no-lightcraft` | Leave LightCraft's settings alone |
| `--configure-lightcraft` | Only apply the LightCraft integration (for example after closing LightCraft) |
| `--status` | Print a JSON report |
| `--uninstall [--keep-models]` | Remove AI Remove |

### Hugging Face token

SAM 3 is the same model LightCraft uses for its Object masks. When LightCraft has already downloaded it, AI Remove
links that copy and downloads nothing.

**FLUX**, and SAM 3 when LightCraft does not have it, are gated:

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

Without questions: `--model-dir flux=D:\ComfyUI\models --model-dir sdxl=~/.cache/huggingface/hub`.

## Models

| Model | Best for | Size | Licence |
|---|---|---|---|
| LaMa | Small and medium objects on plain backgrounds; runs on the processor in seconds | 0.2 GB | Apache-2.0 |
| SDXL Inpainting | Medium areas with detail; every variant differs; ~8–15 s each on a GPU | 6.8 GB | CreativeML Open RAIL++-M |
| FLUX.1 Fill [dev] + Turbo | The most realistic (light, perspective, architecture); large or hard areas; needs a 12+ GB GPU | 16.4 GB | FLUX.1 [dev] Non-Commercial |
| SAM 3 | One-click selection (without it: the brush) | 3.2 GB (0 if LightCraft has it) | SAM License (Meta) |
| OSOR (optional, on FLUX) | The object with its shadow and reflection, one step (~3–8 s); finds the shadow for "Include the shadow" | 0.6 GB | FLUX.1 [dev] Non-Commercial |
| ObjectClear (optional) | The object with its shadow and reflection, ~5 s per variant, 512 px | 7.3 GB | S-Lab License 1.0 (non-commercial) |

The installer shows the same descriptions, sizes and licences (from `airemove/model_files.py`).

**Commercial use.** FLUX, OSOR and ObjectClear are for non-commercial use only. They are fine for your own photos, but
not for paid work or clients without a licence from their makers: Black Forest Labs for FLUX and OSOR, S-Lab for
ObjectClear. For paid work, use LaMa or SDXL (SDXL with its usage restrictions). FLUX's licence also asks you to check
its results before sharing them, and to say they were edited with AI where the law requires it. This is a summary, not
legal advice: the licences themselves decide.

An optional prompt **in English** guides SDXL and FLUX, for example "old plaster wall" or "dark doorway".

## Using it

| | Windows / Linux | Mac |
|---|---|---|
| Select an object | click | click |
| Take a part out / add a part | Alt+click / Shift+click | Option+click / Shift+click |
| SAM click / Brush / Eraser | S / B / E | S / B / E |
| Brush size | `[` `]` or Alt+wheel | `[` `]` or Option+wheel |
| Drop an object from the selection | right-click | right-click (or Control+click) |
| Zoom | Ctrl+wheel, `+` `−`, `0` = fit | Cmd+wheel, `+` `−`, `0` = fit |
| Pan | wheel, middle button, Space+drag | two fingers, Space+drag |
| Undo | Ctrl+Z | Cmd+Z |
| Compare with the original | hold "Original" or `\` | hold "Original" or `\` |
| Remove selection | Enter | Enter |
| Stop generating (the variants already made stay) | Esc | Esc |
| Previous / next variant | ← / → | ← / → |
| Delete a variant | right-click it | right-click (or Ctrl+click) it |

AI Remove also opens from the Start menu, Applications or the app menu. It always works on LightCraft's active photo.

**Headless.** A LightCraft mask named `Remove` (or `Rimuovi`, or `Remove: <English prompt>`) on the photo is the
starting selection. `airemove-cli --auto sdxl` fills it without opening the window, writes the DNG, and prints the
result as JSON.

### Files it writes

| File | Where | What |
|---|---|---|
| `<name>-AIRemove.dng` | next to the original, stacked with it in LightCraft | the retouched photo |
| `<raw name>.airemove` | next to the raw | the project: every removal and its variants |
| `install.log`, `work/last-run.log` | in `~/AIRemove` | logs |

## Languages

AI Remove speaks **English** (the source language) and **Italian**. It picks the language in this order:

1. the `AIREMOVE_LANG` environment variable;
2. the language chosen in the window's top bar (the `EN ▾` button);
3. LightCraft's own language;
4. the system's language;
5. English.

Translations are `airemove/locales/<code>.json` catalogs that map each English text to its translation, the way
LightCraft does it. To add a language:

1. copy `airemove/locales/it.json` to `<code>.json` and translate its values, keeping the `{fields}`;
2. add the code and the language's own name to `LANGUAGES` in `airemove/i18n.py`;
3. run `python tools/i18n_check.py`. It lists missing or unused texts and broken placeholders, and `--update` adds
   new texts to every catalog.

## For AI assistants

- `mcp/` holds an MCP server that uses only the Python standard library. It works before AI Remove is installed, and
  can check the computer, install, configure LightCraft, open the app and run headless removals. Setup is in
  [mcp/README.md](mcp/README.md).
- Agents with a shell should read [AGENTS.md](AGENTS.md).

## Uninstall

| System | How |
|---|---|
| **Windows** | *Settings > Apps > AI Remove for LightCraft* |
| **macOS** | `Uninstall AI Remove.command` in `~/AIRemove` |
| **Linux** | `uninstall.sh` in `~/AIRemove` |

Uninstalling removes the app, its models and the LightCraft settings it added. Your photos, the DNGs it made and the
`.airemove` projects stay.

## Privacy and security

Your photos never leave your computer. The only request to the internet after the install is the daily check for a
new version (above). AI Remove drives LightCraft through LightCraft's control channel. That
channel only accepts connections from your own computer (127.0.0.1, port 7980), but it has **no password**: while
LightCraft runs, any program on your computer can drive it. Uninstalling turns the channel off.

## Development

| Path | What |
|---|---|
| `airemove/` | The app: `airemove.py` (session, LightCraft bridge, RAW pipeline, CLI), `ui.py` (Tk window), `engines.py` (SAM 3, LaMa, SDXL, FLUX), `model_files.py` (each model's files, sizes and licence, and where they are), `rawdng.py` (DNG read/write, sensor noise), `blend.py` (seamless blending), `project.py` (`.airemove` files), `system.py` (per-OS paths, LightCraft discovery), `i18n.py` + `locales/` (translations) |
| `installer/` | `bootstrap.ps1` / `bootstrap.sh` (fetch uv, then run `install.py`), `install.py` (standard library only), `fetch_models.py` |
| `mcp/` | The MCP server and its launchers |
| `assets/icon/` | The icon, and how it was made ([assets/icon/README.md](assets/icon/README.md)) |
| `tools/` | `build_dist.py` (release packages), `check_dist.py` (checks them), `i18n_check.py` (translation catalogs), `ci_smoke.py` and `ci_removal.py` (CI: a real install, then one removal end to end) |

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
