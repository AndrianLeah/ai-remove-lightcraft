"""AI Remove for LightCraft — installer for Windows, macOS and Linux.

Started by the double-click files next to it (or by the MCP server), through uv, on a Python 3.12 that uv keeps in the
install folder. Standard library only. What it does, in order (each step can be re-run: it skips what is done):

  1. looks at the computer: OS, graphics card -> which PyTorch build (NVIDIA CUDA, AMD ROCm, Intel XPU, Apple MPS, CPU)
  2. copies the app into the install folder (default: ~/AIRemove — outside AppData on Windows on purpose)
  3. makes a private Python environment there (venv) with PyTorch and the other libraries
  4. downloads the AI models the user chose (LaMa, SAM 3 — or links LightCraft's copy —, SDXL, FLUX)
  5. creates the launcher (AI Remove.exe / app / command) with its icon, a Start menu / Applications / menu entry
  6. sets up LightCraft: its control channel (LIGHTCRAFT_CONTROL_PORT), AI Remove as its external editor and the
     shortcut Ctrl+Shift+X (Cmd+Shift+X on a Mac) for Photo > Edit In > Open Original in Other Editor
  7. checks the result (airemove --check)

  install.py [--dir DIR] [--models lama,sam3,sdxl,flux | recommended | none] [--hf-token TOKEN] [--yes]
             [--torch auto|cuda|rocm|rocm-win|xpu|mps|cpu] [--models-from DIR] [--port 7980] [--no-lightcraft]
  install.py --configure-lightcraft [--dir DIR]      only step 6 (e.g. after closing LightCraft)
  install.py --status [--dir DIR]                    JSON: what is installed
  install.py --uninstall [--keep-models] [--yes]     removes AI Remove and its LightCraft settings (not your photos,
                                                     not the .airemove projects next to them)
"""
import argparse
import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent  # the unzipped package (or the install itself, for repairs)
sys.path.insert(0, str(PKG / "airemove"))
import system  # noqa: E402  (standard library only, shared with the app)
from i18n import _, N_  # noqa: E402

VERSION = system.VERSION
PY_VERSION = "3.12"
TORCH, TORCHVISION = "2.9.1", "0.24.1"
# tested together (Windows / AMD, October 2026); if a pin has no wheel for a platform the newest is taken instead
PACKAGES = ["diffusers==0.41.0", "transformers==5.20.1", "accelerate==1.15.0", "safetensors==0.8.0",
            "huggingface_hub==1.33.0", "peft==0.21.2", "gguf==0.19.0", "sentencepiece==0.2.2", "protobuf",
            "onnxruntime==1.31.0", "numpy==2.5.4", "scipy==1.18.1", "pillow==13.0.0", "tifffile==2026.10.15"]
AMD_WIN = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/"
AMD_WIN_FILES = ["rocm_sdk_core-7.2.1-py3-none-win_amd64.whl", "rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl",
                 "rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl", "rocm-7.2.1.tar.gz",
                 "torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
                 "torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"]
# AMD's PyTorch for Windows: Radeon RX 7000 / 9000, Radeon PRO W7000 / AI PRO, Ryzen AI Max / 300 graphics
AMD_WIN_OK = re.compile(r"RX\s*[79]\d{3}|PRO\s*W7\d{3}|AI\s*PRO|Radeon\s*(8060S|8050S|890M|880M)", re.I)
TORCH_FLAVOURS = {
    "cuda": ("NVIDIA (CUDA)", 4.5), "rocm": ("AMD (ROCm, Linux)", 9.0), "rocm-win": (N_("AMD (ROCm for Windows)"), 6.0),
    "xpu": ("Intel Arc (XPU)", 3.5), "mps": ("Apple Silicon (Metal)", 1.0), "cpu": (N_("processor only"), 1.0)}
MODELS = {  # name: (GB, what (translated where shown), licence, gated repo or None)
    "lama": (0.2, N_("LaMa: quick fill on the processor, for small objects on plain backgrounds"), "Apache-2.0", None),
    "sam3": (3.4, N_("SAM 3: one-click selection (the same model as LightCraft's Object masks)"),
             "SAM License (Meta)", "facebook/sam3"),
    "sdxl": (6.9, N_("SDXL Inpainting: generative variants on the GPU, ~8-15 s each"), "CreativeML Open RAIL++-M",
             None),
    "flux": (16.6, N_("FLUX.1 Fill [dev] + Turbo: the most realistic, needs a 12+ GB GPU"),
             "FLUX.1 [dev] Non-Commercial License", "black-forest-labs/FLUX.1-Fill-dev"),
}
SHORTCUT = "Cmd+Shift+X"  # LightCraft's notation: Cmd = Ctrl on Windows and Linux
EDIT_COMMAND = "photo.openOriginalInExternal"
APP_NAME = "AI Remove"
WIN_UNINSTALL_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIRemoveLightCraft"
MAC_AGENT = "com.airemove.lightcraft-control"


# ------------------------------------------------------------------------------------------------ output
class Out:
    """Console + install.log + install-status.json (the MCP server polls the last two)."""

    def __init__(self):
        self.log_file = None
        self.status_file = None
        self.step = (0, 7)
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    def attach(self, d):
        d.mkdir(parents=True, exist_ok=True)
        self.log_file = d / "install.log"
        self.status_file = d / "install-status.json"

    def write(self, text):
        print(text, flush=True)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    def status(self, state, message="", **extra):
        if self.status_file:
            data = {"state": state, "step": list(self.step), "message": message, "version": VERSION,
                    "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **extra}
            tmp = self.status_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.status_file)

    def title(self, n, text):
        self.step = (n, 7)
        self.write(f"\n[{n}/7] {text}")
        self.status("running", text)


out = Out()


class Stop(Exception):
    pass


def ask(question, default=True, yes=False):
    if yes:
        return default
    hint = _("[Y/n]") if default else _("[y/N]")
    while True:
        try:
            a = input(f"{question} {hint} ").strip().lower()
        except EOFError:
            return default
        if not a:
            return default
        if a[0] in "ysj":  # yes / sì / ja
            return True
        if a[0] == "n":
            return False


def run(cmd, env=None, check=True, quiet=False, cwd=None):
    """Run a command, its output going to the console and the log; returns (code, output)."""
    if not quiet:
        out.write("  $ " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd,
                         text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in p.stdout:
        line = line.rstrip()
        lines.append(line)
        if not quiet:
            out.write("    " + line)
    code = p.wait()
    if check and code:
        raise Stop(_("the command failed ({code}): {command} …", code=code, command=" ".join(str(c) for c in cmd[:4]))
                   + "\n" + "\n".join(lines[-15:]))
    return code, "\n".join(lines)


def output(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                              errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def gb_free(path):
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free / 2 ** 30


# ------------------------------------------------------------------------------------------------ 1. the computer
def detect_gpus():
    """[(vendor, name, VRAM GB or None)] from the OS, without PyTorch."""
    s, gpus = system.system(), []
    nv = output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]) \
        if shutil.which("nvidia-smi") else ""
    for line in nv.splitlines():
        if "," in line:
            name, mem = line.rsplit(",", 1)
            gpus.append(("nvidia", name.strip(), round(float(mem) / 1024, 1) if mem.strip().isdigit() else None))
    if s == "windows":
        ps = ("Get-ItemProperty 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}"
              "\\0*' -ErrorAction SilentlyContinue | ForEach-Object { \"$($_.DriverDesc)|$($_.'HardwareInformation."
              "qwMemorySize')\" }")
        for line in output(["powershell", "-NoProfile", "-Command", ps]).splitlines():
            name, _, mem = line.partition("|")
            name = name.strip()
            if not name or any(g[1] == name for g in gpus):
                continue
            vendor = "amd" if re.search(r"AMD|Radeon", name, re.I) else "intel" if "Intel" in name else \
                "nvidia" if re.search(r"NVIDIA|GeForce|RTX|Quadro", name, re.I) else "other"
            vram = round(int(mem) / 2 ** 30, 1) if mem.strip().isdigit() else None
            gpus.append((vendor, name, vram))
    elif s == "linux":
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
            dev = card / "device"
            try:
                vendor = (dev / "vendor").read_text().strip()
            except OSError:
                continue
            if vendor == "0x1002":
                try:
                    vram = round(int((dev / "mem_info_vram_total").read_text()) / 2 ** 30, 1)
                except (OSError, ValueError):
                    vram = None
                name = next((ln.split(":", 2)[-1].strip() for ln in output(["lspci"]).splitlines()
                             if re.search(r"VGA|Display|3D", ln) and re.search(r"AMD|ATI", ln)), "AMD Radeon")
                gpus.append(("amd", name, vram))
            elif vendor == "0x8086" and "Arc" in output(["lspci"]):
                gpus.append(("intel", "Intel Arc", None))
    elif s == "macos" and platform.machine() == "arm64":
        chip = output(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Apple Silicon"
        mem = output(["sysctl", "-n", "hw.memsize"]).strip()
        gpus.append(("apple", chip, round(int(mem) / 2 ** 30) if mem.isdigit() else None))
    return gpus


def choose_torch(gpus):
    """(flavour, gpu) for this computer."""
    s = system.system()
    if s == "macos":
        if platform.machine() != "arm64":
            raise Stop(_("Macs with an Intel processor are not supported (PyTorch is no longer made for them): "
                         "it needs a Mac with Apple silicon (M1 or later)."))
        return "mps", gpus[0] if gpus else None
    nv = [g for g in gpus if g[0] == "nvidia"]
    if nv:
        return "cuda", nv[0]
    amd = sorted([g for g in gpus if g[0] == "amd"], key=lambda g: -(g[2] or 0))
    if amd and (amd[0][2] or 0) >= 4:  # a dedicated card, not the processor's graphics
        if s == "windows":
            return ("rocm-win" if AMD_WIN_OK.search(amd[0][1]) else "cpu"), amd[0]
        return "rocm", amd[0]
    if s == "windows" and amd and AMD_WIN_OK.search(amd[0][1]):  # Ryzen AI Max: shared memory, size not reported
        return "rocm-win", amd[0]
    arc = [g for g in gpus if g[0] == "intel" and "Arc" in g[1]]
    if arc:
        return "xpu", arc[0]
    return "cpu", None


def recommended_models(flavour, gpu):
    vram = (gpu[2] if gpu else None) or 0
    picks = ["lama", "sam3"]
    if flavour != "cpu" and (vram >= 6 or flavour == "mps" and vram >= 16 or flavour == "rocm-win"):
        picks.append("sdxl")
    return picks


# ------------------------------------------------------------------------------------------------ 2-3. files and Python
def uv_exe():
    """uv: next to the installer (bootstrap put it in <dir>/bin), else on the PATH."""
    env = os.environ.get("AIREMOVE_UV")
    if env and Path(env).exists():
        return env
    w = shutil.which("uv")
    if w:
        return w
    raise Stop(_("uv not found: start the installation with the \"Install\" file for your system (it fetches uv "
                 "by itself)."))


def uv_env(d):
    e = dict(os.environ)
    e["UV_PYTHON_INSTALL_DIR"] = str(d / "python")  # the interpreter outside AppData: LightCraft must see it
    e["UV_PYTHON_PREFERENCE"] = "only-managed"  # a distribution's Python may lack Tk
    e.setdefault("UV_HTTP_TIMEOUT", "300")
    return e


COPY = ["airemove", "mcp", "installer", "assets", "README.md", "README.it.md", "AGENTS.md",
        "THIRD-PARTY-NOTICES.md", "LICENSE.txt"]


def copy_app(d):
    if d.resolve() == PKG.resolve():
        out.write("  " + _("installing in the package folder (no copy)"))
        return
    for name in COPY:
        src = PKG / name
        if not src.exists():
            continue
        dst = d / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
    out.write("  " + _("app copied to {dir}", dir=d))


def venv_python(d):
    return d / "venv" / ("Scripts/python.exe" if system.system() == "windows" else "bin/python")


def make_venv(d, flavour, reinstall=False):
    uv, env = uv_exe(), uv_env(d)
    py = venv_python(d)
    if py.exists() and not reinstall:
        out.write("  " + _("Python environment already there"))
    else:
        # replaces a venv already there (--reinstall, or one left broken): newer uv refuses without it. The variable,
        # not --clear: an older uv on the PATH would reject the flag, and replaced it anyway
        run([uv, "venv", "--python", PY_VERSION, "--seed", str(d / "venv")], env=dict(env, UV_VENV_CLEAR="1"))
    pip = [uv, "pip", "install", "--python", str(py)]
    have_torch = run([py, "-c", "import torch, sys; sys.exit(0)"], check=False, quiet=True)[0] == 0
    if not have_torch or reinstall:
        out.write("  " + _("PyTorch for {build} (~{gb} GB)…", build=_(TORCH_FLAVOURS[flavour][0]),
                                gb=f"{TORCH_FLAVOURS[flavour][1]:.0f}"))
        if flavour == "rocm-win":
            run(pip + [AMD_WIN + f for f in AMD_WIN_FILES], env=env)
        else:
            index = {"cuda": "https://download.pytorch.org/whl/cu128", "rocm": "https://download.pytorch.org/whl/rocm6.4",
                     "xpu": "https://download.pytorch.org/whl/xpu", "cpu": "https://download.pytorch.org/whl/cpu",
                     "mps": None}[flavour]
            if flavour == "cuda" and system.system() == "linux":
                index = None  # PyPI's Linux torch already carries CUDA
            # uv asks an extra index before the default one (PyPI), and takes a package from the first index that has
            # it: PyTorch's index must be the extra one, else PyPI's torch wins (CUDA on Linux, processor-only on
            # Windows) whatever the build asked for
            idx = ["--extra-index-url", index] if index else []
            code, __ = run(pip + idx + [f"torch=={TORCH}", f"torchvision=={TORCHVISION}"], env=env, check=False)
            if code:
                out.write("  " + _("the pinned version is not available here: trying the newest"))
                run(pip + idx + ["torch", "torchvision"], env=env)
    code, __ = run(pip + PACKAGES, env=env, check=False)
    if code:
        out.write("  " + _("some pinned versions are missing for this system: installing the newest"))
        run(pip + [re.split(r"[=<>]", p)[0] for p in PACKAGES], env=env)
    # the launcher: a real program (AI Remove.exe on Windows: no console window) that starts the app
    run(pip + [str(make_launcher_pkg(d))], env=env)
    code, txt = run([py, "-c", "import sys, tkinter; sys.path.insert(0, r'%s'); import system; "
                               "print('DEVICE', *system.gpu_summary())" % (d / "airemove")], check=False, quiet=True)
    dev = next((ln for ln in txt.splitlines() if ln.startswith("DEVICE")), "")
    out.write("  " + _("check: {result}", result=dev[7:] if dev else txt[-300:]))
    if code:
        raise Stop(_("the Python environment does not work:") + "\n" + txt[-800:])
    if flavour != "cpu" and " cpu " in f" {dev} ":
        out.write("  ! " + _("PyTorch does not see the graphics card: check its drivers (AI Remove will work, but "
                               "slowly)"))
    return dev[7:].split(" ", 1)[0] if dev else "cpu"


def make_launcher_pkg(d):
    p = d / "launcher"
    p.mkdir(parents=True, exist_ok=True)
    (p / "airemove_launcher.py").write_text(
        '"""The installed `airemove` program: AI Remove\'s window (or --check / --auto)."""\n'
        "import sys\nfrom pathlib import Path\n\n\n"
        "def main():\n"
        "    root = Path(sys.prefix).resolve().parent  # <install>/venv -> <install>\n"
        "    sys.path.insert(0, str(root / 'airemove'))\n"
        "    import airemove\n"
        "    airemove.run()\n", encoding="utf-8")
    (p / "pyproject.toml").write_text(
        '[project]\nname = "airemove-launcher"\nversion = "%s"\n\n'
        '[project.gui-scripts]\nairemove = "airemove_launcher:main"\n\n'
        '[project.scripts]\nairemove-cli = "airemove_launcher:main"\n\n'
        '[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n'
        '[tool.setuptools]\npy-modules = ["airemove_launcher"]\n' % VERSION, encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------------ 4. models
def get_models(d, wanted, token, models_from):
    py = venv_python(d)
    cmd = [py, str(d / "installer" / "fetch_models.py"), "--dest", str(d / "models"), "--models", ",".join(wanted)]
    if models_from:
        cmd += ["--from", str(models_from)]
    env = dict(os.environ)
    if token:
        env["HF_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    code, txt = run(cmd, env=env, check=False)
    done = re.findall(r"^MODEL_OK (\w+)", txt, re.M)
    failed = re.findall(r"^MODEL_FAIL (\w+) (.*)$", txt, re.M)
    return done, failed


# ------------------------------------------------------------------------------------------------ 5. launchers
def launcher_exe(d):
    return d / "venv" / ("Scripts/airemove.exe" if system.system() == "windows" else "bin/airemove")


def make_shortcuts(d, cfg):
    s = system.system()
    icon = d / "assets" / "icon"
    if s != "windows":  # double-click uninstaller in the install folder (Windows: in Settings > Apps, below)
        u = d / ("Uninstall AI Remove.command" if s == "macos" else "uninstall.sh")
        u.write_text('#!/bin/sh\nD="$(cd "$(dirname "$0")" && pwd)"\n'
                     'AIREMOVE_HOME="$D" sh "$D/installer/bootstrap.sh" --uninstall --dir "$D" "$@"\n', encoding="utf-8")
        u.chmod(0o755)
    if s == "windows":
        programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        lnk = programs / f"{APP_NAME}.lnk"
        ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $s.TargetPath = '%s'; "
              "$s.WorkingDirectory = '%s'; $s.IconLocation = '%s,0'; "
              "$s.Description = '%s'; $s.Save()"
              % (str(lnk).replace("'", "''"), str(launcher_exe(d)).replace("'", "''"),
                 str(d).replace("'", "''"), str(icon / "airemove.ico").replace("'", "''"),
                 _("AI Remove for LightCraft: removes objects from RAW photos").replace("'", "''")))
        run(["powershell", "-NoProfile", "-Command", ps], quiet=True, check=False)
        cfg["shortcut"] = str(lnk)
        size_kb = int(sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024)
        uninst = d / "Uninstall AI Remove.cmd"
        uninst.write_text('@echo off\r\nset "AIREMOVE_HOME=%~dp0"\r\n'
                          'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\\bootstrap.ps1" '
                          '--uninstall %*\r\n', encoding="utf-8")
        for name, typ, val in (("DisplayName", "REG_SZ", "AI Remove for LightCraft"),
                               ("DisplayVersion", "REG_SZ", VERSION),
                               ("Publisher", "REG_SZ", "AI Remove (unofficial LightCraft plug-in)"),
                               ("DisplayIcon", "REG_SZ", str(icon / "airemove.ico")),
                               ("InstallLocation", "REG_SZ", str(d)),
                               ("UninstallString", "REG_SZ", f'"{uninst}"'),
                               ("NoModify", "REG_DWORD", "1"), ("NoRepair", "REG_DWORD", "1"),
                               ("EstimatedSize", "REG_DWORD", str(size_kb))):
            output(["reg", "add", WIN_UNINSTALL_KEY, "/v", name, "/t", typ, "/d", val, "/f"])
        out.write("  " + _("Start menu: {app} · Settings > Apps: \"AI Remove for LightCraft\" (to uninstall)",
                                app=APP_NAME))
        return str(launcher_exe(d))
    if s == "macos":
        app = Path.home() / "Applications" / f"{APP_NAME}.app"
        exe = str(launcher_exe(d)).replace("\\", "\\\\").replace('"', '\\"')
        script = d / "launcher" / "AI Remove.applescript"
        script.write_text(
            'on run\n'
            f'\tdo shell script quoted form of "{exe}" & " > /dev/null 2>&1 &"\n'
            'end run\n\n'
            'on open theFiles\n'
            '\trepeat with f in theFiles\n'
            f'\t\tdo shell script quoted form of "{exe}" & " " & quoted form of POSIX path of f & " > /dev/null 2>&1 &"\n'
            '\t\texit repeat\n'
            '\tend repeat\n'
            'end open\n', encoding="utf-8")
        if app.exists():
            shutil.rmtree(app)
        app.parent.mkdir(parents=True, exist_ok=True)
        run(["osacompile", "-o", str(app), str(script)])
        shutil.copyfile(icon / "airemove.icns", app / "Contents" / "Resources" / "applet.icns")
        # a new icon breaks the applet's signature (it seals its resources): sign it again, ad hoc. Made here, not
        # downloaded, it carries no quarantine, so Gatekeeper lets it run; Apple Silicon needs the valid signature
        output(["codesign", "--force", "--deep", "--sign", "-", str(app)])
        output(["xattr", "-dr", "com.apple.quarantine", str(app)])
        output(["touch", str(app)])
        cfg["shortcut"] = str(app)
        out.write("  " + _("app: {app} (drag it to the Dock if you like)", app=app))
        return str(app)
    # Linux: a menu entry with the icon in the user's icon theme
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    for sz_dir in (icon / "hicolor").iterdir():
        dst = data / "icons" / "hicolor" / sz_dir.name / "apps"
        dst.mkdir(parents=True, exist_ok=True)
        for f in (sz_dir / "apps").iterdir():
            shutil.copyfile(f, dst / f.name)
    entry = data / "applications" / "airemove.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("[Desktop Entry]\nType=Application\nName=AI Remove\n"
                     "GenericName=Object removal for LightCraft\nGenericName[it]=Rimozione oggetti per LightCraft\n"
                     "Comment=Removes objects from LightCraft's RAW photos with AI\n"
                     "Comment[it]=Rimuove oggetti dai RAW di LightCraft con l'AI\n"
                     f'Exec="{launcher_exe(d)}" %f\nIcon=airemove\nTerminal=false\n'
                     "Categories=Graphics;Photography;\nStartupWMClass=Airemove\n", encoding="utf-8")
    output(["update-desktop-database", str(entry.parent)])
    cfg["shortcut"] = str(entry)
    editor = str(launcher_exe(d))
    if system.flatpak_lightcraft():  # LightCraft in its sandbox starts the editor inside it: hop out to the host
        hop = d / "airemove-flatpak.sh"
        hop.write_text(f'#!/bin/sh\nexec flatpak-spawn --host "{launcher_exe(d)}" "$@"\n', encoding="utf-8")
        hop.chmod(0o755)
        editor = str(hop)
    out.write("  " + _("applications menu: AI Remove ({entry})", entry=entry))
    return editor


# ------------------------------------------------------------------------------------------------ 6. LightCraft
def lc_running():
    s = system.system()
    if s == "windows":
        return "lightcraft.exe" in output(["tasklist", "/FI", "IMAGENAME eq lightcraft.exe", "/NH"]).lower()
    if s == "macos":
        return bool(output(["pgrep", "-x", "LightCraft"]).strip())
    return bool(output(["pgrep", "-x", "lightcraft"]).strip())


def lc_request(port, method, params, timeout=10):
    """One control-channel request to the running LightCraft (None if it does not answer)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as c:
            c.settimeout(timeout)
            c.sendall((json.dumps({"id": 1, "method": method, "params": params}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = c.recv(65536)
                if not chunk:
                    return None
                buf += chunk
            return json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace").lstrip("﻿"))
    except (OSError, ValueError):
        return None


def set_control_port(port, cfg):
    """LIGHTCRAFT_CONTROL_PORT for LightCraft started from now on (it reads it at start)."""
    s, done = system.system(), []
    if s == "windows":
        output(["setx", "LIGHTCRAFT_CONTROL_PORT", str(port)])
        done.append(_("user variable LIGHTCRAFT_CONTROL_PORT"))
    elif s == "macos":
        agent = Path.home() / "Library" / "LaunchAgents" / f"{MAC_AGENT}.plist"
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n'
            f'  <key>Label</key><string>{MAC_AGENT}</string>\n'
            '  <key>ProgramArguments</key><array><string>/bin/launchctl</string><string>setenv</string>'
            f'<string>LIGHTCRAFT_CONTROL_PORT</string><string>{port}</string></array>\n'
            '  <key>RunAtLoad</key><true/>\n</dict></plist>\n', encoding="utf-8")
        output(["launchctl", "setenv", "LIGHTCRAFT_CONTROL_PORT", str(port)])
        output(["launchctl", "load", "-w", str(agent)])
        done.append(f"LaunchAgent {agent.name}")
    else:
        envd = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "environment.d"
        envd.mkdir(parents=True, exist_ok=True)
        (envd / "60-lightcraft-control.conf").write_text(f"LIGHTCRAFT_CONTROL_PORT={port}\n", encoding="utf-8")
        done.append(_("~/.config/environment.d (from the next login)"))
        output(["systemctl", "--user", "set-environment", f"LIGHTCRAFT_CONTROL_PORT={port}"])
        if system.flatpak_lightcraft():
            output(["flatpak", "override", "--user", f"--env=LIGHTCRAFT_CONTROL_PORT={port}", "--share=network",
                    f"--filesystem={cfg['dir']}", "--talk-name=org.freedesktop.Flatpak", system.LIGHTCRAFT_ID])
            done.append(_("Flatpak permissions (local network, AI Remove's folder, starting programs)"))
            cfg["flatpak_override"] = True
        else:  # the menu entry starts LightCraft with the channel on, without waiting for a new login
            data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
            src = next((Path(p) / "applications" / f"{system.LIGHTCRAFT_ID}.desktop" for p in
                        (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
                        if (Path(p) / "applications" / f"{system.LIGHTCRAFT_ID}.desktop").exists()), None)
            if src:
                text = src.read_text(encoding="utf-8")
                text = re.sub(r"^Exec=(?!env LIGHTCRAFT_CONTROL_PORT)", f"Exec=env LIGHTCRAFT_CONTROL_PORT={port} ",
                              text, flags=re.M)
                data.mkdir(parents=True, exist_ok=True)
                (data / src.name).write_text(text, encoding="utf-8")
                cfg["desktop_override"] = str(data / src.name)
                done.append(_("LightCraft's menu entry"))
    cfg["port"], cfg["control_env"] = port, True
    return done


def ui_json():
    return system.lightcraft_config_dir() / "ui.json"


def is_ours(value, d, cfg):
    """Whether LightCraft's external editor is this install's AI Remove — never another program, nor another copy of
    AI Remove (uninstalling a second install must not unhook the first)."""
    if not value:
        return False
    norm = lambda x: os.path.normcase(os.path.abspath(str(x)))  # noqa: E731
    v = norm(value)
    return v in [norm(x) for x in (cfg.get("editor"), cfg.get("shortcut")) if x] or v.startswith(norm(d) + os.sep)


def edit_ui_json(editor, remove=None):
    """Set (or clear) the external editor and the shortcut in LightCraft's ui.json — only while LightCraft is closed
    (it rewrites the file when it quits). Written in place: on Windows a new file under AppData made from inside a
    packaged app (the Claude app) would be invisible to LightCraft. remove: a test of the current editor (is_ours);
    the editor and the shortcut are cleared only when it says yes. Returns whether the file was changed."""
    p = ui_json()
    data = {}
    if p.exists():
        raw = p.read_text(encoding="utf-8-sig")
        data = json.loads(raw) if raw.strip() else {}
        backup = p.with_name("ui.json.before-airemove")
        if not backup.exists() and not remove:
            backup.write_text(raw, encoding="utf-8")
    st = data.setdefault("settings", {})
    km = st.setdefault("keymap", {})
    if remove:
        if not remove(st.get("externalEditor")):
            return False
        st["externalEditor"] = ""
        if km.get(EDIT_COMMAND) == SHORTCUT:
            km.pop(EDIT_COMMAND, None)
    else:
        st["externalEditor"] = editor
        km[EDIT_COMMAND] = SHORTCUT
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    with open(p, "r+" if p.exists() else "w", encoding="utf-8") as f:
        f.seek(0)
        f.write(text)
        f.truncate()
    return True


def configure_lightcraft(d, cfg, editor, yes=False):
    """Returns (state, message): state 'done' | 'pending' (LightCraft must be closed first)."""
    port = int(cfg.get("port") or system.DEFAULT_PORT)
    notes = set_control_port(port, cfg)
    out.write("  " + _("control channel: {how}", how=", ".join(notes)))
    cfg["editor"] = editor
    if lc_request(port, "engine.execute", {"command": "library.state", "params": {}}):
        r1 = lc_request(port, "ui.set", {"settings": {"externalEditor": editor}})
        r2 = lc_request(port, "engine.execute", {"command": "app.setShortcut",
                                                 "params": {"id": EDIT_COMMAND, "shortcut": SHORTCUT}})
        if r1 and r1.get("ok"):
            msg = _("LightCraft is open: external editor set right away")
            if not (r2 and r2.get("ok")):
                msg += " " + _("(shortcut not set: {error})", error=(r2 or {}).get("error"))
            cfg["lightcraft"] = "done"
            return "done", msg
    tries = 0
    while lc_running():
        if yes or tries >= 3:
            cfg["lightcraft"] = "pending"
            return "pending", _("LightCraft is open: close it, then run the configuration again "
                                "(install --configure-lightcraft, or the MCP tool configure_lightcraft)")
        input("  " + _("LightCraft is open: close it (save your work), then press Enter… "))
        tries += 1
    edit_ui_json(editor)
    cfg["lightcraft"] = "done"
    return "done", _("settings written to {file}", file=ui_json())


# ------------------------------------------------------------------------------------------------ status / uninstall
def read_cfg(d):
    try:
        return json.loads((d / "airemove.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def write_cfg(d, cfg):
    (d / "airemove.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")


def status(d):
    cfg = read_cfg(d)
    rep = {"installed": venv_python(d).exists(), "dir": str(d), "config": cfg, "os": system.system(),
           "lightcraft_app": system.lightcraft_app(), "lightcraft_running": lc_running(),
           "lightcraft_reachable": system.lightcraft_reachable(int(cfg.get("port") or system.DEFAULT_PORT)),
           "lightcraft_settings": str(system.lightcraft_config_dir())}
    try:
        st = json.loads(ui_json().read_text(encoding="utf-8-sig")).get("settings", {})
        rep["lightcraft_editor"] = st.get("externalEditor")
        rep["lightcraft_shortcut"] = (st.get("keymap") or {}).get(EDIT_COMMAND)
    except (OSError, ValueError):
        pass
    if rep["installed"]:
        __, txt = run([venv_python(d), str(d / "airemove" / "airemove.py"), "--check"], check=False, quiet=True)
        try:
            rep["check"] = json.loads(txt[txt.index("{"):])
        except ValueError:
            rep["check_output"] = txt[-1000:]
    print(json.dumps(rep, indent=1, ensure_ascii=False))


def uninstall(d, keep_models, yes):
    cfg = read_cfg(d)
    s = system.system()
    if not ask((_("Uninstall AI Remove from {dir}, keeping the models?", dir=d) if keep_models else
                _("Uninstall AI Remove from {dir}?", dir=d)) + " " +
               _("The photos, the DNGs made and the .airemove projects next to the RAWs stay."), True, yes):
        return
    port = int(cfg.get("port") or system.DEFAULT_PORT)
    ours = lambda v: is_ours(v, d, cfg)  # noqa: E731
    live = lc_request(port, "ui.set", {})  # no change: replies with LightCraft's current settings
    if live and live.get("ok"):
        st = (live.get("result") or {}).get("settings") or {}
        if ours(st.get("externalEditor")):
            lc_request(port, "ui.set", {"settings": {"externalEditor": ""}})
            if (st.get("keymap") or {}).get(EDIT_COMMAND) == SHORTCUT:
                lc_request(port, "engine.execute", {"command": "app.setShortcut",
                                                    "params": {"id": EDIT_COMMAND, "shortcut": ""}})
            out.write("  " + _("LightCraft: external editor removed"))
        else:
            out.write("  " + _("LightCraft: its external editor is not this installation, left as it is"))
    elif not lc_running():
        try:
            done = edit_ui_json("", remove=ours)
            out.write("  " + (_("LightCraft: external editor and shortcut removed") if done else
                              _("LightCraft: its external editor is not this installation, left as it is")))
        except (OSError, ValueError) as e:
            out.write("  ! " + _("ui.json not changed: {error}", error=e))
    else:
        out.write("  ! " + _("LightCraft is open: remove the external editor yourself in Settings > External "
                             "Editing"))
    if cfg.get("control_env"):
        if s == "windows":
            output(["reg", "delete", "HKCU\\Environment", "/v", "LIGHTCRAFT_CONTROL_PORT", "/f"])
        elif s == "macos":
            agent = Path.home() / "Library" / "LaunchAgents" / f"{MAC_AGENT}.plist"
            output(["launchctl", "unload", str(agent)])
            output(["launchctl", "unsetenv", "LIGHTCRAFT_CONTROL_PORT"])
            agent.unlink(missing_ok=True)
        else:
            envd = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "environment.d"
            (envd / "60-lightcraft-control.conf").unlink(missing_ok=True)
            output(["systemctl", "--user", "unset-environment", "LIGHTCRAFT_CONTROL_PORT"])
            if cfg.get("desktop_override"):
                Path(cfg["desktop_override"]).unlink(missing_ok=True)
            if cfg.get("flatpak_override"):
                output(["flatpak", "override", "--user", "--unset-env=LIGHTCRAFT_CONTROL_PORT",
                        f"--nofilesystem={d}", "--no-talk-name=org.freedesktop.Flatpak", system.LIGHTCRAFT_ID])
        out.write("  " + _("LightCraft's control channel: removed"))
    sc = cfg.get("shortcut")
    if sc and Path(sc).exists():
        (shutil.rmtree if Path(sc).is_dir() else os.remove)(sc)
    if s == "windows":
        output(["reg", "delete", WIN_UNINSTALL_KEY, "/f"])
    elif s == "linux":
        data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        for f in (data / "icons" / "hicolor").glob("*/apps/airemove.*"):
            f.unlink(missing_ok=True)
    keep = {"models"} if keep_models else set()
    left = []
    for item in list(d.iterdir()) if d.exists() else []:
        if item.name in keep:
            continue
        if s == "windows" and item.suffix.lower() == ".cmd":
            # cmd may be running it (Settings > Apps, the MCP server): removed now, cmd would stop with "the batch
            # file cannot be found" and exit code 1. Removed with what is in use, below
            left.append(item)
            continue
        try:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        except OSError:
            left.append(item)  # in use: on Windows this very Python; removed once it has quit
    if left and s == "windows":
        import tempfile
        bat = Path(tempfile.gettempdir()) / "airemove-uninstall.cmd"
        lines = ["@echo off", "ping 127.0.0.1 -n 4 >nul"]
        lines += [f'rmdir /s /q "{p}" 2>nul & del /f /q "{p}" 2>nul' for p in left]
        if not keep:
            lines.append(f'rmdir /s /q "{d}" 2>nul')
        lines.append('del "%~f0"')
        bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x00000008 | 0x00000200)  # detached
    out.write(_("AI Remove uninstalled.") + (" " + _("The models stay in {dir}.", dir=d / "models")
                                              if keep_models else ""))


# ------------------------------------------------------------------------------------------------ main
def parse():
    ap = argparse.ArgumentParser(description="Install AI Remove for LightCraft")
    ap.add_argument("--dir", help="install folder (default: ~/AIRemove)")
    ap.add_argument("--models", default=None, help="lama,sam3,sdxl,flux | recommended | none")
    ap.add_argument("--hf-token", default=None, help="Hugging Face token (only for SAM 3 / FLUX, models with a licence to accept)")
    ap.add_argument("--hf-token-file", default=None, help="file holding the token (read, then deleted: the MCP server uses it)")
    ap.add_argument("--torch", default="auto", choices=["auto"] + list(TORCH_FLAVOURS))
    ap.add_argument("--models-from", default=None, help="another install's models/ folder to reuse")
    ap.add_argument("--port", type=int, default=None, help="port of LightCraft's control channel (7980)")
    ap.add_argument("--no-lightcraft", action="store_true", help="leave LightCraft's settings alone")
    ap.add_argument("--yes", "-y", action="store_true", help="no questions (recommended choices)")
    ap.add_argument("--reinstall", action="store_true", help="rebuild the Python environment")
    ap.add_argument("--configure-lightcraft", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--keep-models", action="store_true")
    return ap.parse_args()


def install_dir(args):
    return Path(args.dir or os.environ.get("AIREMOVE_HOME") or Path.home() / "AIRemove").expanduser().resolve()


def main():
    args = parse()
    d = install_dir(args)
    if args.status:
        return status(d)
    if args.uninstall:
        return uninstall(d, args.keep_models, args.yes)
    out.attach(d)
    cfg = read_cfg(d)
    cfg.update({"version": VERSION, "dir": str(d)})
    if args.port:
        cfg["port"] = args.port
    if args.configure_lightcraft:
        out.title(6, "LightCraft")
        state, msg = configure_lightcraft(d, cfg, cfg.get("editor") or str(launcher_exe(d)), args.yes)
        write_cfg(d, cfg)
        out.write("  " + msg)
        out.status(state if state != "done" else "done", msg)
        return 0 if state == "done" else 2

    out.write(_("AI Remove for LightCraft {version} — installation ({os})", version=VERSION,
                os=f"{platform.system()} {platform.machine()}"))
    out.title(1, _("The computer"))
    gpus = detect_gpus()
    for g in gpus:
        out.write("  " + _("graphics: {name}", name=g[1]) + (f" ({g[2]:g} GB)" if g[2] else ""))
    flavour, gpu = choose_torch(gpus) if args.torch == "auto" else (args.torch, gpus[0] if gpus else None)
    out.write(f"  PyTorch: {_(TORCH_FLAVOURS[flavour][0])}")
    if flavour == "cpu":
        out.write("  ! " + _("no usable GPU: LaMa and the selection will work; SDXL would be very slow"))
    lc = system.lightcraft_app()
    out.write("  LightCraft: " + (lc or _("not found (install it from getartcraft.com: AI Remove works inside "
                                            "LightCraft)")))
    lc_sam = (system.lightcraft_sam3_dir() / "model.safetensors").exists()

    # models: what to download
    if args.models in (None, "recommended"):
        wanted = recommended_models(flavour, gpu)
        if args.models is None and not args.yes:
            wanted = ["lama", "sam3"]
            if ask(_("Install SDXL ({gb} GB, generative variants on the GPU)?", gb=MODELS["sdxl"][0]),
                   "sdxl" in recommended_models(flavour, gpu)):
                wanted.append("sdxl")
            if flavour != "cpu" and ask(_("Install FLUX too ({gb} GB, the most realistic; it needs a Hugging Face "
                                          "token and a 12+ GB GPU)?", gb=MODELS["flux"][0]), False):
                wanted.append("flux")
    elif args.models == "none":
        wanted = []
    else:
        wanted = [m.strip() for m in args.models.split(",") if m.strip() in MODELS]
    if "lama" not in wanted and args.models != "none":
        wanted.insert(0, "lama")
    from fetch_models import complete  # noqa: E402  (next to this file; standard library only)
    have = {m for m in MODELS if complete(d / "models", m) or
            (args.models_from and complete(Path(args.models_from), m)) or (m == "sam3" and lc_sam)}
    need = [m for m in wanted if m not in have]
    total = TORCH_FLAVOURS[flavour][1] + sum(MODELS[m][0] for m in need)
    out.write("  " + _("folder: {dir}  ·  free space {free} GB  ·  needed ~{need} GB", dir=d,
                         free=f"{gb_free(d):.0f}", need=f"{total:.0f}"))
    for m in wanted:
        gb, what, lic, gated = MODELS[m]
        src = (_("already in LightCraft: linked (0 GB)") if m == "sam3" and lc_sam else
               _("already there (0 GB)") if m in have else f"{gb:g} GB")
        out.write(f"   · {_(what)} — {src} — " + _("licence {licence}", licence=lic))
    if gb_free(d) < total + 2:
        raise Stop(_("not enough space: free at least {gb} GB or pick another folder (--dir)",
                     gb=f"{total + 2 - gb_free(d):.0f}"))
    token = args.hf_token or os.environ.get("HF_TOKEN")
    if args.hf_token_file:
        try:
            token = Path(args.hf_token_file).read_text(encoding="utf-8").strip() or token
            Path(args.hf_token_file).unlink()
        except OSError:
            pass
    gated = [m for m in need if MODELS[m][3]]
    if gated and not token and not args.yes:
        out.write("\n  " + _("{models}: a licence to accept on Hugging Face:", models=", ".join(MODELS[m][3] for m in gated))
                  + "\n  " + _("1) make an account on huggingface.co  2) open {pages} and accept the licence  "
                               "3) make a token (Read) at https://huggingface.co/settings/tokens",
                               pages=", ".join(f"https://huggingface.co/{MODELS[m][3]}" for m in gated)))
        try:
            token = getpass.getpass("  " + _("Paste the token (hidden; Enter to skip these models): ")).strip()
        except (EOFError, KeyboardInterrupt):
            token = ""
    if gated and not token:
        for m in gated:
            out.write("  " + _("skipping {model}: it needs the Hugging Face token", model=m)
                      + (" " + _("(selection will be with the brush)") if m == "sam3" else ""))
            wanted.remove(m)
    if not ask(_("Go ahead?"), True, args.yes):
        raise Stop(_("cancelled"))

    out.title(2, _("The app's files"))
    d.mkdir(parents=True, exist_ok=True)
    copy_app(d)
    (d / "work").mkdir(exist_ok=True)

    out.title(3, _("Python environment and PyTorch (the longest step)"))
    device = make_venv(d, flavour, args.reinstall)
    cfg.update({"torch": flavour, "device": device, "gpu": gpu[1] if gpu else None})
    write_cfg(d, cfg)

    out.title(4, _("AI models"))
    done, failed = get_models(d, wanted, token, args.models_from) if wanted else ([], [])
    cfg["models"] = sorted(set(cfg.get("models", [])) | set(done))
    for m, why in failed:
        out.write("  ! " + _("{model} not installed: {why}", model=m, why=why))
    write_cfg(d, cfg)

    out.title(5, _("Program, icon and menu"))
    editor = make_shortcuts(d, cfg)
    write_cfg(d, cfg)

    out.title(6, "LightCraft")
    if args.no_lightcraft:
        out.write("  " + _("skipped (--no-lightcraft)"))
        lc_state, lc_msg = "skipped", _("LightCraft not configured")
    else:
        lc_state, lc_msg = configure_lightcraft(d, cfg, editor, args.yes)
        out.write("  " + lc_msg)
    write_cfg(d, cfg)

    out.title(7, _("Check"))
    __, txt = run([venv_python(d), str(d / "airemove" / "airemove.py"), "--check"], check=False, quiet=True)
    try:
        rep = json.loads(txt[txt.index("{"):])
        out.write("  " + _("device: {gpu} · usable models: {models} · LightCraft {state}", gpu=rep.get("gpu"),
                             models=", ".join(rep.get("usable_models", [])),
                             state=_("connected") if rep["lightcraft"]["connected"] else _("not reachable now")))
    except ValueError:
        out.write(txt[-800:])
    key = "Cmd+Shift+X" if system.system() == "macos" else "Ctrl+Shift+X"
    final = (_("Done. Restart LightCraft, then select a RAW photo and press {key} (Photo > Edit In > Open Original "
               "in Other Editor). Or open \"AI Remove\" from the menu.", key=key) if lc_state != "skipped" else
             _("Done. In LightCraft select a RAW photo and press {key} (Photo > Edit In > Open Original in Other "
               "Editor). Or open \"AI Remove\" from the menu.", key=key))
    if lc_state == "pending":
        final += " " + _("FIRST: close LightCraft and finish the configuration (see above).")
    if failed:
        final += " " + _("Some models were not installed (see above).")
    out.write("\n" + final)
    out.status("done" if lc_state != "pending" else "pending_lightcraft", final, models=cfg.get("models"),
               failed=[f"{m}: {w}" for m, w in failed])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        out.write("\n" + _("INSTALLATION STOPPED: {error}", error=e))
        out.status("failed", str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        out.status("failed", _("interrupted"))
        sys.exit(130)
    except Exception as e:
        import traceback
        out.write(traceback.format_exc())
        out.status("failed", f"{type(e).__name__}: {e}")
        sys.exit(1)
