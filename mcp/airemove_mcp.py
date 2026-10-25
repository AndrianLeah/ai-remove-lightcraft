"""MCP server for AI Remove (2.0 beta: a local AI server for the Craft apps, and the window for LightCraft and
Chromaforge): lets an AI assistant explain, install,
configure, check, use and uninstall AI Remove on Windows, macOS and Linux.

Standard library only (Python 3.8+), stdio transport (one JSON-RPC message per line), so it runs before anything is
installed. Start it with mcp/run_mcp.cmd (Windows) or mcp/run_mcp.sh (macOS / Linux): they find a Python, or get one
through uv. See mcp/README.md for the client configuration.
"""
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "airemove"))
sys.path.insert(0, str(PKG / "installer"))
import model_files as mf  # noqa: E402
import system  # noqa: E402

# what fills a removal: the window's four first (lama, rorem, flux, qwen), then SDXL and OSOR, which it keeps out of
# its menu (model_files: the one list; SAM 3 selects). A retired name still works: objectclear runs OSOR.
FILL_MODELS = ["lama", "rorem", "flux", "qwen", "sdxl", "osor"]
RETIRED = {"objectclear": "osor"}

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
    """p's JSON; None when it is missing or stays unreadable. The installer replaces install-status.json and rewrites
    airemove.json while this reads them: on Windows the open can be refused for a moment, a rewrite can show half a
    file, so read again for up to half a second. The file is open only while it is read, which leaves the installer's
    replace room between two reads."""
    for i in range(10):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            if i == 9:
                return None
            time.sleep(0.05)


def venv_python(d):
    return d / "venv" / ("Scripts/python.exe" if WIN else "bin/python")


def doc(name):
    for p in (PKG / name, install_dir() / name):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


# ------------------------------------------------------------------------------------------------ guide
GUIDE = {
    "overview": """AI Remove 2.0 beta (unofficial: not made or endorsed by the ArtCraft team, who make the Craft apps)
removes objects, people and reflections from photos with local AI, in two ways:
- as a local AI server for the Craft apps' shared AI layer (storytold/craft-ai-integrations): `airemove-cli --serve`
  answers OpenAI's image edits on 127.0.0.1:7990, reached through a custom OpenAI-compatible connection (topic
  "server");
- as the 1.x window for LightCraft (the raw photo editor by the ArtCraft team) and Chromaforge, unchanged.
The released version is 1.6, the window only.
The window is Lightroom's Generative Remove, but local: select with one click (SAM 3), generate variants (LaMa, RORem,
FLUX Fill or Qwen-Image), pick one;
from a RAW the result is written back into a RAW DNG (<name>-AIRemove.dng) stacked on the original in LightCraft, so
all the development still works on it; from a JPEG, PNG, TIFF, WebP, HEIC or AVIF it is a copy in the same format
(<name>-AIRemove.jpg...). Every removal stays editable in a project file next to the photo (<photo>.airemove). It also
works on its own, on a photo file, without LightCraft's window.
It works the same way in Chromaforge (github.com/emmertex/lightcraft-classic, once "LightCraft Classic"), a fork of
LightCraft: one of them or both, the installer sets up the ones chosen.
Runs on Windows, macOS (Apple Silicon) and Linux; a GPU is strongly recommended (NVIDIA, AMD RX 7000/9000, Apple M).""",
    "install": """1. check_system: shows the GPU, the PyTorch build that will be used, the recommended models, sizes and
   licences, free disk space, and whether LightCraft and Chromaforge are installed / running ("apps").
2. Tell the user what each model is for, what will be downloaded (sizes) and the model licences, and get their OK.
   Ask which app AI Remove should be set up for: LightCraft, Chromaforge or both (install's apps).
   SAM 3 is reused from LightCraft or Chromaforge when one already downloaded it; otherwise it and FLUX need a free
   Hugging Face account, the licence accepted on the model page, and a Read token (huggingface.co/settings/tokens) —
   never invent or reuse a token, ask the user to paste theirs.
   Ask whether they already have some of the models on disk (another AI Remove install, a Hugging Face cache,
   ComfyUI's models): check_system(model_dirs={model: folder}) says what it finds there; those are then used from
   that folder, nothing downloaded or copied (a part not found there is downloaded).
3. install with accept_licenses=true, the models the user chose and model_dirs for the folders that check_system
   accepted. It runs in the background (10-60 min, mostly downloads; on Windows a console window shows it). Poll
   install_status every 30-60 s and report progress.
4. When done: the app (LightCraft, Chromaforge) must be restarted once (it reads the control-channel setting at
   start). If install_status says pending_lightcraft, ask the user to close the app it names (or, for a Chromaforge
   never opened yet, to open it once and close it), then call configure_lightcraft (with the same apps). Chromaforge
   installed later: configure_lightcraft(apps=chromaforge).
5. Usage: in LightCraft or Chromaforge select a photo, press Ctrl+Shift+X (Cmd+Shift+X on Mac), or open "AI Remove"
   from the Start menu / Applications / app menu (it works on the app's active photo, else asks for a photo file).""",
    "use": """In the AI Remove window: click an object (SAM 3 selects it whole); Alt/Option+click removes a part,
Shift+click adds one; Brush (B) / Eraser (E) for manual touch-ups; or describe it ("person", then "bag"): SAM 3
selects every instance. "Include the shadow" adds their shadows (SAM 3, and OSOR when installed) to the selection.
"Split into parts" cuts the selection into parts sized for the models; for each, pick the model and "Generate" (or
"Generate all"): LaMa = fast, small things on plain backgrounds and cables; RORem = people and objects, draws no one
back (the default); FLUX Fill = architecture, large areas, NOT people (it draws people back into a crowd); Qwen-Image =
people and objects on complex backgrounds, removes them by name. "Remove selection" (Enter) does it all with one model.
Reflections in glass (a shop window, a display case): choose "DAI" under "Remove reflections" in the model menu and
press "Remove reflections": with nothing selected the whole photo, else the selection. It takes away the light the
glass reflects and keeps every detail; its slider says how much of it (75 % at first, 0 to 150 %).
Each removal is separate (regenerate, choose another variant, delete it). "Save to LightCraft" (or "Save to
Chromaforge") writes/updates the result (the DNG, or the picture's copy).
Zoom: Ctrl/Cmd+wheel or + / -, 0 = fit; pan: wheel, middle button or Space+drag; hold "Originale" (or \\) to compare.
Headless (no window): put a mask named "Remove" (or "Remove: <English prompt>"; "Rimuovi" works too) on the photo in
LightCraft or Chromaforge — e.g. with the app's own MCP tools (an Object mask on the thing, renamed) — then call
remove_with_masks (app=chromaforge when both are open); for reflections in glass, remove_reflections (the "Remove"
masks, else the whole photo).""",
    "server": """2.0 beta: AI Remove as a local OpenAI-compatible image server, for the Craft apps' shared AI layer
(storytold/craft-ai-integrations) or any OpenAI client. No LightCraft or Chromaforge needed (install with apps=none if
the user only wants this).
Start: <install>/venv/Scripts/airemove-cli.exe --serve (Windows; venv/bin/airemove-cli elsewhere), optional --port
(7990) and --key-file PATH (a file holding the key; never put a key on a command line). It prints one JSON line
(serving, models, key, version) and serves until Ctrl+C; the models stay loaded on the GPU, one job at a time. It is
GPU work: not next to the user's AI Remove window.
In craft-ai-integrations: a custom OpenAI-compatible connection, address http://127.0.0.1:7990/v1, the key if any,
models lama, rorem, flux, qwen declared as image inpainting and dai-50, dai-75, dai-100, dai-125 as image editing.
API: GET /v1/models; POST /v1/images/edits (multipart: model, image, mask, prompt, n, output_format png|jpeg|webp,
output_compression 0-100 = their quality, a WebP at 100 lossless) -> {"data": [{"b64_json": …}]}, the whole picture at
its size (a PNG by default; above ~30 MP a PNG passes the Craft layer's 32 MiB cap: ask webp or jpeg). Pixels in,
pixels out: the DNG write-back over a RAW is only the window's and --auto's. Mask: transparent = change (OpenAI's) or white = change; needed by the fill models,
optional for dai-*. The prompt goes to flux only. Only 127.0.0.1, no browser Origin, Bearer key with --key-file.
Status: not yet tried inside a Craft app; the layer's "Remove objects" tool needs the prompt to be optional for
custom models (suggested upstream).""",
    "troubleshoot": """- "LightCraft non risponde": LightCraft is closed, or was started before the install: restart it. On Linux
  with Wayland its window must be visible. The control port is 7980 (LIGHTCRAFT_CONTROL_PORT); Chromaforge's is 7981
  (LIGHTCRAFT_CLASSIC_CONTROL_PORT; without it Chromaforge takes LIGHTCRAFT_CONTROL_PORT too, and both apps want the
  same port: run configure_lightcraft(apps=chromaforge)).
- "Chromaforge non ha accettato AI Remove": its control channel wants the token it writes at every start
  (control-token-<port> in its settings folder): restart Chromaforge.
- First FLUX/SDXL variant slow on AMD: the GPU compiles its kernels once (minutes), then it is fast.
- Out of GPU memory: use RORem instead of FLUX, fewer variants, close other GPU apps (the server too: it keeps its
  models loaded).
- The server: "cannot listen on 127.0.0.1:7990" = the port is taken (another server already running?): --port, and the
  same port in the connection's address. 401 = the connection's key is not the key file's.
- Windows SmartScreen / macOS Gatekeeper warnings on the install files: they are unsigned scripts. Windows: More info
  > Run anyway. macOS blocks a double-click on a downloaded unsigned script and macOS 15 dropped right-click > Open:
  run `sh "Install on Mac.command"` in Terminal (Gatekeeper does not check scripts started that way), or use System
  Settings > Privacy & Security > Open Anyway. The MCP install tool runs the installer through sh, so it is not
  affected. Files the installer downloads (uv, Python, PyTorch, models) carry no quarantine.
- macOS asks once whether Python may access an external drive or the Desktop/Documents folders when the photos are
  there: allow it.
- Logs: <install>/install.log (installation), <install>/work/last-run.log (the app).""",
    "uninstall": """uninstall (confirm=true) removes the app, its models (unless keep_models), the menu entries and the
LightCraft settings it added (external editor, shortcut, control channel). Photos, the -AIRemove files and the
.airemove projects next to the photos are kept.""",
}


# ------------------------------------------------------------------------------------------------ actions
def check_folders(dirs):
    """{model: what the folder holds of it}: the parts found (used from there) and the ones still to download."""
    rep = {}
    for m, folder in (dirs or {}).items():
        if m not in mf.MODELS:
            rep[m] = {"ok": False, "error": f"unknown model: one of {', '.join(mf.MODELS)}"}
            continue
        f = Path(str(folder)).expanduser()
        found = mf.find_model(m, f) if f.is_dir() else {}
        rep[m] = {"ok": bool(found), "folder": str(f), "found": {p: str(v) for p, v in found.items()},
                  "to_download_gb": {p: mf.PARTS[p].gb for p in mf.MODELS[m].parts if p not in found}}
        if not found:
            rep[m]["error"] = (f"{f} is not a folder" if not f.is_dir() else
                               f"none of {mf.MODELS[m].name} there (looked for {mf.looks_for(m)}, a few levels deep)")
    return rep


def app_state(host, cfg, ins):
    """What check_system says about LightCraft or Chromaforge: installed, running, reachable, set up."""
    port = host.port() if host.env("CONTROL_PORT") else int(cfg.get(host.cfg_key("port")) or host.default_port)
    return {"name": host.name, "app": host.app(), "running": ins.lc_running(host), "control_port": port,
            "reachable": host.reachable(port), "settings_dir": str(host.config_dir()),
            "configured": cfg.get(host.key)}


def app_args(a):
    """--app for the app named in the tool's arguments (default: AI Remove picks the one that answers)."""
    return ["--app", a["app"]] if system.host_named(a.get("app")) else []


def check_system(a):
    ins = installer()
    d = install_dir()
    gpus = ins.detect_gpus()
    try:
        flavour, gpu = ins.choose_torch(gpus)
        rec = ins.recommended_models(flavour, gpu)
        supported = True
    except ins.Stop as e:
        flavour, gpu, rec, supported = None, None, [], str(e)
    sam_host = system.sam3_host(mf.SAM3_WEIGHTS)  # an app that has SAM 3 already: linked, not downloaded
    lc_sam = sam_host is not None
    cfg = read_json(d / "airemove.json") or {}
    paths = cfg.get("model_paths") or {}
    rep = {
        "os": system.system(), "supported": supported,
        "gpus": [{"vendor": g[0], "name": g[1], "vram_gb": g[2]} for g in gpus],
        "pytorch_build": flavour and {"id": flavour, "what": ins.TORCH_FLAVOURS[flavour][0],
                                      "download_gb": ins.TORCH_FLAVOURS[flavour][1]},
        "models": {m: {"name": v.name, "gb": 0 if (m == "sam3" and lc_sam) else v.gb, "what": v.what,
                       "licence": v.licence, "needs_hf_token": bool(v.gated) and not (m == "sam3" and lc_sam),
                       "recommended": m in rec, "installed": mf.has(m, d / "models", paths, optional=True)}
                   for m, v in mf.MODELS.items()},
        "sam3_from_lightcraft": lc_sam, "sam3_from_app": sam_host and sam_host.name,
        "install_dir": str(d), "free_gb": round(ins.gb_free(d), 1),
        "installed": venv_python(d).exists(), "install_config": cfg or None,
        "install_status": read_json(d / "install-status.json"),
        # the apps AI Remove works in; "lightcraft" also as before Chromaforge
        "apps": {h.key: app_state(h, cfg, ins) for h in system.HOSTS},
        "apps_chosen": cfg.get("apps"),
    }
    rep["lightcraft"] = rep["apps"]["lightcraft"]
    if a.get("model_dirs"):
        rep["model_dirs"] = check_folders(a["model_dirs"])
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
    for i in range(10):  # a program reading it refuses the delete for a moment (Windows)
        try:
            st.unlink(missing_ok=True)
            break
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.05)
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


def install_args(a, d):
    """The installer's arguments for the install tool's arguments a."""
    models = a.get("models") or "recommended"
    args = ["--yes", "--dir", str(d), "--models", ",".join(models) if isinstance(models, list) else str(models)]
    for m, folder in (a.get("model_dirs") or {}).items():
        args += ["--model-dir", f"{m}={folder}"]
    if a.get("torch"):
        args += ["--torch", a["torch"]]
    if a.get("configure_lightcraft") is False:
        args.append("--no-lightcraft")
    elif a.get("apps"):
        args += ["--apps", str(a["apps"])]
    return args


def install(a):
    if not a.get("accept_licenses"):
        return {"started": False, "error": "accept_licenses must be true: first show the user the sizes and the "
                                           "model licences (check_system) and get their OK"}
    d = Path(a.get("install_dir") or install_dir()).expanduser()
    bad = {m: r.get("error") for m, r in check_folders(a.get("model_dirs")).items() if not r["ok"]}
    if bad:  # the installer would stop on them: say it now
        return {"started": False, "error": "model_dirs: " + "; ".join(f"{m}: {e}" for m, e in bad.items())}
    args = install_args(a, d) + _token_file(d, a.get("hf_token"))
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
    _launch_installer(["--configure-lightcraft", "--yes", "--dir", str(d)] + (["--apps", str(a["apps"])]
                                                                              if a.get("apps") else []), d)
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
    hosts = [h for h in ([system.host_named(a.get("app"))] if system.host_named(a.get("app")) else system.HOSTS)
             if h.reachable()]
    if not hosts:
        return {"ok": False, "error": "neither LightCraft nor Chromaforge is reachable: open it (restart it once "
                                      "after installing)" if not a.get("app") else
                                      f"{a['app']} is not reachable: open it (restart it once after installing)"}
    _app(d, app_args(a) + (["--id", str(int(a["photo_id"]))] if a.get("photo_id") else []), detach=True)
    return {"ok": True, "message": "AI Remove window opening on " +
                                   (f"photo {a['photo_id']}" if a.get("photo_id") else "the app's active photo")
                                   + f" (answering: {', '.join(h.name for h in hosts)})"}


def remove_with_masks(a):
    d = install_dir()
    model = str(a.get("model") or "rorem").lower()
    model = RETIRED.get(model, model)
    if model not in FILL_MODELS:
        return {"ok": False, "error": "model: " + " | ".join(FILL_MODELS)}
    args = ["--auto", model + (str(int(a["variant"])) if a.get("variant") else "")]
    if a.get("shadow"):
        args.append("--shadow")
    args += app_args(a)
    if a.get("photo_id"):
        args += ["--id", str(int(a["photo_id"]))]
    try:
        r = _app(d, args, timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "took more than 15 minutes (see work/last-run.log)"}
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("{")), None)
    return json.loads(line) if line else {"ok": False, "error": (r.stdout + r.stderr)[-1500:]}


REFLECTION_STRENGTH, REFLECTION_MAX = round(100 * mf.REFLECTION_STRENGTH), round(100 * mf.REFLECTION_MAX)  # in %


def remove_reflections(a):
    d = install_dir()
    strength = int(a["strength"]) if a.get("strength") is not None else REFLECTION_STRENGTH
    if not 0 <= strength <= REFLECTION_MAX:
        return {"ok": False, "error": f"strength: 0 to {REFLECTION_MAX} (%)"}
    args = ["--auto", f"dai{strength}"] + app_args(a)
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
        host = system.host_named(a.get("app")) or next((h for h in system.HOSTS if h.reachable()), system.LIGHTCRAFT)
        r = installer().lc_request(host.port(), "engine.execute",
                                   {"command": "photo.inspect", "params": {"id": int(a["photo_id"])}}, host=host)
        if not r or not r.get("ok"):
            return {"ok": False, "error": f"{host.name} did not answer photo.inspect: " + str((r or {}).get("error"))}
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
APP = {"type": "string", "enum": [h.key for h in system.HOSTS],
       "description": "the app the photo is in: lightcraft or chromaforge (default: the one answering; both open: the "
                      "one with an active photo)"}
APPS = {"type": "string", "enum": ["lightcraft", "chromaforge", "both", "none"],
        "description": "the apps to set up (external editor, shortcut, control channel). Ask the user which: "
                       "LightCraft, Chromaforge or both (check_system says which are installed). Default: the ones "
                       "chosen last time, else the installed ones"}
MODEL_DIRS = {"type": "object", "additionalProperties": {"type": "string"},
              "propertyNames": {"enum": list(mf.MODELS)},
              "description": "models the user already has on disk: {model: folder} (another AI Remove install, a "
                             "Hugging Face cache, ComfyUI's models...). Used from there, not downloaded again; parts "
                             "not found there are downloaded"}
TOOLS = [
    ("ai_remove_guide", "What AI Remove is and how to install, use, troubleshoot or uninstall it. Read this first.",
     {"type": "object", "properties": {"topic": {"type": "string", "enum": ["all"] + list(GUIDE)}}}, guide, True),
    ("check_system", "Inspect this computer for AI Remove: OS, graphics card, which PyTorch build and models fit, "
                     "what each model is for, its download size and licence, free disk, LightCraft and Chromaforge "
                     "installed/running/reachable/set up (apps), and the state of an existing AI Remove install "
                     "(with a self-test). "
                     "With model_dirs, also what those folders hold of the models. Read-only.",
     {"type": "object", "properties": {"model_dirs": MODEL_DIRS}}, check_system, True),
    ("install", "Install (or update/repair) AI Remove in the background: Python environment, PyTorch for the GPU, the "
                "chosen models, launcher with icon, menu entry, integration with LightCraft and/or Chromaforge "
                "(apps). Only after the user agreed "
                "to the download sizes and model licences shown by check_system. Then poll install_status.",
     {"type": "object", "required": ["accept_licenses"], "properties": {
         "accept_licenses": {"type": "boolean", "description": "true = the user accepted sizes and licences"},
         "models": {"type": "array", "items": {"type": "string", "enum": list(mf.MODELS)},
                    "description": "default: the recommended ones for this computer"},
         "model_dirs": MODEL_DIRS,
         "hf_token": {"type": "string", "description": "the user's own Hugging Face Read token; only needed for "
                                                       "sam3 (when neither LightCraft nor Chromaforge has it) and flux"},
         "install_dir": {"type": "string", "description": "default ~/AIRemove"},
         "torch": {"type": "string", "enum": ["cuda", "rocm", "rocm-win", "xpu", "mps", "cpu"],
                   "description": "override the detected PyTorch build"},
         "apps": APPS,
         "configure_lightcraft": {"type": "boolean", "description": "false: set up no app (as apps=none)"}}},
     install, False),
    ("install_status", "Progress of a running install (state, step n/7, message) and the end of its log.",
     {"type": "object", "properties": {"lines": {"type": "integer"}, "install_dir": {"type": "string"}}},
     install_status, True),
    ("configure_lightcraft", "(Re)apply the integration with LightCraft and/or Chromaforge (apps): control channel, "
                             "AI Remove as external editor, Ctrl/Cmd+Shift+X. If the app is running and not "
                             "reachable, the user must close it first.",
     {"type": "object", "properties": {"apps": APPS}}, configure_lightcraft, False),
    ("open_ai_remove", "Open the AI Remove window on the active photo of LightCraft or Chromaforge (or photo_id).",
     {"type": "object", "properties": {"photo_id": {"type": "integer"}, "app": APP}}, open_ai_remove, False),
    ("remove_with_masks", "Headless removal: the photo's masks (LightCraft or Chromaforge) named \"Remove\" (or "
                          "\"Remove: <English prompt>\") are filled with the model (far-apart parts each as a "
                          "removal of its own, in its own area) and written into <name>-AIRemove.dng (a picture: "
                          "<name>-AIRemove.jpg..., its own format), stacked on the original (like the window's Save). "
                          "Can take minutes. Returns the result's path (dng / file), photo id and the removals made.",
     {"type": "object", "properties": {
         "model": {"type": "string", "enum": FILL_MODELS + list(RETIRED),
                   "description": "rorem (default): people and objects, draws no one back, reads no prompt; "
                                  "lama: small things on plain backgrounds, cables; flux: architecture, large areas, "
                                  "not people; qwen: removes it by name (a mask's English prompt names it, else "
                                  "Qwen3-VL does); sdxl and osor are kept for scripts (osor also removes the object's "
                                  "shadow); objectclear, retired, runs osor"},
         "shadow": {"type": "boolean", "description": "first add the object's shadow and reflection to the masks "
                                                      "(needs osor installed), then fill with model"},
         "variant": {"type": "integer", "description": "generate this many variants and use the last (default 1)"},
         "app": APP, "photo_id": {"type": "integer", "description": "default: the app's active photo"}}},
     remove_with_masks, False),
    ("remove_reflections", "Headless \"Remove reflections\": the light a glass reflects (a shop window, a display "
                           "case) is taken away from the photo with DAI (installed as the \"dai\" model), from its "
                           "masks named \"Remove\" or, without one, from the whole photo; every detail of it stays. "
                           "Written and stacked like remove_with_masks. Seconds on a GPU.",
     {"type": "object", "properties": {
         "strength": {"type": "integer", "minimum": 0, "maximum": REFLECTION_MAX,
                      "description": f"% of the reflection DAI found that is taken away (default "
                                     f"{REFLECTION_STRENGTH}: closest to Lightroom's Reflection Removal where "
                                     f"measured; DAI alone takes more)"},
         "app": APP, "photo_id": {"type": "integer", "description": "default: the app's active photo"}}},
     remove_reflections, False),
    ("project_info", "The AI Remove project of a photo: its removals, the chosen variants and the result it writes.",
     {"type": "object", "properties": {"photo_id": {"type": "integer"}, "app": APP,
                                       "raw_path": {"type": "string", "description": "the photo's file (a RAW or "
                                                                                     "a picture)"}}},
     project_info, True),
    ("uninstall", "Uninstall AI Remove and undo its settings in LightCraft / Chromaforge (photos and projects are "
                  "kept). Ask first.",
     {"type": "object", "required": ["confirm"], "properties": {"confirm": {"type": "boolean"},
                                                                 "keep_models": {"type": "boolean"}}},
     uninstall, False),
]
INSTRUCTIONS = """AI Remove 2.0 beta: removes objects and reflections from photos with local AI, as a local
OpenAI-compatible server for the Craft apps' shared AI layer (ai_remove_guide(topic=server)) and as the window for
LightCraft and Chromaforge (a LightCraft fork), which writes the result back into a DNG (from a RAW) or a copy in the
picture's format (JPEG, PNG, TIFF, WebP, HEIC, AVIF). To install: ai_remove_guide(topic=install), then check_system, explain sizes and
licences, ask which app to set up (LightCraft, Chromaforge or both) and get the user's consent,
install(accept_licenses=true, apps=...), poll install_status, then tell the user to restart the app and press
Ctrl+Shift+X (Cmd+Shift+X on Mac) on a photo. Never invent a Hugging Face token."""


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
    "install_ai_remove": ("Install AI Remove for LightCraft and Chromaforge on this computer, step by step.",
                          "Install AI Remove for LightCraft and Chromaforge on this computer. Start with "
                          "ai_remove_guide(topic=install) and check_system, tell me what will be downloaded and the "
                          "licences, ask me which app to set up, and wait for my OK before installing."),
    "remove_object": ("Remove an object from the active photo of LightCraft or Chromaforge.",
                      "Help me remove an object from the photo that is active in LightCraft or Chromaforge with AI "
                      "Remove: open the AI Remove window for me and explain how to select and generate, or — if I "
                      "describe the object — do it headless with a \"Remove\" mask and remove_with_masks."),
}


def handle(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "ai-remove", "title": "AI Remove for LightCraft and Chromaforge",
                               "version": system.VERSION},
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
