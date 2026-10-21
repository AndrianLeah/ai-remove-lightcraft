## New

- WRITE THE CHANGES HERE before publishing (the list of pull requests below is GitHub's, for reference).

## Fixed

- 

## Download

| System | Package | Then |
|---|---|---|
| Windows 10/11 | `AIRemove-@VERSION@-windows.zip` | unzip, double-click `Install on Windows.cmd` |
| macOS 12+ (Apple Silicon) | `AIRemove-@VERSION@-macos.zip` | unzip; in Terminal type `sh `, drag in `Install on Mac.command`, press Return |
| Linux x86-64 | `AIRemove-@VERSION@-linux.tar.gz` | unpack, `sh "Install on Linux.sh"` |
| All three | `AIRemove-@VERSION@-all-platforms.zip` | |

Then restart LightCraft once, select a raw photo and press **Ctrl+Shift+X** (Cmd+Shift+X on a Mac).

**Already installed?** Run the @VERSION@ installer again on the same folder. It updates the app and keeps the models
you have, without downloading them again.

**Checksums:** `SHA256SUMS` has the SHA-256 of each package. To check a download, in its folder:
- Linux: `sha256sum -c SHA256SUMS --ignore-missing`
- macOS: `shasum -a 256 -c SHA256SUMS --ignore-missing`
- Windows (PowerShell): `Get-FileHash AIRemove-@VERSION@-windows.zip`, then compare with `SHA256SUMS`

The packages were built and checked by GitHub Actions from commit @COMMIT@ ([the run](@RUN@)).

## Licences

The models have their own licences:
- **LaMa:** Apache-2.0
- **SAM 3:** SAM License
- **SDXL:** CreativeML Open RAIL++-M
- **RORem:** Apache-2.0, on SDXL Inpainting (CreativeML Open RAIL++-M)
- **FLUX.1 [dev] and OSOR:** FLUX.1 [dev] Non-Commercial
- **ObjectClear:** S-Lab License 1.0, non-commercial. Its code is downloaded at install time, not shipped with AI
  Remove.
- **Qwen-Image 2.1 Turbo:** Qwen Research License, non-commercial; its text encoder Qwen3-VL: Apache-2.0

For paid work, use LaMa, SDXL or RORem. See `THIRD-PARTY-NOTICES.md` for details.
