# Instructions for AI agents: installing and using AI Remove

AI Remove is an unofficial plug-in for LightCraft and Chromaforge (a LightCraft fork, once named LightCraft Classic)
that removes objects from photos with local AI: from a RAW it writes
the result into a DNG, from a JPEG, PNG, TIFF, WebP, HEIC or AVIF into a copy in the same format. Talk to the user in
their language. Most users of this package speak Italian.

## Preferred: the MCP server

If the `ai-remove` MCP tools are available, use them in this order:

1. `ai_remove_guide`
2. `check_system`
3. `install`
4. `install_status`
5. `configure_lightcraft` (only if the install status says so)
6. `open_ai_remove` / `remove_with_masks` / `project_info`

Setup of the server: `mcp/README.md`.

## Without MCP (shell)

1. **Look first.** Run `installer/bootstrap.(ps1|sh) --status`. It prints JSON and changes nothing; it only fetches
   uv into the install folder if uv is missing. It reports whether AI Remove is installed, the GPU, and whether
   LightCraft and Chromaforge are installed, running and reachable (`apps`).
2. **Tell the user and wait for their OK** before installing. Say:
   - what each model is for (README, "Models");
   - the download size: PyTorch 1–9 GB depending on the GPU, plus the models;
   - the model licences (see `THIRD-PARTY-NOTICES.md`);
   - that the app's local control channel will be enabled (LightCraft's has no password; Chromaforge's wants a token
     it writes in its settings folder; local programs only);
   - **which app to set up: LightCraft, Chromaforge or both** (`--status` says which are installed). Pass it as
     `--apps lightcraft|chromaforge|both`; without it, `--yes` takes the ones chosen last time, else the installed.
3. **Models already on disk.** Ask whether the user already has some of the models (another AI Remove install, a
   Hugging Face cache, ComfyUI's `models`). Pass each one as `--model-dir MODEL=FOLDER`. The installer checks the
   folder, stops if the model is not there, uses what it finds where it is and downloads only the missing parts.
4. **Hugging Face token, only if needed.** Ask for a token only when FLUX is wanted, or SAM 3 is wanted and neither
   LightCraft nor Chromaforge has downloaded it. The token is the user's own Read token, and they must have accepted the licence on the model
   page. Never invent one. Never print it back.
5. **Install, non-interactively:**
   - macOS / Linux: `sh installer/bootstrap.sh --yes --models lama,sam3,rorem --apps both [--hf-token T]`
   - Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File installer\bootstrap.ps1 --yes --models lama,sam3,rorem --apps both`

   **Windows, inside the Claude desktop app** (or any packaged MSIX app): processes you start write AppData into a
   private copy that LightCraft, Chromaforge and the Start menu cannot see (so does an app you start from there). So start the installer through Explorer instead:
   write a `.cmd` that calls the line above, then run `explorer.exe that.cmd`. The MCP `install` tool does this.

   Progress goes to `~/AIRemove/install-status.json` (state, step n/7) and `~/AIRemove/install.log`. It takes 10–60
   minutes.
6. **After the install**, the user must restart the app (LightCraft, Chromaforge) once. If the status is
   `pending_lightcraft`:
   1. the user closes the app the message names (a Chromaforge never opened yet: the user opens it once, then
      closes it — its settings folder must come from its own first start);
   2. run `bootstrap --configure-lightcraft --yes` (with the same `--apps`). Chromaforge installed later:
      `bootstrap --configure-lightcraft --yes --apps chromaforge`.

## Using it

- **For the user:** in LightCraft or Chromaforge, select a photo and press Ctrl+Shift+X (Cmd+Shift+X on a Mac). Or
  open "AI Remove" from the Start menu / Applications / app menu; it works on the app's active photo (both open:
  LightCraft's, unless `--app chromaforge`).
- **Which app:** AI Remove asks each app that answers which photo it has selected and works in that one;
  `--app lightcraft|chromaforge` picks one (the MCP tools take `app`). LightCraft's control port is 7980
  (`LIGHTCRAFT_CONTROL_PORT`), Chromaforge's 7981 (`LIGHTCRAFT_CLASSIC_CONTROL_PORT`), and Chromaforge's channel wants
  the token in `control-token-<port>` in its settings folder (AI Remove reads it).
- **On its own (no LightCraft window):** `airemove <path to a photo>`, or the app with LightCraft closed, which asks
  for a file. A RAW is read through `lightcraft-cli` (LightCraft must be installed; `LIGHTCRAFT_CLI` points to it
  elsewhere; without LightCraft, Chromaforge's `lightcraft-classic-cli`, or `LIGHTCRAFT_CLASSIC_CLI`) with that app's
  default development; a JPEG, PNG, TIFF, WebP, HEIC or AVIF as it is. "Save as DNG"
  ("Save as JPEG"…) writes `<name>-AIRemove.dng` (`.jpg`…) next to the photo without importing it. A photo that is
  LightCraft's current selection opens as LightCraft's photo instead.
- **Check:** `~/AIRemove/venv/(Scripts|bin)/airemove-cli --check` prints a JSON report: GPU, models, LightCraft and
  Chromaforge connections (`apps`).
- **Headless:**
  1. Put a mask named `Remove` (or `Rimuovi`), or `Remove: <English prompt>`, on the photo in LightCraft or
     Chromaforge. For example, with the app's MCP: an Object mask on the thing, then rename it.
  2. Run `airemove-cli --auto rorem` (or `lama`, `flux`, `qwen`; `rorem3` to use the 3rd variant; `sdxl` and `osor`
     still work, `objectclear` runs OSOR), optionally with `--id PHOTO_ID` and `--app`. Far-apart parts of the masks become
     removals of their own. Add `--shadow` to remove the object's shadow and reflection too (needs OSOR installed).
     Reflections in glass: `airemove-cli --auto dai` (needs the `dai` model) takes them off the masks as one removal,
     or off the whole photo when it has no such mask, at 75 %; `daiN` takes N % of what DAI found away (0 to 150:
     `dai100` all of it). The MCP tool for it is `remove_reflections` (`strength`, in %).
     Generative fill: `airemove-cli --auto fill` (needs FLUX) draws what the mask's name says, in English, into the
     masks as one removal (name the mask `Remove: a wooden bench`). Without a prompt in the name it refuses.
  3. It prints one JSON line with the result's path (`dng`, and `file`: the same, also for a picture), the app it
     worked in (`app`) and the photo id there.
- **Projects:** `<photo>.airemove` (a zip; `project.json` lists the removals and their variants) sits next to each
  photo. The installer registers it as a file type for the user (Windows `HKCU\Software\Classes\.airemove`, macOS the
  app's Info.plist, Linux `~/.local/share/mime/packages/airemove.xml`): a double-click opens its photo in AI Remove.

## Uninstall

Run `bootstrap --uninstall --yes [--keep-models]`. Ask the user first. Photos, DNGs and projects are kept.
