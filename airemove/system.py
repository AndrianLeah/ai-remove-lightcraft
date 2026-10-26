"""What differs between Windows, macOS and Linux, and between the apps AI Remove works inside (LightCraft and
Chromaforge, see Host): where each keeps its settings and its SAM 3 model, how to reach it while it runs (its
JSON-lines control channel), its command line, the GPU, and the install's own settings file.

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
VERSION = "1.7.0"
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


class Host:
    """An app AI Remove works inside: LightCraft, or Chromaforge (github.com/emmertex/lightcraft-classic, first named
    LightCraft Classic), a fork of LightCraft with the same control channel, commands, command line and SAM 3 folder
    under names of its own — and a token its control channel asks for before anything else.

    An app reads its environment variables with its own prefix first, then with the prefixes it had before (Chromaforge
    falls back to LIGHTCRAFT_*: LIGHTCRAFT_CONTROL_PORT alone opens its channel on that port too); env() reads them the
    same way. key: AI Remove's own name for it (--app, airemove.json, the MCP tools); settings: its settings folder's
    name; exe: its program's (the command line is <exe>-cli); folders: its Windows install folders' names; app_id: its
    Flatpak and desktop entry id."""

    def __init__(self, key, name, prefixes, settings, port, exe, folders, mac_apps, mac_process, app_id):
        self.key, self.name, self.prefixes, self.settings = key, name, prefixes, settings
        self.default_port, self.exe, self.folders = port, exe, folders
        self.mac_apps, self.mac_process, self.app_id = mac_apps, mac_process, app_id

    def __repr__(self):
        return f"Host({self.key})"

    def var(self, name):
        """The variable NAME under the app's own prefix (LIGHTCRAFT_CLASSIC_CONTROL_PORT): the one AI Remove sets."""
        return f"{self.prefixes[0]}_{name}"

    def env(self, name):
        """The variable NAME as the app reads it: its own prefix, else an older one."""
        return next((os.environ[f"{p}_{name}"] for p in self.prefixes if os.environ.get(f"{p}_{name}")), None)

    def cfg_key(self, name):
        """airemove.json's key for this app's NAME: LightCraft's are the plain ones (port, control_env…), from before
        there were two apps; Chromaforge's are prefixed (chromaforge_port…)."""
        return name if self is LIGHTCRAFT else f"{self.key}_{name}"

    def port(self):
        """The port of its control channel: the variable it reads at start, else the one the installer set up, else
        its default (LightCraft 7980; Chromaforge 7981, so that both can be open)."""
        for v in (self.env("CONTROL_PORT"), config().get(self.cfg_key("port"))):
            try:
                if v and 0 < int(v) < 65536:
                    return int(v)
            except (TypeError, ValueError):
                pass
        return self.default_port

    def reachable(self, port=None, timeout=1.0):
        try:
            with socket.create_connection(("127.0.0.1", port or self.port()), timeout=timeout):
                return True
        except OSError:
            return False

    def token(self, port=None):
        """The token its control channel wants first, if it wants one (Chromaforge; LightCraft so far does not):
        the CONTROL_TOKEN variable, else the file control-token-<port> the app writes in its settings folder at every
        start."""
        v = self.env("CONTROL_TOKEN")
        if v:
            return v.strip()
        try:
            return (self.config_dir() / f"control-token-{port or self.port()}").read_text("utf-8").strip() or None
        except OSError:
            return None

    def is_flatpak(self):
        """True when the app is the Flatpak (Linux)."""
        if system() != "linux" or not shutil.which("flatpak"):
            return False
        import subprocess
        try:
            return subprocess.run(["flatpak", "info", self.app_id], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def config_dir(self):
        """Its settings folder: the CONFIG_DIR variable, else macOS ~/Library/Application Support/<settings> ·
        Windows %APPDATA%\\<settings> · Linux $XDG_CONFIG_HOME/<settings in lower case> (the Flatpak's:
        ~/.var/app/<id>/config/<the same>)."""
        v = self.env("CONFIG_DIR")
        if v:
            return Path(v)
        home = Path.home()
        s = system()
        if s == "macos":
            return home / "Library" / "Application Support" / self.settings
        if s == "windows":
            return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / self.settings
        flat = home / ".var" / "app" / self.app_id / "config" / self.settings.lower()
        native = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / self.settings.lower()
        if flat.is_dir() and not native.is_dir():
            return flat
        return native

    def ui_json(self):
        """Its interface settings: the external editor, the shortcuts, the language."""
        return self.config_dir() / "ui.json"

    def sam3_dir(self):
        """Where it keeps the SAM 3 model of its Object masks (the SAM3_DIR variable, else <settings>/models/sam3)."""
        v = self.env("SAM3_DIR")
        return Path(v) if v else self.config_dir() / "models" / "sam3"

    def app(self):
        """The program (or app bundle) if it is installed where its installers put it, else None."""
        s = system()
        cands = []
        if s == "windows":
            for var in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
                d = os.environ.get(var)
                for f in self.folders if d else ():
                    sub = ("Programs", f) if var == "LOCALAPPDATA" else (f,)
                    cands.append(Path(d, *sub, f"{self.exe}.exe"))
            cands += _app_paths(f"{self.exe}.exe")  # installed in a folder of the user's choice
        elif s == "macos":
            cands = [base / a for a in self.mac_apps for base in (Path("/Applications"), Path.home() / "Applications")]
        else:
            w = shutil.which(self.exe)
            if w:
                cands.append(Path(w))
            cands += [Path("/usr/bin") / self.exe, Path("/opt") / self.exe / self.exe]
        found = next((c for c in cands if c.exists()), None)
        if found is None and s == "linux" and self.is_flatpak():
            return "flatpak:" + self.app_id
        return str(found) if found else None

    def cli(self):
        """The command that runs it without its window (<exe>-cli), as an argument list, or None: next to the program
        its installers put (on a Mac inside its app bundle), on the PATH, or the Flatpak's. <PREFIX>_CLI overrides it
        (LIGHTCRAFT_CLI, LIGHTCRAFT_CLASSIC_CLI). AI Remove reads a RAW opened on its own through it."""
        v = os.environ.get(self.var("CLI"))
        if v:
            return [v]
        app = self.app()
        if app and app.startswith("flatpak:"):
            return ["flatpak", "run", f"--command={self.exe}-cli", self.app_id]
        s = system()
        cands = []
        if app:
            a = Path(app)
            cli = f"{self.exe}-cli"
            cands.append(a.with_name(f"{cli}.exe") if s == "windows" else
                         a / "Contents" / "MacOS" / cli if s == "macos" else a.with_name(cli))
        w = shutil.which(f"{self.exe}-cli")
        if w:
            cands.append(Path(w))
        found = next((c for c in cands if c.exists()), None)
        return [str(found)] if found else None

    def process(self):
        """Its process name as pgrep matches it: the kernel keeps 15 characters of it on Linux, 16 on macOS."""
        if system() == "macos":
            return self.mac_process[:16]
        return self.exe[:15]


def _app_paths(exe):
    """Windows: where the App Paths registry key (MSI installers write it) says exe is."""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                found.append(Path(str(winreg.QueryValue(k, None)).strip('"')))
        except OSError:
            pass
    return found


LIGHTCRAFT = Host("lightcraft", "LightCraft", ("LIGHTCRAFT",), "LightCraft", 7980, "lightcraft", ("LightCraft",),
                  ("LightCraft.app",), "LightCraft", "ai.storyteller.lightcraft")
CHROMAFORGE = Host("chromaforge", "Chromaforge", ("LIGHTCRAFT_CLASSIC", "NONAMEYET", "LIGHTCRAFT"),
                   "LightCraft Classic", 7981, "lightcraft-classic", ("Chromaforge", "LightCraft Classic"),
                   ("Chromaforge.app", "LightCraft Classic.app"), "lightcraft-classic", "com.emmertex.chromaforge")
HOSTS = (LIGHTCRAFT, CHROMAFORGE)  # in this order where one has to be picked without a reason (LightCraft came first)


def host_named(key):
    """The app named key ('lightcraft' | 'chromaforge', in any case), else None."""
    return next((h for h in HOSTS if h.key == str(key or "").strip().lower()), None)


def installed_hosts():
    return [h for h in HOSTS if h.app()]


def sam3_host(weights):
    """The app that has downloaded SAM 3 for its Object masks (the file weights in its sam3_dir), else None."""
    return next((h for h in HOSTS if (h.sam3_dir() / weights).exists()), None)


def host_cli():
    """An installed app's command line, to read a RAW opened on its own: (host, command), else (None, None)."""
    return next(((h, h.cli()) for h in HOSTS if h.cli()), (None, None))


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
