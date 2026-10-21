# AI Remove MCP server

The server lets an AI assistant install, configure, check, use and uninstall AI Remove. It speaks MCP over stdio and
uses only the Python standard library, so it works **before** AI Remove is installed. The launchers find a Python:

1. the installed AI Remove's;
2. else a system Python 3.8+;
3. else they fetch `uv` quietly, and uv gets Python.

## Configure your assistant

Use the path of this folder: the unzipped package before installing, or `~/AIRemove/mcp` after. Replace `<you>` with
your user name.

### Claude Desktop

Open *Settings > Developer > Edit Config* (`claude_desktop_config.json`).

Windows:

```json
{
  "mcpServers": {
    "ai-remove": { "command": "cmd", "args": ["/c", "C:\\Users\\<you>\\AIRemove\\mcp\\run_mcp.cmd"] }
  }
}
```

macOS:

```json
{
  "mcpServers": {
    "ai-remove": { "command": "sh", "args": ["/Users/<you>/AIRemove/mcp/run_mcp.sh"] }
  }
}
```

Linux: the same as macOS, with `/home/<you>/AIRemove/mcp/run_mcp.sh`.

### Claude Code

Windows:

```bash
claude mcp add ai-remove -- cmd /c "C:\Users\<you>\AIRemove\mcp\run_mcp.cmd"
```

macOS / Linux:

```bash
claude mcp add ai-remove -- sh ~/AIRemove/mcp/run_mcp.sh
```

### Cursor, VS Code, others

Use the same command and arguments in the client's MCP settings: `cmd /c …\run_mcp.cmd` on Windows,
`sh …/run_mcp.sh` on macOS and Linux.

Then ask: *"Install AI Remove for LightCraft"*. The `install_ai_remove` prompt does the same.

## Tools

| Tool | What it does |
|---|---|
| `ai_remove_guide` | What AI Remove is; how to install, use, troubleshoot, uninstall |
| `check_system` | GPU, PyTorch build, what each model is for with its size and licence, disk, LightCraft state, install self-test; with `model_dirs` ({model: folder}), what those folders hold of the models (read-only) |
| `install` | Background install, after the user accepted sizes and licences (`accept_licenses: true`); optional `models`, `model_dirs` (models the user already has: used from there, not downloaded), `hf_token`, `install_dir`, `torch` |
| `install_status` | Progress (step n/7) and the end of the log |
| `configure_lightcraft` | (Re)apply the LightCraft integration: control channel, external editor, Ctrl/Cmd+Shift+X |
| `open_ai_remove` | Open the window on LightCraft's active photo, or on `photo_id` |
| `remove_with_masks` | Headless: fill the photo's "Remove" (or "Rimuovi") masks with `lama`, `sdxl`, `rorem`, `flux`, `osor`, `objectclear` or `qwen` (the shadow models and `shadow: true` also take the object's shadow and reflection), write the result (a DNG, or a picture's copy in its format) |
| `project_info` | A photo's removals, chosen variants and result |
| `uninstall` | Remove AI Remove and its LightCraft settings (`confirm: true`); photos and projects are kept |

Resources:

- `airemove://readme`
- `airemove://agents`
- `airemove://status`

**On Windows** the installer is started through Explorer, in a console window the user can watch. When the assistant
runs inside a packaged app (the Claude desktop app is MSIX), its own child processes would write AppData into a private
copy that LightCraft could not see.
