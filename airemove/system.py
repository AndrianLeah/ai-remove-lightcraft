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


def save_config(**changes):
    """airemove.json with these keys changed (None: the key removed), the rest as it was; what the Settings window
    changes after the installation. Written in place, as the installer does: the same file, read again at every use."""
    cfg = config()
    for k, v in changes.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    CONFIG_FILE.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    return cfg


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


class Names:
    """One of the names an app has had (Chromaforge's brand.toml: the current ones, then [legacy]): exe its program's
    (the command line is <exe>-cli), settings its settings folder's, prefixes those of the environment variables it
    reads, in the order it reads them (its own first, then the ones it falls back to), mac_app its Mac app bundle,
    mac_process the process name there."""

    def __init__(self, exe, settings, prefixes, mac_app, mac_process):
        self.exe, self.settings, self.prefixes = exe, settings, prefixes
        self.mac_app, self.mac_process = mac_app, mac_process

    def __repr__(self):
        return f"Names({self.exe})"


class Host:
    """An app AI Remove works inside: LightCraft, or Chromaforge (github.com/emmertex/chromaforge, first named
    LightCraft Classic), a fork of LightCraft with the same control channel, commands, command line and SAM 3 folder
    under names of its own — and a token its control channel asks for before anything else.

    names: the names it has had, the current ones first. Chromaforge 26.45 renamed everything (chromaforge.exe,
    %APPDATA%\\Chromaforge, CHROMAFORGE_*); a build from before is still lightcraft-classic.exe with "LightCraft
    Classic" and LIGHTCRAFT_CLASSIC_*. The names in use (names_now) are the build's that is found: running, chosen in
    the Settings window, or installed — the newest one when none is.

    An app reads its environment variables with its own prefix first, then with the ones it had before. The current
    Chromaforge falls back to NONAMEYET_*, then LIGHTCRAFT_* — LightCraft's own: LIGHTCRAFT_CONTROL_PORT alone opens
    its channel on LightCraft's port, where it collides with LightCraft (clash) — and only then LIGHTCRAFT_CLASSIC_*.
    env() reads them the same way; the installer sets the variables under every prefix of its own (own_vars), so old
    and new builds both find theirs first.

    key: AI Remove's own name for it (--app, airemove.json, the MCP tools); folders: its Windows install folders'
    names; app_id: its Flatpak and desktop entry id. The program and the command line chosen in the Settings window
    (airemove.json "app_paths") come before the ones found."""

    def __init__(self, key, name, names, port, folders, app_id):
        self.key, self.name, self.names = key, name, names
        self.default_port, self.folders, self.app_id = port, folders, app_id

    def __repr__(self):
        return f"Host({self.key})"

    # ---- the names in use
    def chosen(self):
        """{"app": path, "cli": path}: what the user chose in the Settings window (airemove.json "app_paths")."""
        d = (config().get("app_paths") or {}).get(self.key)
        return {k: v for k, v in d.items() if k in ("app", "cli") and isinstance(v, str) and v} \
            if isinstance(d, dict) else {}

    def names_of(self, program):
        """The names whose program this file (or app bundle) is, else None."""
        p = Path(str(program))
        if p.suffix.lower() == ".app":  # a bundle: the program inside says which build it is, whatever its name
            n = next((n for n in self.names if (p / "Contents" / "MacOS" / n.exe).exists()), None)
            if n is not None:
                return n
        stem = p.name.lower()
        for n in self.names:
            if stem in (n.exe, f"{n.exe}.exe", n.mac_app.lower()):
                return n
        return None

    def names_now(self):
        """The names of the build in use: the program running, else the one chosen or installed, else the newest."""
        for prog in running_programs():
            n = self.names_of(prog)
            if n is not None:
                return n
        app = self.app()
        return (self.names_of(app) if app else None) or self.names[0]

    @property
    def exe(self):
        return self.names_now().exe

    @property
    def prefixes(self):
        return self.names_now().prefixes

    @property
    def settings(self):
        return self.names_now().settings

    def programs(self):
        """Every file name its program has had: chromaforge.exe, lightcraft-classic.exe (and the chosen one's)."""
        ext = ".exe" if system() == "windows" else ""
        out = [n.exe + ext for n in self.names]
        if self.chosen().get("app"):
            out.append(Path(self.chosen()["app"]).name)
        return list(dict.fromkeys(x.lower() for x in out))

    def own_prefixes(self):
        """The prefixes that are the app's own under one of its names (CHROMAFORGE, LIGHTCRAFT_CLASSIC): the ones a
        build reads first. Never another app's (LIGHTCRAFT)."""
        return list(dict.fromkeys(n.prefixes[0] for n in self.names))

    def var(self, name):
        """The variable NAME under the app's current prefix (CHROMAFORGE_CONTROL_PORT): the one messages name."""
        return f"{self.names[0].prefixes[0]}_{name}"

    def own_vars(self, name):
        """The variable NAME under every prefix of its own, the current one first: the ones AI Remove sets."""
        return [f"{p}_{name}" for p in self.own_prefixes()]

    def env(self, name, names=None):
        """The variable NAME as the app (the build in use, or names) reads it: its own prefix, else an older one."""
        names = names or self.names_now()
        return next((os.environ[f"{p}_{name}"] for p in names.prefixes if os.environ.get(f"{p}_{name}")), None)

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

    def clash(self):
        """The other app whose control port this one takes too, else None: Chromaforge 26.45 without
        CHROMAFORGE_CONTROL_PORT reads LIGHTCRAFT_CONTROL_PORT, the one the installer sets for LightCraft. Then only one
        of the two opens its channel (the first started) and AI Remove cannot tell which one answers: setting the app
        up again (installer, Settings window) sets its own variable."""
        if self is LIGHTCRAFT:
            return None
        return LIGHTCRAFT if self.port() == LIGHTCRAFT.port() else None

    def reachable(self, port=None, timeout=1.0):
        try:
            with socket.create_connection(("127.0.0.1", port or self.port()), timeout=timeout):
                return True
        except OSError:
            return False

    def answers(self, timeout=1.0):
        """Something answers on its port, and as far as can be told it is this app: with a clash (both apps on one
        port) the one of the two that is running; both running, LightCraft (it reads its own variable, and only the
        first one started gets the port: here LightCraft, normally open first)."""
        if not self.reachable(timeout=timeout):
            return False
        other = self.clash() or next((h for h in HOSTS if h is not self and h.clash() is self), None)
        if other is None:
            return True
        mine, theirs = self.running(), other.running()
        if bool(mine) != bool(theirs):
            return bool(mine)
        return self is LIGHTCRAFT

    def token(self, port=None):
        """The token its control channel wants first, if it wants one (Chromaforge; LightCraft so far does not):
        the CONTROL_TOKEN variable, else the file control-token-<port> the app writes in its settings folder at every
        start — the folder of the build in use, else the newest such file in the folder of another of its names."""
        v = self.env("CONTROL_TOKEN")
        if v:
            return v.strip()
        name = f"control-token-{port or self.port()}"
        first = self.config_dir() / name
        others = sorted((p for p in (self.config_dir(n) / name for n in self.names) if p != first and p.is_file()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        for p in [first] + others:
            try:
                t = p.read_text("utf-8").strip()
                if t:
                    return t
            except OSError:
                pass
        return None

    def is_flatpak(self):
        """True when the app is the Flatpak (Linux). Asked once a minute at most: names_now asks often."""
        if system() != "linux" or not shutil.which("flatpak"):
            return False
        import subprocess
        import time
        when, was = getattr(self, "_flatpak", (0.0, False))
        if time.monotonic() - when < 60:
            return was
        try:
            now = subprocess.run(["flatpak", "info", self.app_id], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            now = False
        self._flatpak = (time.monotonic(), now)
        return now

    def config_dir(self, names=None):
        """Its settings folder (the build in use's, or names'): the CONFIG_DIR variable, else macOS ~/Library/
        Application Support/<settings> · Windows %APPDATA%\\<settings> · Linux $XDG_CONFIG_HOME/<settings in lower
        case> (the Flatpak's: ~/.var/app/<id>/config/<the same>)."""
        names = names or self.names_now()
        v = self.env("CONFIG_DIR", names)
        if v:
            return Path(v)
        home = Path.home()
        s = system()
        if s == "macos":
            return home / "Library" / "Application Support" / names.settings
        if s == "windows":
            return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / names.settings
        flat = home / ".var" / "app" / self.app_id / "config" / names.settings.lower()
        native = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / names.settings.lower()
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

    def sam3_dirs(self):
        """Every folder where one of its builds keeps SAM 3: the one in use first."""
        dirs = [self.sam3_dir()] + [Path(self.env("SAM3_DIR", n) or self.config_dir(n) / "models" / "sam3")
                                    for n in self.names]
        return list(dict.fromkeys(dirs))

    def found_apps(self):
        """[(program or app bundle, where)], every one found where its installers put it, the current names first;
        where: "installed" (its install folder, App Paths, /Applications, the PATH) or "flatpak"."""
        s = system()
        cands = []
        if s == "windows":
            for n in self.names:
                for var in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
                    d = os.environ.get(var)
                    for f in self.folders if d else ():
                        sub = ("Programs", f) if var == "LOCALAPPDATA" else (f,)
                        cands.append(Path(d, *sub, f"{n.exe}.exe"))
                cands += _app_paths(f"{n.exe}.exe")  # installed in a folder of the user's choice
        elif s == "macos":
            cands = [base / n.mac_app for n in self.names
                     for base in (Path("/Applications"), Path.home() / "Applications")]
        else:
            for n in self.names:
                w = shutil.which(n.exe)
                if w:
                    cands.append(Path(w))
                cands += [Path("/usr/bin") / n.exe, Path("/opt") / n.exe / n.exe]
        seen, out = set(), []
        for c in cands:
            if c.exists() and _norm(c) not in seen:
                seen.add(_norm(c))
                out.append((str(c), "installed"))
        if not out and s == "linux" and self.is_flatpak():
            out.append(("flatpak:" + self.app_id, "flatpak"))
        return out

    def app(self):
        """The program (or app bundle): the one chosen in the Settings window while it is there, else the first one
        found where its installers put it, else None."""
        c = self.chosen().get("app")
        if c and Path(c).exists():
            return c
        found = self.found_apps()
        return found[0][0] if found else None

    def cli_names(self):
        return [f"{n.exe}-cli" for n in self.names]

    def cli_next_to(self, app):
        """Its command line next to the program (on a Mac inside its app bundle), under any of its names, else None."""
        s, a = system(), Path(app)
        for cli in self.cli_names():
            c = (a.with_name(f"{cli}.exe") if s == "windows" else
                 a / "Contents" / "MacOS" / cli if s == "macos" else a.with_name(cli))
            if c.is_file():
                return str(c)
        return None

    def cli(self):
        """The command that runs it without its window (<exe>-cli), as an argument list, or None: <PREFIX>_CLI under a
        prefix of its own (LIGHTCRAFT_CLI; CHROMAFORGE_CLI, LIGHTCRAFT_CLASSIC_CLI), else the one chosen in the Settings
        window, else next to its program (on a Mac inside its app bundle), on the PATH, or the Flatpak's. AI Remove
        reads a RAW opened on its own through it."""
        v = next((os.environ[x] for x in self.own_vars("CLI") if os.environ.get(x)), None)
        if v:
            return [v]
        c = self.chosen().get("cli")
        if c and Path(c).is_file():
            return [c]
        app = self.app()
        if app and app.startswith("flatpak:"):
            return ["flatpak", "run", f"--command={self.names_now().exe}-cli", self.app_id]
        found = self.cli_next_to(app) if app else None
        if found:
            return [found]
        w = next((shutil.which(n) for n in self.cli_names() if shutil.which(n)), None)
        return [w] if w else None

    def process(self):
        """Its process name as pgrep matches it: the kernel keeps 15 characters of it on Linux, 16 on macOS."""
        n = self.names_now()
        if system() == "macos":
            return n.mac_process[:16]
        return n.exe[:15]

    def processes(self):
        """Every process name it has had, as pgrep matches it."""
        return list(dict.fromkeys((n.mac_process[:16] if system() == "macos" else n.exe[:15]) for n in self.names))

    def running(self):
        """The program of its running process, else None (running_programs)."""
        return next((p for p in running_programs() if self.names_of(p) is not None
                     or Path(p).name.lower() in self.programs()), None)


_RUNNING = [0.0, []]  # (when, what): listed again at most every RUNNING_TTL seconds
RUNNING_TTL = 2.0


def running_programs(fresh=False):
    """The programs of the processes running now, as full paths where the system says them (Windows, Linux; macOS:
    ps gives the executable's path). Standard library only; [] when they cannot be listed. Kept for RUNNING_TTL
    seconds (Host.names_now asks often), unless fresh."""
    import time
    if fresh or time.monotonic() - _RUNNING[0] > RUNNING_TTL:
        _RUNNING[:] = [time.monotonic(), _list_programs()]
    return _RUNNING[1]


def _list_programs():
    s = system()
    if s == "windows":
        return _win_processes()
    import subprocess
    if s == "linux":
        out = []
        try:
            for d in os.scandir("/proc"):
                if d.name.isdigit():
                    try:
                        out.append(os.readlink(f"/proc/{d.name}/exe"))
                    except OSError:
                        pass
        except OSError:
            pass
        return out
    try:
        txt = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in txt.splitlines():
        line = line.strip()
        m = re.match(r"(.*?\.app)/Contents/MacOS/", line)
        out.append(m.group(1) if m else line)  # the app bundle, as the Settings window chooses it
    return out


def _win_processes():
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out = []
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            path = e.szExeFile
            h = k32.OpenProcess(0x1000, False, e.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    path = buf.value
                k32.CloseHandle(h)
            out.append(path)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def find_programs(host, folder, depth=4, limit=4000):
    """{"app": program, "cli": command line} that the folder (or a few levels below it) holds for the app, under any
    of its names: the Settings window's "Look in a folder…". Breadth first, at most `limit` folders; {} for none."""
    s = system()
    found, level, seen = {}, [Path(folder)], 0
    apps = {(n.mac_app if s == "macos" else n.exe + (".exe" if s == "windows" else "")).lower() for n in host.names}
    clis = {c + (".exe" if s == "windows" else "") for c in host.cli_names()}
    for __ in range(depth + 1):
        deeper = []
        for d in level:
            seen += 1
            try:
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda e: e.name.lower())
            except OSError:
                continue
            for e in entries:
                low = e.name.lower()
                if "app" not in found and low in apps and (e.is_dir() if s == "macos" else e.is_file()):
                    found["app"] = e.path
                    nxt = host.cli_next_to(e.path)
                    if nxt and "cli" not in found:
                        found["cli"] = nxt
                elif "cli" not in found and low in clis and e.is_file():
                    found["cli"] = e.path
                elif e.is_dir() and not e.name.startswith(".") and not (s == "macos" and low.endswith(".app")):
                    deeper.append(Path(e.path))
            if ("app" in found and "cli" in found) or seen >= limit:
                return found
        level = deeper
    return found


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


LIGHTCRAFT = Host("lightcraft", "LightCraft",
                  [Names("lightcraft", "LightCraft", ("LIGHTCRAFT",), "LightCraft.app", "LightCraft")],
                  7980, ("LightCraft",), "ai.storyteller.lightcraft")
# emmertex/chromaforge's brand.toml: [product] / [identity] now, [legacy] before (its env_prefixes in its order, after
# its own). The Mac disk image also carries a hidden "LightCraft Classic.app" copy of a new build: names_of tells them
# apart by the program inside (cli_next_to looks for every name's)
CHROMAFORGE = Host("chromaforge", "Chromaforge",
                   [Names("chromaforge", "Chromaforge",
                          ("CHROMAFORGE", "NONAMEYET", "LIGHTCRAFT", "LIGHTCRAFT_CLASSIC"), "Chromaforge.app",
                          "chromaforge"),
                    Names("lightcraft-classic", "LightCraft Classic", ("LIGHTCRAFT_CLASSIC", "NONAMEYET", "LIGHTCRAFT"),
                          "LightCraft Classic.app", "lightcraft-classic")],
                   7981, ("Chromaforge", "LightCraft Classic"), "com.emmertex.chromaforge")
HOSTS = (LIGHTCRAFT, CHROMAFORGE)  # in this order where one has to be picked without a reason (LightCraft came first)


def host_named(key):
    """The app named key ('lightcraft' | 'chromaforge', in any case), else None."""
    return next((h for h in HOSTS if h.key == str(key or "").strip().lower()), None)


def installed_hosts():
    return [h for h in HOSTS if h.app()]


def sam3_host(weights):
    """The app that has downloaded SAM 3 for its Object masks (the file weights in its sam3_dir), else None."""
    return next((h for h in HOSTS if (h.sam3_dir() / weights).exists()), None) or \
        next((h for h in HOSTS for d in h.sam3_dirs() if (d / weights).exists()), None)


def sam3_file(weights):
    """The SAM 3 weights an app downloaded (sam3_host), in the folder of whichever of its builds has them, else None."""
    return next((d / weights for h in HOSTS for d in h.sam3_dirs() if (d / weights).exists()), None)


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
