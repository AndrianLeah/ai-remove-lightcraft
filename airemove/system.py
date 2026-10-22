"""What differs between Windows, macOS and Linux: where LightCraft keeps its settings and its SAM 3 model, how to
reach the running LightCraft (its JSON-lines control channel), the GPU, and the install's own settings file.

Everything here uses the standard library only: the installer and the MCP server import it too."""
import json
import os
import platform
import re
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the install folder: airemove/, models/, work/, venv/
CONFIG_FILE = ROOT / "airemove.json"  # written by the installer
DEFAULT_PORT = 7980
LIGHTCRAFT_ID = "ai.storyteller.lightcraft"  # Flatpak / desktop entry id
VERSION = "1.5.0"
REPO = "AndrianLeah/ai-remove-lightcraft"  # on GitHub: its releases are the updates
RELEASES = f"https://github.com/{REPO}/releases/latest"


def version_tuple(v):
    """'1.10.2' or 'v1.10.2' -> (1, 10, 2), for comparing versions."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def latest_release(timeout=4.0):
    """(version, release page) of the newest published release on GitHub, or None when it cannot be asked (offline,
    a proxy, GitHub's rate limit). Only the request itself is sent: nothing about the computer or the photos."""
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": f"AI-Remove/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    tag = str(d.get("tag_name") or "")
    return (tag.lstrip("vV"), d.get("html_url") or RELEASES) if version_tuple(tag) else None


def system():
    """'windows' | 'macos' | 'linux'"""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def control_port():
    """The port of LightCraft's control channel: LIGHTCRAFT_CONTROL_PORT (what LightCraft itself reads), else the
    one the installer set up, else 7980."""
    for v in (os.environ.get("LIGHTCRAFT_CONTROL_PORT"), config().get("port")):
        try:
            if v and 0 < int(v) < 65536:
                return int(v)
        except (TypeError, ValueError):
            pass
    return DEFAULT_PORT


def lightcraft_reachable(port=None, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port or control_port()), timeout=timeout):
            return True
    except OSError:
        return False


def flatpak_lightcraft():
    """True when LightCraft is the Flatpak (Linux)."""
    if system() != "linux" or not shutil.which("flatpak"):
        return False
    import subprocess
    try:
        return subprocess.run(["flatpak", "info", LIGHTCRAFT_ID], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lightcraft_config_dir():
    """LightCraft's settings folder (crates/engine/src/config.rs): LIGHTCRAFT_CONFIG_DIR, else
    macOS ~/Library/Application Support/LightCraft · Windows %APPDATA%\\LightCraft ·
    Linux $XDG_CONFIG_HOME/lightcraft (the Flatpak: ~/.var/app/ai.storyteller.lightcraft/config/lightcraft)."""
    v = os.environ.get("LIGHTCRAFT_CONFIG_DIR")
    if v:
        return Path(v)
    home = Path.home()
    s = system()
    if s == "macos":
        return home / "Library" / "Application Support" / "LightCraft"
    if s == "windows":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "LightCraft"
    flat = home / ".var" / "app" / LIGHTCRAFT_ID / "config" / "lightcraft"
    native = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "lightcraft"
    if flat.is_dir() and not native.is_dir():
        return flat
    return native


def lightcraft_sam3_dir():
    """Where LightCraft keeps the SAM 3 model (LIGHTCRAFT_SAM3_DIR, else <settings>/models/sam3)."""
    v = os.environ.get("LIGHTCRAFT_SAM3_DIR")
    return Path(v) if v else lightcraft_config_dir() / "models" / "sam3"


def lightcraft_app():
    """The LightCraft program (or app bundle) if it is installed where its installers put it, else None."""
    s = system()
    cands = []
    if s == "windows":
        for var in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
            d = os.environ.get(var)
            if d:
                sub = ("Programs", "LightCraft") if var == "LOCALAPPDATA" else ("LightCraft",)
                cands.append(Path(d, *sub, "lightcraft.exe"))
    elif s == "macos":
        cands = [Path("/Applications/LightCraft.app"), Path.home() / "Applications" / "LightCraft.app"]
    else:
        w = shutil.which("lightcraft")
        if w:
            cands.append(Path(w))
        cands += [Path("/usr/bin/lightcraft"), Path("/opt/lightcraft/lightcraft")]
    found = next((c for c in cands if c.exists()), None)
    if found is None and s == "linux" and flatpak_lightcraft():
        return "flatpak:" + LIGHTCRAFT_ID
    return str(found) if found else None


def lightcraft_cli():
    """The command that runs LightCraft without its window (lightcraft-cli), as an argument list, or None: next to
    the program LightCraft's installers put (on a Mac inside its app bundle), on the PATH, or the Flatpak's.
    LIGHTCRAFT_CLI overrides it. AI Remove reads a RAW opened on its own through it."""
    v = os.environ.get("LIGHTCRAFT_CLI")
    if v:
        return [v]
    app = lightcraft_app()
    if app and app.startswith("flatpak:"):
        return ["flatpak", "run", "--command=lightcraft-cli", LIGHTCRAFT_ID]
    s = system()
    cands = []
    if app:
        a = Path(app)
        cands.append(a.with_name("lightcraft-cli.exe") if s == "windows" else
                     a / "Contents" / "MacOS" / "lightcraft-cli" if s == "macos" else a.with_name("lightcraft-cli"))
    w = shutil.which("lightcraft-cli")
    if w:
        cands.append(Path(w))
    found = next((c for c in cands if c.exists()), None)
    return [str(found)] if found else None


def hard_exit(code=0):
    """End the process now. On Windows not through ExitProcess (os._exit): the AMD ROCm runtime can hang forever in
    its DLL shutdown, leaving a windowless AI Remove holding memory; TerminateProcess skips the DLLs' shutdown."""
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except Exception:
            pass
    if system() == "windows":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    os._exit(code)


def link_or_copy(src, dst):
    """dst becomes the same file as src: a hard link (no extra space), else a symbolic link, else a copy."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    for how in ("hard", "sym"):
        try:
            (os.link if how == "hard" else os.symlink)(src, dst)
            return how
        except (OSError, NotImplementedError, AttributeError):
            pass
    shutil.copyfile(src, dst)
    return "copy"


def gpu_summary():
    """torch's view of the accelerator: (device, description). Imports torch (only call it in the app's venv)."""
    import torch
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
        kind = "ROCm" if getattr(torch.version, "hip", None) else "CUDA"
        return "cuda", f"{name} ({kind}, {vram:.0f} GB)"
    if getattr(torch, "xpu", None) is not None and torch.xpu.is_available():
        return "xpu", torch.xpu.get_device_name(0)
    if torch.backends.mps.is_available():
        return "mps", f"Apple {platform.machine()} (Metal)"
    return "cpu", f"processor ({os.cpu_count()} cores)"
