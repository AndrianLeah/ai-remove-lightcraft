"""MCP server for AI Remove (a LightCraft plug-in): lets an AI assistant explain, install, configure, check, use and
uninstall AI Remove on Windows, macOS and Linux.

Standard library only (Python 3.8+), stdio transport (one JSON-RPC message per line), so it runs before anything is
installed. Start it with mcp/run_mcp.cmd (Windows) or mcp/run_mcp.sh (macOS / Linux): they find a Python, or get one
through uv. See mcp/README.md for the client configuration.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "airemove"))
sys.path.insert(0, str(PKG / "installer"))
import system  # noqa: E402

PROTOCOL = "2025-06-18"
WIN = system.system() == "windows"


def install_dir():
    if (PKG / "venv").exists():  # this server runs from an installed copy
        return PKG
    return Path(os.environ.get("AIREMOVE_HOME") or Path.home() / "AIRemove").expanduser()


def installer():
    """The installer module, for its detection functions (it prints nothing on import)."""
    import install
    return install


def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def venv_python(d):
    return d / "venv" / ("Scripts/python.exe" if WIN else "bin/python")


def doc(name):
    for p in (PKG / name, install_dir() / name):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


# ------------------------------------------------------------------------------------------------ guide
GUIDE = {
    "overview": """AI Remove is an unofficial plug-in for LightCraft (the raw photo editor by the ArtCraft team; this
plug-in is not made or endorsed by them). It removes objects and people from RAW photos with AI (Lightroom's
Generative Remove, but local): select with one click (SAM 3), generate variants (LaMa, SDXL or FLUX Fill), pick one;
the result is written back into a RAW DNG (<name>-AIRemove.dng) stacked on the original in LightCraft, so all the
development still works on it. Every removal stays editable in a project file next to the raw (<raw>.airemove).
Runs on Windows, macOS (Apple Silicon) and Linux; a GPU is strongly recommended (NVIDIA, AMD RX 7000/9000, Apple M).""",
    "install": """1. check_system: shows the GPU, the PyTorch build that will be used, the recommended models, sizes and
   licences, free disk space, and whether LightCraft is installed / running.
2. Tell the user what will be downloaded (sizes) and the model licences, and get their OK. SAM 3 is reused from
   LightCraft when LightCraft already downloaded it; otherwise it and FLUX need a free Hugging Face account, the
   licence accepted on the model page, and a Read token (huggingface.co/settings/tokens) — never invent or reuse a
   token, ask the user to paste theirs.
3. install with accept_licenses=true (and the models the user chose). It runs in the background (10-60 min, mostly
   downloads; on Windows a console window shows it). Poll install_status every 30-60 s and report progress.
4. When done: LightCraft must be restarted once (it reads the control-channel setting at start). If install_status
   says pending_lightcraft, ask the user to close LightCraft, then call configure_lightcraft.
5. Usage: in LightCraft select a raw photo, press Ctrl+Shift+X (Cmd+Shift+X on Mac), or open "AI Remove" from the
   Start menu / Applications / app menu (it works on LightCraft's active photo).""",
    "use": """In the AI Remove window: click an object (SAM 3 selects it whole); Alt/Option+click removes a part,
Shift+click adds one; Brush (B) / Eraser (E) for manual touch-ups. Pick the model (LaMa = fast, small things on plain
backgrounds; SDXL = generative variants; FLUX = most realistic, large or structured areas; OSOR / ObjectClear = the
object together with its shadow and reflection), optionally an English prompt of what should be there ("old plaster
wall"), the number of variants, then "Remove selection" (Enter). "Include the shadow" (when OSOR or ObjectClear is
installed) adds the selected object's shadow and reflection to the selection first, so any model removes them too. Each
removal is separate (regenerate, choose another variant, delete it). "Save to LightCraft" writes/updates the DNG.
Zoom: Ctrl/Cmd+wheel or + / -, 0 = fit; pan: wheel, middle button or Space+drag; hold "Originale" (or \\) to compare.
Headless (no window): put a LightCraft mask named "Remove" (or "Remove: <English prompt>"; "Rimuovi" works too) on the photo — e.g. with
LightCraft's own MCP tools (an Object mask on the thing, renamed) — then call remove_with_masks.""",
    "troubleshoot": """- "LightCraft non risponde": LightCraft is closed, or was started before the install: restart it. On Linux
  with Wayland its window must be visible. The control port is 7980 (LIGHTCRAFT_CONTROL_PORT).
- First FLUX/SDXL variant slow on AMD: the GPU compiles its kernels once (minutes), then it is fast.
- Out of GPU memory: use SDXL instead of FLUX, fewer variants, close other GPU apps.
- Windows SmartScreen / macOS Gatekeeper warnings on the install files: they are unsigned scripts. Windows: More info
  > Run anyway. macOS blocks a double-click on a downloaded unsigned script and macOS 15 dropped right-click > Open:
  run `sh "Install on Mac.command"` in Terminal (Gatekeeper does not check scripts started that way), or use System
  Settings > Privacy & Security > Open Anyway. The MCP install tool runs the installer through sh, so it is not
  affected. Files the installer downloads (uv, Python, PyTorch, models) carry no quarantine.
- macOS asks once whether Python may access an external drive or the Desktop/Documents folders when the raws are
  there: allow it.
- Logs: <install>/install.log (installation), <install>/work/last-run.log (the app).""",
    "uninstall": """uninstall (confirm=true) removes the app, its models (unless keep_models), the menu entries and the
LightCraft settings it added (external editor, shortcut, control channel). Photos, the -AIRemove.dng files and the
.airemove projects next to the raws are kept.""",
}


# ------------------------------------------------------------------------------------------------ actions
def check_system(_):
    ins = installer()
    d = install_dir()
    gpus = ins.detect_gpus()
    try:
        flavour, gpu = ins.choose_torch(gpus)
        rec = ins.recommended_models(flavour, gpu)
        supported = True
    except ins.Stop as e:
        flavour, gpu, rec, supported = None, None, [], str(e)
    lc_sam = (system.lightcraft_sam3_dir() / "model.safetensors").exists()
    cfg = read_json(d / "airemove.json") or {}
    port = int(cfg.get("port") or system.control_port())
    rep = {
        "os": system.system(), "supported": supported,
        "gpus": [{"vendor": g[0], "name": g[1], "vram_gb": g[2]} for g in gpus],
        "pytorch_build": flavour and {"id": flavour, "what": ins.TORCH_FLAVOURS[flavour][0],
                                      "download_gb": ins.TORCH_FLAVOURS[flavour][1]},
        "models": {m: {"gb": 0 if (m == "sam3" and lc_sam) else v[0], "what": v[1], "licence": v[2],
                       "needs_hf_token": bool(v[3]) and not (m == "sam3" and lc_sam),
                       "recommended": m in rec} for m, v in ins.MODELS.items()},
        "sam3_from_lightcraft": lc_sam,
        "install_dir": str(d), "free_gb": round(ins.gb_free(d), 1),
        "installed": venv_python(d).exists(), "install_config": cfg or None,
        "install_status": read_json(d / "install-status.json"),
        "lightcraft": {"app": system.lightcraft_app(), "running": ins.lc_running(), "control_port": port,
                       "reachable": system.lightcraft_reachable(port),
                       "settings_dir": str(system.lightcraft_config_dir())},
    }
    if rep["installed"]:
        r = subprocess.run([str(venv_python(d)), str(d / "airemove" / "airemove.py"), "--check"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
        try:
            rep["app_check"] = json.loads(r.stdout[r.stdout.index("{"):])
        except ValueError:
            rep["app_check_output"] = (r.stdout + r.stderr)[-1500:]
    return rep


def _bootstrap_cmd(args):
    """The command that runs the installer with args (uv is fetched by the bootstrap when missing)."""
    if WIN:
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(PKG / "installer" / "bootstrap.ps1")] + args
    return ["sh", str(PKG / "installer" / "bootstrap.sh")] + args


def _launch_installer(args, d):
    """Start the installer detached. On Windows through Explorer: when this server runs inside a packaged app (the
    Claude desktop app is MSIX), its children see a private copy of AppData — the installer must run outside it so
    LightCraft and the Start menu see what it does. A console window shows the progress."""
    d.mkdir(parents=True, exist_ok=True)
    st = d / "install-status.json"
    if st.exists():
        st.unlink()
    if WIN:
        cmd = d / "run-installer.cmd"
        quoted = " ".join('"%s"' % a if (" " in a or not a) else a for a in _bootstrap_cmd(args))
        cmd.write_text("@echo off\r\nchcp 65001 >nul\r\ntitle AI Remove - installation\r\n"
                       f"set \"AIREMOVE_HOME={d}\"\r\n{quoted}\r\necho.\r\necho You can close this window.\r\n"
                       "timeout /t 30 >nul\r\n", encoding="utf-8")
        subprocess.Popen(["explorer.exe", str(cmd)])
    else:
        env = dict(os.environ, AIREMOVE_HOME=str(d))
        subprocess.Popen(_bootstrap_cmd(args), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env, start_new_session=True)


def _token_file(d, token):
    if not token:
        return []
    f = d / ".hf-token"
    f.write_text(token.strip(), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return ["--hf-token-file", str(f)]


def install(a):
    if not a.get("accept_licenses"):
        return {"started": False, "error": "accept_licenses must be true: first show the user the sizes and the "
                                           "model licences (check_system) and get their OK"}
    d = Path(a.get("install_dir") or install_dir()).expanduser()
    models = a.get("models") or "recommended"
    args = ["--yes", "--dir", str(d), "--models", ",".join(models) if isinstance(models, list) else str(models)]
    if a.get("torch"):
        args += ["--torch", a["torch"]]
    if a.get("configure_lightcraft") is False:
        args.append("--no-lightcraft")
    args += _token_file(d, a.get("hf_token"))
    _launch_installer(args, d)
    return {"started": True, "install_dir": str(d), "log": str(d / "install.log"),
            "next": "call install_status every 30-60 s; downloads take 10-60 min depending on the models"}


def install_status(a):
    d = Path(a.get("install_dir") or install_dir()).expanduser()
    st = read_json(d / "install-status.json")
    tail = ""
    try:
        tail = "\n".join((d / "install.log").read_text(encoding="utf-8", errors="replace").splitlines()[-int(
            a.get("lines") or 30):])
    except OSError:
        pass
    return {"status": st or {"state": "not started (or starting)"}, "log_tail": tail}


def configure_lightcraft(a):
    d = install_dir()
    if not venv_python(d).exists():
        return {"ok": False, "error": "AI Remove is not installed yet (install first)"}
    _launch_installer(["--configure-lightcraft", "--yes", "--dir", str(d)], d)
    for _ in range(90):  # quick: a few seconds
        time.sleep(1)
        st = read_json(d / "install-status.json")
        if st and st.get("state") in ("done", "pending", "failed"):
            return {"ok": st["state"] == "done", "status": st}
    return {"ok": False, "error": "no answer from the configuration step", "status": read_json(d / "install-status.json")}


def _app(d, args, timeout=None, detach=False):
    exe = d / "venv" / ("Scripts/airemove.exe" if WIN else "bin/airemove")
    cli = [str(venv_python(d)), str(d / "airemove" / "airemove.py")]
    if detach:
        target = [str(exe)] if exe.exists() else cli
        flags = 0x00000008 | 0x00000200 if WIN else 0
        subprocess.Popen(target + args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=not WIN)
        return None
    return subprocess.run(cli + args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def open_ai_remove(a):
    d = install_dir()
    if not venv_python(d).exists():
        return {"ok": False, "error": "AI Remove is not installed (install first)"}
    if not system.lightcraft_reachable(system.control_port()):
        return {"ok": False, "error": "LightCraft is not reachable: open it (restart it once after installing)"}
    _app(d, ["--id", str(int(a["photo_id"]))] if a.get("photo_id") else [], detach=True)
    return {"ok": True, "message": "AI Remove window opening on " +
                                   (f"photo {a['photo_id']}" if a.get("photo_id") else "LightCraft's active photo")}


def remove_with_masks(a):
    d = install_dir()
    model = str(a.get("model") or "sdxl").lower()
    if model not in ("lama", "sdxl", "flux", "osor", "objectclear"):
        return {"ok": False, "error": "model: lama | sdxl | flux | osor | objectclear"}
    args = ["--auto", model + (str(int(a["variant"])) if a.get("variant") else "")]
    if a.get("shadow"):
        args.append("--shadow")
    if a.get("photo_id"):
        args += ["--id", str(int(a["photo_id"]))]
    try:
        r = _app(d, args, timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "took more than 15 minutes (see work/last-run.log)"}
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("{")), None)
    return json.loads(line) if line else {"ok": False, "error": (r.stdout + r.stderr)[-1500:]}


def project_info(a):
    raw = a.get("raw_path")
    if not raw and a.get("photo_id"):
        port = system.control_port()
        r = installer().lc_request(port, "engine.execute", {"command": "photo.inspect", "params": {"id": int(a["photo_id"])}})
        if not r or not r.get("ok"):
            return {"ok": False, "error": "LightCraft did not answer photo.inspect: " + str((r or {}).get("error"))}
        raw = (r["result"].get("source") or {}).get("path")
        m = re.match(r"(.+)-AIRemove(?:-\d+)?$", Path(raw).stem)
        if m:  # a result: its project lives next to the original
            cands = [p for p in Path(raw).parent.glob(m.group(1) + ".*") if p.suffix.lower() != ".dng"
                     and not p.name.endswith((".airemove", ".xmp"))]
            raw = str(cands[0]) if cands else raw
    if not raw:
        return {"ok": False, "error": "give raw_path or photo_id"}
    proj = Path(raw).with_name(Path(raw).name + ".airemove")
    if not proj.exists():
        return {"ok": True, "raw": raw, "project": None, "message": "no AI Remove project for this photo yet"}
    with zipfile.ZipFile(proj) as z:
        pj = json.loads(z.read("project.json"))
    rem = []
    for r in pj.get("removals", []):
        labels = [v.get("label") for v in r.get("variants", [])]
        ch = r.get("chosen")
        rem.append({"id": r.get("id"), "variants": labels,
                    "chosen": labels[ch] if isinstance(ch, int) and 0 <= ch < len(labels) else None,
                    "picked_by_user": r.get("user_picked", False)})
    return {"ok": True, "raw": raw, "project": str(proj), "dng": pj.get("dng"), "saved": pj.get("saved"),
            "removals": rem}


def uninstall(a):
    if not a.get("confirm"):
        return {"ok": False, "error": "confirm must be true (ask the user first: it deletes the app and its models)"}
    d = install_dir()
    args = ["--uninstall", "--yes", "--dir", str(d)] + (["--keep-models"] if a.get("keep_models") else [])
    if WIN:
        _launch_installer(args, d)
        return {"ok": True, "message": "uninstaller started (a console window shows it)"}
    r = subprocess.run(_bootstrap_cmd(args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-2000:]}


def guide(a):
    topic = a.get("topic") or "all"
    if topic == "all":
        return "\n\n".join(f"## {k}\n{v}" for k, v in GUIDE.items())
    return GUIDE.get(topic) or f"topics: {', '.join(GUIDE)}"


OBJ = {"type": "object"}
TOOLS = [
    ("ai_remove_guide", "What AI Remove is and how to install, use, troubleshoot or uninstall it. Read this first.",
     {"type": "object", "properties": {"topic": {"type": "string", "enum": ["all"] + list(GUIDE)}}}, guide, True),
    ("check_system", "Inspect this computer for AI Remove: OS, graphics card, which PyTorch build and models fit, "
                     "download sizes and licences, free disk, LightCraft installed/running/reachable, and the state "
                     "of an existing AI Remove install (with a self-test). Read-only.", OBJ, check_system, True),
    ("install", "Install (or update/repair) AI Remove in the background: Python environment, PyTorch for the GPU, the "
                "chosen models, launcher with icon, menu entry, LightCraft integration. Only after the user agreed "
                "to the download sizes and model licences shown by check_system. Then poll install_status.",
     {"type": "object", "required": ["accept_licenses"], "properties": {
         "accept_licenses": {"type": "boolean", "description": "true = the user accepted sizes and licences"},
         "models": {"type": "array", "items": {"type": "string", "enum": ["lama", "sam3", "sdxl", "flux", "osor",
                                                                             "objectclear"]},
                    "description": "default: the recommended ones for this computer"},
         "hf_token": {"type": "string", "description": "the user's own Hugging Face Read token; only needed for "
                                                       "sam3 (when LightCraft has not got it) and flux"},
         "install_dir": {"type": "string", "description": "default ~/AIRemove"},
         "torch": {"type": "string", "enum": ["cuda", "rocm", "rocm-win", "xpu", "mps", "cpu"],
                   "description": "override the detected PyTorch build"},
         "configure_lightcraft": {"type": "boolean", "description": "default true"}}}, install, False),
    ("install_status", "Progress of a running install (state, step n/7, message) and the end of its log.",
     {"type": "object", "properties": {"lines": {"type": "integer"}, "install_dir": {"type": "string"}}},
     install_status, True),
    ("configure_lightcraft", "(Re)apply the LightCraft integration: control channel, AI Remove as external editor, "
                             "Ctrl/Cmd+Shift+X. If LightCraft is running and not reachable, the user must close it "
                             "first.", OBJ, configure_lightcraft, False),
    ("open_ai_remove", "Open the AI Remove window on LightCraft's active photo (or photo_id).",
     {"type": "object", "properties": {"photo_id": {"type": "integer"}}}, open_ai_remove, False),
    ("remove_with_masks", "Headless removal: the photo's LightCraft masks named \"Remove\" (or \"Remove: <English "
                          "prompt>\") are filled with the model and written into <name>-AIRemove.dng, stacked on the "
                          "original (like the window's Save). Can take minutes. Returns the DNG path and photo id.",
     {"type": "object", "properties": {
         "model": {"type": "string", "enum": ["lama", "sdxl", "flux", "osor", "objectclear"],
                   "description": "osor / objectclear also remove the object's shadow and reflection"},
         "shadow": {"type": "boolean", "description": "first add the object's shadow and reflection to the masks "
                                                      "(needs osor or objectclear installed), then fill with model"},
         "variant": {"type": "integer", "description": "generate this many variants and use the last (default 1)"},
         "photo_id": {"type": "integer", "description": "default: LightCraft's active photo"}}},
     remove_with_masks, False),
    ("project_info", "The AI Remove project of a photo: its removals, the chosen variants and the DNG it writes.",
     {"type": "object", "properties": {"photo_id": {"type": "integer"}, "raw_path": {"type": "string"}}},
     project_info, True),
    ("uninstall", "Uninstall AI Remove and undo its LightCraft settings (photos and projects are kept). Ask first.",
     {"type": "object", "required": ["confirm"], "properties": {"confirm": {"type": "boolean"},
                                                                 "keep_models": {"type": "boolean"}}},
     uninstall, False),
]
INSTRUCTIONS = """AI Remove: an unofficial LightCraft plug-in that removes objects from RAW photos with local AI and
writes the result back into a DNG. To install: ai_remove_guide(topic=install), then check_system, explain sizes and
licences and get the user's consent, install(accept_licenses=true), poll install_status, then tell the user to restart
LightCraft and press Ctrl+Shift+X (Cmd+Shift+X on Mac) on a raw photo. Never invent a Hugging Face token."""


# ------------------------------------------------------------------------------------------------ MCP plumbing
def resources():
    return [{"uri": "airemove://readme", "name": "README", "mimeType": "text/markdown"},
            {"uri": "airemove://agents", "name": "Instructions for AI agents", "mimeType": "text/markdown"},
            {"uri": "airemove://status", "name": "Install status", "mimeType": "application/json"}]


def read_resource(uri):
    if uri == "airemove://readme":
        return doc("README.md") or GUIDE["overview"], "text/markdown"
    if uri == "airemove://agents":
        return doc("AGENTS.md") or guide({}), "text/markdown"
    if uri == "airemove://status":
        return json.dumps(install_status({}), indent=1, ensure_ascii=False), "application/json"
    raise KeyError(uri)


PROMPTS = {
    "install_ai_remove": ("Install AI Remove for LightCraft on this computer, step by step.",
                          "Install AI Remove for LightCraft on this computer. Start with ai_remove_guide(topic="
                          "install) and check_system, tell me what will be downloaded and the licences, and wait for "
                          "my OK before installing."),
    "remove_object": ("Remove an object from the active LightCraft photo.",
                      "Help me remove an object from the photo that is active in LightCraft with AI Remove: open the "
                      "AI Remove window for me and explain how to select and generate, or — if I describe the object "
                      "— do it headless with a \"Remove\" mask and remove_with_masks."),
}


def handle(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "ai-remove", "title": "AI Remove for LightCraft", "version": system.VERSION},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": desc, "inputSchema": schema,
                           "annotations": {"readOnlyHint": ro}} for n, desc, schema, _, ro in TOOLS]}
    if method == "tools/call":
        tool = next((t for t in TOOLS if t[0] == params.get("name")), None)
        if tool is None:
            raise LookupError(f"unknown tool {params.get('name')}")
        try:
            res = tool[3](params.get("arguments") or {})
            text = res if isinstance(res, str) else json.dumps(res, indent=1, ensure_ascii=False, default=str)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    if method == "resources/list":
        return {"resources": resources()}
    if method == "resources/read":
        text, mime = read_resource(params.get("uri"))
        return {"contents": [{"uri": params.get("uri"), "mimeType": mime, "text": text}]}
    if method == "prompts/list":
        return {"prompts": [{"name": n, "description": d} for n, (d, _) in PROMPTS.items()]}
    if method == "prompts/get":
        d, text = PROMPTS[params.get("name")]
        return {"description": d, "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    raise NotImplementedError(method)


def main():
    out = sys.stdout
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        out.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.stdout = sys.stderr  # anything printed by mistake must not corrupt the protocol stream
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg or msg.get("method") is None:
            continue  # a notification or a response: nothing to answer
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
        except NotImplementedError as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"method not found: {e}"}}
        except Exception as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        out.write(json.dumps(reply, ensure_ascii=False) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
