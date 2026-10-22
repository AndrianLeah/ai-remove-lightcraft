# Instructions for AI agents: installing and using AI Remove

AI Remove is an unofficial LightCraft plug-in that removes objects from photos with local AI: from a RAW it writes
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
   LightCraft is installed, running and reachable.
2. **Tell the user and wait for their OK** before installing. Say:
   - what each model is for (README, "Models");
   - the download size: PyTorch 1–9 GB depending on the GPU, plus the models;
   - the model licences (see `THIRD-PARTY-NOTICES.md`);
   - that LightCraft's local control channel will be enabled (it has no password; local programs only).
3. **Models already on disk.** Ask whether the user already has some of the models (another AI Remove install, a
   Hugging Face cache, ComfyUI's `models`). Pass each one as `--model-dir MODEL=FOLDER`. The installer checks the
   folder, stops if the model is not there, uses what it finds where it is and downloads only the missing parts.
4. **Hugging Face token, only if needed.** Ask for a token only when FLUX is wanted, or SAM 3 is wanted and LightCraft
   has not downloaded it. The token is the user's own Read token, and they must have accepted the licence on the model
   page. Never invent one. Never print it back.
5. **Install, non-interactively:**
   - macOS / Linux: `sh installer/bootstrap.sh --yes --models lama,sam3,rorem [--hf-token T]`
   - Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File installer\bootstrap.ps1 --yes --models lama,sam3,rorem`

   **Windows, inside the Claude desktop app** (or any packaged MSIX app): processes you start write AppData into a
   private copy that LightCraft and the Start menu cannot see. So start the installer through Explorer instead:
   write a `.cmd` that calls the line above, then run `explorer.exe that.cmd`. The MCP `install` tool does this.

   Progress goes to `~/AIRemove/install-status.json` (state, step n/7) and `~/AIRemove/install.log`. It takes 10–60
   minutes.
6. **After the install**, the user must restart LightCraft once. If the status is `pending_lightcraft`:
   1. the user closes LightCraft;
   2. run `bootstrap --configure-lightcraft --yes`.

## Using it

- **For the user:** in LightCraft, select a photo and press Ctrl+Shift+X (Cmd+Shift+X on a Mac). Or open
  "AI Remove" from the Start menu / Applications / app menu; it works on LightCraft's active photo.
- **On its own (no LightCraft window):** `airemove <path to a photo>`, or the app with LightCraft closed, which asks
  for a file. A RAW is read through `lightcraft-cli` (LightCraft must be installed; `LIGHTCRAFT_CLI` points to it
  elsewhere) with LightCraft's default development; a JPEG, PNG, TIFF, WebP, HEIC or AVIF as it is. "Save as DNG"
  ("Save as JPEG"…) writes `<name>-AIRemove.dng` (`.jpg`…) next to the photo without importing it. A photo that is
  LightCraft's current selection opens as LightCraft's photo instead.
- **Check:** `~/AIRemove/venv/(Scripts|bin)/airemove-cli --check` prints a JSON report: GPU, models, LightCraft
  connection.
- **Headless:**
  1. Put a mask named `Remove` (or `Rimuovi`), or `Remove: <English prompt>`, on the photo in LightCraft. For example, with
     LightCraft's MCP: an Object mask on the thing, then rename it.
  2. Run `airemove-cli --auto rorem` (or `lama`, `flux`, `qwen`; `rorem3` to use the 3rd variant; `sdxl` and `osor`
     still work, `objectclear` runs OSOR), optionally with `--id PHOTO_ID`. Far-apart parts of the masks become
     removals of their own. Add `--shadow` to remove the object's shadow and reflection too (needs OSOR installed).
     Reflections in glass: `airemove-cli --auto dai` (needs the `dai` model) takes them off the masks as one removal,
     or off the whole photo when it has no such mask, at 75 %; `daiN` takes N % of what DAI found away (0 to 150:
     `dai100` all of it). The MCP tool for it is `remove_reflections` (`strength`, in %).
  3. It prints one JSON line with the result's path (`dng`, and `file`: the same, also for a picture) and its
     LightCraft photo id.
- **Projects:** `<photo>.airemove` (a zip; `project.json` lists the removals and their variants) sits next to each
  photo. The installer registers it as a file type for the user (Windows `HKCU\Software\Classes\.airemove`, macOS the
  app's Info.plist, Linux `~/.local/share/mime/packages/airemove.xml`): a double-click opens its photo in AI Remove.

## Uninstall

Run `bootstrap --uninstall --yes [--keep-models]`. Ask the user first. Photos, DNGs and projects are kept.
