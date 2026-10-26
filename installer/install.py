"""AI Remove for LightCraft and Chromaforge — installer for Windows, macOS and Linux.

Started by the double-click files next to it (or by the MCP server), through uv, on a Python 3.12 that uv keeps in the
install folder. Standard library only. What it does, in order (each step can be re-run: it skips what is done):

  1. looks at the computer: OS, graphics card -> which PyTorch build (NVIDIA CUDA, AMD ROCm, Intel XPU, Apple MPS, CPU)
  2. copies the app into the install folder (default: ~/AIRemove — outside AppData on Windows on purpose)
  3. makes a private Python environment there (venv) with PyTorch and the other libraries
  4. downloads the AI models the user chose (LaMa, SAM 3 — or links LightCraft's copy —, RORem, FLUX, OSOR,
     Qwen-Image) and removes the ones AI Remove no longer uses from its own models folder (RETIRED);
     a model the user already has in a folder of their own is used from there (airemove.json "model_paths")
  5. creates the launcher (AI Remove.exe / app / command) with its icon, a Start menu / Applications / menu entry
  6. sets up the apps chosen — LightCraft, Chromaforge (LightCraft Classic) or both, asked at the start (--apps): the
     app's control channel (LIGHTCRAFT_CONTROL_PORT 7980, LIGHTCRAFT_CLASSIC_CONTROL_PORT 7981), AI Remove as its
     external editor and the shortcut Ctrl+Shift+X (Cmd+Shift+X on a Mac) for Photo > Edit In > Open Original in
     Other Editor
  7. checks the result (airemove --check)

  install.py [--dir DIR] [--models lama,sam3,rorem,flux,osor,qwen | recommended | none]
             [--yes] [--model-dir MODEL=FOLDER ...] [--hf-token TOKEN] [--torch auto|cuda|rocm|rocm-win|xpu|mps|cpu]
             [--models-from DIR] [--apps lightcraft|chromaforge|both|none] [--port 7980] [--no-lightcraft]
  install.py --configure-lightcraft [--apps …] [--dir DIR]   only step 6 (e.g. after closing the app, or installing
                                                             Chromaforge); asks which apps unless --apps / --yes
  install.py --status [--dir DIR]                    JSON: what is installed
  install.py --uninstall [--keep-models] [--yes]     removes AI Remove and its settings in the apps (not your photos,
                                                     not the .airemove projects next to them)
--yes without --apps: the apps chosen last time (an install from before Chromaforge: LightCraft), else the ones
installed, else LightCraft.
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
import model_files as mf  # noqa: E402  (standard library only, shared with the app: the same checks)
import system  # noqa: E402  (standard library only, shared with the app)
from i18n import _, N_, num  # noqa: E402

VERSION = system.VERSION
PY_VERSION = "3.12"
TORCH, TORCHVISION = "2.9.1", "0.24.1"
# tested together (Windows / AMD, October 2026); if a pin has no wheel for a platform the newest is taken instead
PACKAGES = ["diffusers==0.41.0", "transformers==5.20.1", "accelerate==1.15.0", "safetensors==0.8.0",
            "huggingface_hub==1.33.0", "peft==0.21.2", "gguf==0.19.0", "sentencepiece==0.2.2", "protobuf",
            "onnxruntime==1.31.0", "numpy==2.5.4", "scipy==1.18.1", "pillow==13.0.0", "tifffile==2026.10.15",
            "pillow-heif==1.8.1"]  # HEIC pictures (its wheels: GPLv2, see THIRD-PARTY-NOTICES.md); AVIF is Pillow's
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
MODELS = mf.MODELS  # what each model is for, its download and licence, its files (airemove/model_files.py)
GPU_ONLY = ("flux", "osor", "qwen")  # not offered without a GPU (they fail on the processor)
# models AI Remove had and no longer uses: their folders in the install's own models/ are removed at the next run (a
# folder of the user's own is never touched). ObjectClear (7.3 GB): "Include the shadow" with SAM 3 and OSOR, then RORem
# or FLUX, does its job sharper; it worked at 512 px.
RETIRED = {"objectclear": ("objectclear",)}
# Qwen-Image: its 8B text encoder (~10 GB in FP8) and then its transformer with the picture's attention cache (~10 GB)
# take a 16 GB card, next to what the desktop and LightCraft keep on it (2-4 GB). Measured on an RX 7800 XT 16 GB; the
# runtimes it needs (CUDA, ROCm) are NVIDIA's and AMD's.
QWEN_VRAM, QWEN_TORCH = 15.5, ("cuda", "rocm", "rocm-win")
SHORTCUT = "Cmd+Shift+X"  # LightCraft's notation: Cmd = Ctrl on Windows and Linux
APP_KEY = "Cmd+Shift+X" if system.system() == "macos" else "Ctrl+Shift+X"  # the same, as the user presses it
EDIT_COMMAND = "photo.openOriginalInExternal"
APP_NAME = "AI Remove"
WIN_UNINSTALL_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIRemoveLightCraft"
MAC_AGENT = "com.airemove.lightcraft-control"
# a photo's project (<raw>.airemove): its own file type, which opens the photo in AI Remove when double-clicked
WIN_PROJECT_CLASS = "AIRemove.Project"
MAC_PROJECT_UTI = "com.airemove.project"
LINUX_PROJECT_MIME = "application/x-airemove-project"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/"
              "lsregister")


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
        self.note(text)

    def note(self, text):
        """To the log only (what the user typed is on the screen already)."""
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    def status(self, state, message="", **extra):
        """install-status.json, replaced whole: a reader never sees half of it. On Windows the replace fails while
        another program has the file open (the MCP server's install_status, a Get-Content poll; sharing delete does not
        help): tried again for half a second, then left for the next status — install.log has everything."""
        if self.status_file:
            data = {"state": state, "step": list(self.step), "message": message, "version": VERSION,
                    "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **extra}
            tmp = self.status_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            for __ in range(10):
                try:
                    os.replace(tmp, self.status_file)
                    return
                except PermissionError:
                    time.sleep(0.05)

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


def qwen_fits(flavour, gpu):
    """Qwen-Image runs on this GPU: NVIDIA or AMD, 16 GB or more (QWEN_VRAM)."""
    return flavour in QWEN_TORCH and ((gpu[2] if gpu else None) or 0) >= QWEN_VRAM


def retire_models(models_dir):
    """The models AI Remove no longer uses (RETIRED), removed from its own models folder: a link to a folder of the
    user's own (a junction, a symlink) is unlinked, never followed; hard-linked files lose only this link."""
    for model, parts in RETIRED.items():
        for part in parts:
            p = models_dir / part
            if not (p.exists() or p.is_symlink()):
                continue
            try:
                if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                    p.unlink()
                else:
                    size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2 ** 30  # as the sizes shown
                    shutil.rmtree(p)
                    out.write("  " + _("{model} is no longer used by AI Remove: its folder removed ({gb} GB freed)",
                                       model=model, gb=num(size)))
            except OSError as e:
                out.write("  ! " + _("{model} is no longer used: remove {dir} by hand ({error})", model=model, dir=p,
                                     error=e))


def recommended_models(flavour, gpu):
    vram = (gpu[2] if gpu else None) or 0
    picks = ["lama", "sam3"]
    if flavour != "cpu" and (vram >= 6 or flavour == "mps" and vram >= 16 or flavour == "rocm-win"):
        picks.append("rorem")  # with SDXL's files
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
YES, NO = ("y", "yes", "s", "si", "sì", "j", "ja"), ("n", "no", "nein")
FOLDER = ("f", "folder", "c", "cartella", "d", "dir")


def para(text, first="  ", rest="    "):
    """A paragraph wrapped to the console."""
    import textwrap
    width = max(60, min(shutil.get_terminal_size((100, 20)).columns, 110) - 1)
    out.write(textwrap.fill(text, width, initial_indent=first, subsequent_indent=rest))


def prompt(text):
    try:
        a = input(text).strip()
    except EOFError:
        a = ""
    out.note(text + a)
    return a


def clean_path(text):
    """A folder as typed, pasted or dragged into the console: without quotes, file:// and (macOS, Linux) the
    backslashes before spaces; a file stands for the folder it is in."""
    t = text.strip()
    if len(t) > 1 and t[0] == t[-1] and t[0] in "'\"":
        t = t[1:-1]
    if t.startswith("file://"):
        from urllib.parse import unquote, urlparse
        t = unquote(urlparse(t).path)
        if re.match(r"/[A-Za-z]:", t):
            t = t[1:]
    elif system.system() != "windows":
        t = re.sub(r"\\(.)", r"\1", t)
    p = Path(os.path.abspath(Path(t).expanduser()))
    return p.parent if p.is_file() else p


def look(model, folder):
    """The model's parts in a folder of the user's: ({part: folder}, "") — or ({}, why not)."""
    f, name = clean_path(str(folder)), MODELS[model].name
    if not f.is_dir():
        return {}, _("{model}: {folder} is not a folder", model=name, folder=f)
    out.write("    " + _("looking for {model} in {folder} …", model=name, folder=f))
    found = mf.find_model(model, f)
    if not found:
        return {}, _("{model}: nothing of it in {folder} (it looks for files like {files}, there or a few levels "
                     "below)", model=name, folder=f, files=mf.looks_for(model))
    return found, ""


def say_found(model, found):
    for p in MODELS[model].parts:
        out.write("    " + (_("found: {part} in {folder}", part=p, folder=found[p]) if p in found else
                            _("not in that folder, to download: {part} ({gb} GB)", part=p, gb=num(mf.PARTS[p].gb))))


def ask_model(model, default, required):
    """y / n / the folder where the user already has the model. Returns None (no), {} (download it) or
    {part: folder} (use it from there)."""
    hint = _("[Y/folder]") if required else _("[Y/n/folder]") if default else _("[y/N/folder]")
    while True:
        a = prompt("    " + _("Install {model}?", model=MODELS[model].name) + f" {hint} ")
        if not a:
            return {} if default or required else None
        if a.lower() in YES:
            return {}
        if a.lower() in NO:
            if not required:
                return None
            out.write("    " + _("LaMa is always installed: it is the window's quick fill"))
            return {}
        if a.lower() in FOLDER:
            a = prompt("    " + _("Folder (you can drag it here): "))
            if not a:
                continue
        found, why = look(model, a)
        if found:
            say_found(model, found)
            return found
        para(why, "    ! ", "      ")


def choose_models(flavour, gpu, installed, given, sam_host):
    """The questions, model by model: what it is for, its download and its licence; y, n, or the folder where the
    user already has it (what is there goes into given). Returns the models wanted."""
    rec = recommended_models(flavour, gpu)
    out.write("")
    para(_("The AI models: what each one is for, its download and its licence. Answer y to install it or n to skip "
           "it, or give the folder where you already have it (another AI Remove, a Hugging Face cache, ComfyUI's "
           "models; you can drag the folder into this window): it is used from there, not downloaded again."),
         "  ", "  ")
    wanted = []
    for m, mod in MODELS.items():
        if not mod.offered:  # SDXL: RORem brings its files
            continue
        if m in GPU_ONLY and flavour == "cpu" and m not in given and m not in installed:
            continue
        if m == "qwen" and not qwen_fits(flavour, gpu) and m not in given and m not in installed:
            continue
        if m == "osor" and "flux" not in wanted + installed:
            continue  # it runs on FLUX
        lc = m == "sam3" and sam_host is not None
        out.write("")
        para(f"{mod.name} — {_(mod.what)}")
        notes = [f"{num(mod.gb)} GB", _("licence {licence}", licence=mod.licence)]
        if mod.gated and not lc and m not in installed:
            notes.append(_("needs a free Hugging Face token (its licence accepted)"))
        para(" · ".join(notes), "    ", "      ")
        if m in installed:
            out.write("    " + _("already installed, kept"))
        elif m in given:
            say_found(m, given[m])
            wanted.append(m)
        elif lc:
            out.write("    " + _("already in {app}: linked, nothing to download", app=sam_host.name))
            wanted.append(m)
        else:
            ans = ask_model(m, m in ("lama", "sam3") or m in rec, m == "lama")
            if ans is not None:
                wanted.append(m)
                given.update({m: ans} if ans else {})
    if flavour == "cpu":
        out.write("")
        para(_("FLUX and OSOR need a graphics card: not offered on this computer (--models installs them "
               "anyway)."))
    elif not qwen_fits(flavour, gpu) and "qwen" not in wanted + installed:
        out.write("")
        para(_("Qwen-Image needs an NVIDIA or AMD graphics card with 16 GB or more: not offered on this computer "
               "(--models installs it anyway)."))
    return wanted


def get_models(d, wanted, token, models_from, paths):
    py = venv_python(d)
    cmd = [py, str(d / "installer" / "fetch_models.py"), "--dest", str(d / "models"), "--models", ",".join(wanted),
           "--paths", json.dumps({p: str(f) for p, f in paths.items()})]
    if models_from:
        cmd += ["--from", str(models_from)]
    env = dict(os.environ)
    if token:
        env["HF_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    __, txt = run(cmd, env=env, check=False)  # what failed is in its MODEL_FAIL lines, not its exit code
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
                 _("AI Remove for LightCraft and Chromaforge: removes objects from photos").replace("'", "''")))
        run(["powershell", "-NoProfile", "-Command", ps], quiet=True, check=False)
        cfg["shortcut"] = str(lnk)
        size_kb = int(sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024)
        uninst = d / "Uninstall AI Remove.cmd"
        uninst.write_text('@echo off\r\nset "AIREMOVE_HOME=%~dp0"\r\n'
                          'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\\bootstrap.ps1" '
                          '--uninstall %*\r\n', encoding="utf-8")
        for name, typ, val in (("DisplayName", "REG_SZ", "AI Remove for LightCraft and Chromaforge"),
                               ("DisplayVersion", "REG_SZ", VERSION),
                               ("Publisher", "REG_SZ", "AI Remove (unofficial plug-in for LightCraft and Chromaforge)"),
                               ("DisplayIcon", "REG_SZ", str(icon / "airemove.ico")),
                               ("InstallLocation", "REG_SZ", str(d)),
                               ("UninstallString", "REG_SZ", f'"{uninst}"'),
                               ("NoModify", "REG_DWORD", "1"), ("NoRepair", "REG_DWORD", "1"),
                               ("EstimatedSize", "REG_DWORD", str(size_kb))):
            output(["reg", "add", WIN_UNINSTALL_KEY, "/v", name, "/t", typ, "/d", val, "/f"])
        out.write("  " + _("Start menu: {app} · Settings > Apps: \"AI Remove for LightCraft and Chromaforge\" "
                           "(to uninstall)", app=APP_NAME))
        win_project_type(f'"{launcher_exe(d)}" "%1"', str(icon / "airemove-project.ico"))
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
        mac_project_type(app, icon / "airemove-project.icns")
        # a new icon breaks the applet's signature (it seals its resources): sign it again, ad hoc. Made here, not
        # downloaded, it carries no quarantine, so Gatekeeper lets it run; Apple Silicon needs the valid signature
        output(["codesign", "--force", "--deep", "--sign", "-", str(app)])
        output(["xattr", "-dr", "com.apple.quarantine", str(app)])
        output(["touch", str(app)])
        output([LSREGISTER, "-f", str(app)])  # Finder learns the .airemove type now, not at the next login
        cfg["shortcut"] = str(app)
        out.write("  " + _("app: {app} (drag it to the Dock if you like)", app=app))
        return str(app)
    # Linux: a menu entry with the icon in the user's icon theme
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    for sz_dir, kind in ((s, k) for s in (icon / "hicolor").iterdir() for k in ("apps", "mimetypes")):
        if not (sz_dir / kind).is_dir():  # apps: the app's icon; mimetypes: the .airemove files'
            continue
        dst = data / "icons" / "hicolor" / sz_dir.name / kind
        dst.mkdir(parents=True, exist_ok=True)
        for f in (sz_dir / kind).iterdir():
            shutil.copyfile(f, dst / f.name)
    entry = data / "applications" / "airemove.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("[Desktop Entry]\nType=Application\nName=AI Remove\n"
                     "GenericName=Object removal for LightCraft and Chromaforge\n"
                     "GenericName[it]=Rimozione oggetti per LightCraft e Chromaforge\n"
                     "Comment=Removes objects from photos with AI, in LightCraft, in Chromaforge or on its own\n"
                     "Comment[it]=Rimuove oggetti dalle foto con l'AI, in LightCraft, in Chromaforge o da solo\n"
                     f'Exec="{launcher_exe(d)}" %f\nIcon=airemove\nTerminal=false\n'
                     f"Categories=Graphics;Photography;\nMimeType={LINUX_PROJECT_MIME};\nStartupWMClass=Airemove\n",
                     encoding="utf-8")
    output(["update-desktop-database", str(entry.parent)])
    linux_project_type(data)
    cfg["shortcut"] = str(entry)
    editor = str(launcher_exe(d))
    if any(h.is_flatpak() for h in system.HOSTS):  # the app in its sandbox starts the editor inside it: hop out
        hop = d / "airemove-flatpak.sh"
        hop.write_text(f'#!/bin/sh\nexec flatpak-spawn --host "{launcher_exe(d)}" "$@"\n', encoding="utf-8")
        hop.chmod(0o755)
        editor = str(hop)
    out.write("  " + _("applications menu: AI Remove ({entry})", entry=entry))
    return editor


def win_project_type(command=None, icon=None):
    """Windows, for this user: a double-clicked .airemove runs `command` ("%1" = the file); without a command the
    file type is removed, with what Explorer noted about it once a project was opened (FileExts: its "open with"
    list). Explorer is told, so the files' icons change at once."""
    classes = "HKCU\\Software\\Classes\\"
    if command is None:
        for key in (classes + ".airemove", classes + WIN_PROJECT_CLASS,
                    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\.airemove"):
            output(["reg", "delete", key, "/f"])
    else:
        for key, val in ((".airemove", WIN_PROJECT_CLASS), (WIN_PROJECT_CLASS, _("AI Remove project")),
                         (WIN_PROJECT_CLASS + "\\DefaultIcon", icon),
                         (WIN_PROJECT_CLASS + "\\shell\\open\\command", command)):
            output(["reg", "add", classes + key, "/ve", "/d", val, "/f"])
        out.write("  " + _(".airemove projects: a double-click opens the photo in AI Remove"))
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


def mac_project_type(app, icns):
    """macOS: the app declares the .airemove type and opens it (its applet's `on open` gets the file); the files
    show `icns`, copied into the app as project.icns. Written into the app before it is signed; LaunchServices is
    told after."""
    import plistlib
    shutil.copyfile(icns, app / "Contents" / "Resources" / "project.icns")
    plist = app / "Contents" / "Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info.setdefault("CFBundleIdentifier", "com.airemove.app")  # LaunchServices files document types under it
    info["UTExportedTypeDeclarations"] = [{
        "UTTypeIdentifier": MAC_PROJECT_UTI, "UTTypeDescription": _("AI Remove project"),
        "UTTypeConformsTo": ["public.data"], "UTTypeIconFile": "project",
        "UTTypeTagSpecification": {"public.filename-extension": ["airemove"]}}]
    info.setdefault("CFBundleDocumentTypes", []).append({
        "CFBundleTypeName": _("AI Remove project"), "CFBundleTypeRole": "Editor", "LSHandlerRank": "Owner",
        "LSItemContentTypes": [MAC_PROJECT_UTI], "CFBundleTypeIconFile": "project"})
    plist.write_bytes(plistlib.dumps(info))
    out.write("  " + _(".airemove projects: a double-click opens the photo in AI Remove"))


def linux_project_type(data, remove=False):
    """Linux: *.airemove is its own file type (a zip, as it is), opened by AI Remove's menu entry (its MimeType=)."""
    mime = data / "mime"
    xml = mime / "packages" / "airemove.xml"
    apps = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mimeapps.list"
    if remove:
        xml.unlink(missing_ok=True)
        try:  # the default xdg-mime set below
            lines = apps.read_text(encoding="utf-8").splitlines(keepends=True)
            kept = [x for x in lines if not x.startswith(LINUX_PROJECT_MIME + "=")]
            if kept != lines:
                apps.write_text("".join(kept), encoding="utf-8")
        except OSError:
            pass
    else:
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
                       f'  <mime-type type="{LINUX_PROJECT_MIME}">\n'
                       '    <comment>AI Remove project</comment>\n'
                       '    <comment xml:lang="it">Progetto di AI Remove</comment>\n'
                       '    <sub-class-of type="application/zip"/>\n'
                       '    <icon name="airemove-project"/>\n'
                       '    <glob pattern="*.airemove"/>\n'
                       '  </mime-type>\n'
                       '</mime-info>\n', encoding="utf-8")
    output(["update-mime-database", str(mime)])
    if not remove:  # before the archive managers, which open any zip
        output(["xdg-mime", "default", "airemove.desktop", LINUX_PROJECT_MIME])
        out.write("  " + _(".airemove projects: a double-click opens the photo in AI Remove"))


# ------------------------------------------------------------------------------------------------ 6. the apps
def lc_running(host=system.LIGHTCRAFT):
    """Whether the app (LightCraft, Chromaforge) is running, with or without its control channel."""
    if system.system() == "windows":
        return f"{host.exe}.exe" in output(["tasklist", "/FI", f"IMAGENAME eq {host.exe}.exe", "/NH"]).lower()
    return bool(output(["pgrep", "-x", host.process()]).strip())


def lc_request(port, method, params, timeout=10, host=system.LIGHTCRAFT):
    """One control-channel request to the running app (None if it does not answer); after its token, on the same
    connection, when the app wants one (Chromaforge). A refused token: that reply."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as c:
            c.settimeout(timeout)
            token, buf = host.token(port), b""
            for n, (m, p) in enumerate(([("auth", {"token": token})] if token else []) + [(method, params)], 1):
                c.sendall((json.dumps({"id": n, "method": m, "params": p}) + "\n").encode())
                while b"\n" not in buf:
                    chunk = c.recv(65536)
                    if not chunk:
                        return None
                    buf += chunk
                line, buf = buf.split(b"\n", 1)
                reply = json.loads(line.decode("utf-8", "replace").lstrip("﻿"))
                if m == "auth" and not reply.get("ok"):
                    return reply
            return reply
    except (OSError, ValueError):
        return None


def mac_agent(host):
    """The LaunchAgent that sets the app's control port at login (LightCraft's kept its name from before)."""
    return MAC_AGENT if host is system.LIGHTCRAFT else f"com.airemove.{host.key}-control"


def set_control_port(port, cfg, host=system.LIGHTCRAFT):
    """The app's <PREFIX>_CONTROL_PORT (LIGHTCRAFT_CONTROL_PORT, LIGHTCRAFT_CLASSIC_CONTROL_PORT) for the app started
    from now on (it reads it at start)."""
    s, done, var = system.system(), [], host.var("CONTROL_PORT")
    if s == "windows":
        output(["setx", var, str(port)])
        done.append(_("user variable {variable}", variable=var))
    elif s == "macos":
        agent = Path.home() / "Library" / "LaunchAgents" / f"{mac_agent(host)}.plist"
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n'
            f'  <key>Label</key><string>{mac_agent(host)}</string>\n'
            '  <key>ProgramArguments</key><array><string>/bin/launchctl</string><string>setenv</string>'
            f'<string>{var}</string><string>{port}</string></array>\n'
            '  <key>RunAtLoad</key><true/>\n</dict></plist>\n', encoding="utf-8")
        output(["launchctl", "setenv", var, str(port)])
        output(["launchctl", "load", "-w", str(agent)])
        done.append(f"LaunchAgent {agent.name}")
    else:
        envd = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "environment.d"
        envd.mkdir(parents=True, exist_ok=True)
        (envd / f"60-{host.key}-control.conf").write_text(f"{var}={port}\n", encoding="utf-8")
        done.append(_("~/.config/environment.d (from the next login)"))
        output(["systemctl", "--user", "set-environment", f"{var}={port}"])
        if host.is_flatpak():
            output(["flatpak", "override", "--user", f"--env={var}={port}", "--share=network",
                    f"--filesystem={cfg['dir']}", "--talk-name=org.freedesktop.Flatpak", host.app_id])
            done.append(_("Flatpak permissions (local network, AI Remove's folder, starting programs)"))
            cfg[host.cfg_key("flatpak_override")] = True
        else:  # the menu entry starts the app with the channel on, without waiting for a new login
            data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
            src = next((Path(p) / "applications" / f"{host.app_id}.desktop" for p in
                        (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
                        if (Path(p) / "applications" / f"{host.app_id}.desktop").exists()), None)
            if src:
                text = src.read_text(encoding="utf-8")
                text = re.sub(rf"^Exec=(?!env {var})", f"Exec=env {var}={port} ", text, flags=re.M)
                data.mkdir(parents=True, exist_ok=True)
                (data / src.name).write_text(text, encoding="utf-8")
                cfg[host.cfg_key("desktop_override")] = str(data / src.name)
                done.append(_("{app}'s menu entry", app=host.name))
    cfg[host.cfg_key("port")], cfg[host.cfg_key("control_env")] = port, True
    return done


def unset_control_port(d, cfg, host=system.LIGHTCRAFT):
    """Undo set_control_port."""
    s, var = system.system(), host.var("CONTROL_PORT")
    if s == "windows":
        output(["reg", "delete", "HKCU\\Environment", "/v", var, "/f"])
    elif s == "macos":
        agent = Path.home() / "Library" / "LaunchAgents" / f"{mac_agent(host)}.plist"
        output(["launchctl", "unload", str(agent)])
        output(["launchctl", "unsetenv", var])
        agent.unlink(missing_ok=True)
    else:
        envd = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "environment.d"
        (envd / f"60-{host.key}-control.conf").unlink(missing_ok=True)
        output(["systemctl", "--user", "unset-environment", var])
        if cfg.get(host.cfg_key("desktop_override")):
            Path(cfg[host.cfg_key("desktop_override")]).unlink(missing_ok=True)
        if cfg.get(host.cfg_key("flatpak_override")):
            output(["flatpak", "override", "--user", f"--unset-env={var}",
                    f"--nofilesystem={d}", "--no-talk-name=org.freedesktop.Flatpak", host.app_id])
    out.write("  " + _("{app}'s control channel: removed", app=host.name))


def ui_json(host=system.LIGHTCRAFT):
    return host.ui_json()


def is_ours(value, d, cfg):
    """Whether the app's external editor is this install's AI Remove — never another program, nor another copy of
    AI Remove (uninstalling a second install must not unhook the first)."""
    if not value:
        return False
    norm = lambda x: os.path.normcase(os.path.abspath(str(x)))  # noqa: E731
    v = norm(value)
    return v in [norm(x) for x in (cfg.get("editor"), cfg.get("shortcut")) if x] or v.startswith(norm(d) + os.sep)


def edit_ui_json(editor, remove=None, host=system.LIGHTCRAFT):
    """Set (or clear) the external editor and the shortcut in the app's ui.json — only while the app is closed
    (it rewrites the file when it quits). Written in place: on Windows a new file under AppData made from inside a
    packaged app (the Claude app) would be invisible to the app. remove: a test of the current editor (is_ours);
    the editor and the shortcut are cleared only when it says yes. Returns whether the file was changed."""
    p = ui_json(host)
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


def default_apps(cfg):
    """The apps to set up when nobody is asked: the ones chosen last time; LightCraft for an install from before
    Chromaforge (an update does not take over Chromaforge's external editor unasked); else the ones installed, else
    LightCraft (it may be installed after AI Remove)."""
    if isinstance(cfg.get("apps"), list):
        return [h for h in system.HOSTS if h.key in cfg["apps"]]
    if cfg.get("lightcraft"):
        return [system.LIGHTCRAFT]
    return system.installed_hosts() or [system.LIGHTCRAFT]


def parse_apps(value):
    """--apps: lightcraft, chromaforge, both (or lightcraft,chromaforge), none."""
    v = value.strip().lower()
    if v in ("both", "all"):
        return list(system.HOSTS)
    if v == "none":
        return []
    hosts = [system.host_named(x) for x in v.split(",") if x.strip()]
    if not hosts or None in hosts:
        raise Stop(_("--apps wants lightcraft, chromaforge, both or none (it was: {value})", value=value))
    return [h for h in system.HOSTS if h in hosts]


def choose_apps(cfg, yes):
    """The question: which apps AI Remove is set up for — LightCraft, Chromaforge or both, each said found or not;
    the default is the ones chosen last time, else the ones found."""
    default = default_apps(cfg)
    if yes:
        return default
    options = {str(n): [h] for n, h in enumerate(system.HOSTS, 1)}
    options.update({str(len(system.HOSTS) + 1): list(system.HOSTS), "0": []})
    out.write("")
    para(_("AI Remove works inside LightCraft and inside Chromaforge (LightCraft Classic): it becomes the app's "
           "external editor, on {key}, and turns on its control channel. Which one should it be set up for?",
           key=APP_KEY), "  ", "  ")
    for n, h in enumerate(system.HOSTS, 1):
        out.write(f"    {n}) {h.name} — " + (h.app() or _("not found on this computer")))
    out.write(f"    {len(system.HOSTS) + 1}) " + _("both"))
    out.write("    0) " + _("neither (their settings are left alone)"))
    dflt = next((k for k, v in options.items() if v == default), "1")
    while True:
        try:
            a = input("  " + _("Choice [{default}]: ", default=dflt)).strip()
        except EOFError:
            a = ""
        if a in options or not a:
            return options[a or dflt]


def wait_closed(host, yes):
    """Whether the app is closed, now or once the user has closed it (asked up to three times; never with --yes):
    its ui.json can then be written, which it rewrites when it quits."""
    tries = 0
    while lc_running(host):
        if yes or tries >= 3:
            return False
        input("  " + _("{app} is open: close it (save your work), then press Enter… ", app=host.name))
        tries += 1
    return True


def configurable(host):
    """Whether the app can be set up now: LightCraft always (it may be installed after AI Remove, as before
    Chromaforge); Chromaforge once it is installed or has run (one never opened gets only its port: see
    configure_lightcraft)."""
    return host is system.LIGHTCRAFT or bool(host.app()) or host.config_dir().is_dir()


def configure_lightcraft(d, cfg, editor, yes=False, host=system.LIGHTCRAFT):
    """Set up one app (LightCraft or Chromaforge). Returns (state, message): state 'done' | 'pending' (the app must be
    closed first) | 'first_run' (Chromaforge never opened: it must be opened once first)."""
    port = int(cfg.get(host.cfg_key("port")) or host.default_port)
    notes = set_control_port(port, cfg, host)
    out.write("  " + _("control channel: {how}", how=", ".join(notes)))
    cfg["editor"] = editor
    if host is not system.LIGHTCRAFT and not host.config_dir().is_dir():
        # never opened: its settings folder made now (ui.json) would stop Chromaforge copying LightCraft's at its
        # first start (models, preferences). The port is set (a variable, no folder); the rest waits for that start
        cfg[host.key] = "pending"
        return "first_run", _("{app} has never been opened: open it once, close it, then run the configuration again "
                              "(install --configure-lightcraft, or the MCP tool configure_lightcraft) for its external "
                              "editor and shortcut", app=host.name)
    if lc_request(port, "engine.execute", {"command": "library.state", "params": {}}, host=host):
        r1 = lc_request(port, "ui.set", {"settings": {"externalEditor": editor}}, host=host)
        if r1 and r1.get("ok"):
            # the shortcut only once the editor is this AI Remove: else it would start whatever editor the app had
            r2 = lc_request(port, "engine.execute", {"command": "app.setShortcut",
                                                     "params": {"id": EDIT_COMMAND, "shortcut": SHORTCUT}}, host=host)
            msg = _("{app} is open: external editor set right away", app=host.name)
            if not (r2 and r2.get("ok")):
                msg += " " + _("(shortcut not set: {error})", error=(r2 or {}).get("error"))
            cfg[host.key] = "done"
            return "done", msg
        if r1 is not None:
            # refused: LightCraft lets only the user choose the programs Edit In starts while it runs
            # (storytold/lightcraft#2638; an update that keeps the same editor is no change, and passes). Its
            # ui.json, read when it starts, still takes them while it is closed
            out.write("  " + _("{app} does not let another program change its external editor while it is open",
                               app=host.name))
    if not wait_closed(host, yes):
        cfg[host.key] = "pending"
        return "pending", _("{app} is open: close it, then run the configuration again "
                            "(install --configure-lightcraft, or the MCP tool configure_lightcraft)", app=host.name)
    edit_ui_json(editor, host=host)
    cfg[host.key] = "done"
    return "done", _("settings written to {file}", file=ui_json(host))


def configure_apps(d, cfg, editor, apps, yes=False):
    """Step 6 for the apps chosen (choose_apps): [(host, state, message)]; the others are left as they are."""
    cfg["apps"] = [h.key for h in apps]
    results = []
    for host in system.HOSTS:
        if host not in apps:
            out.write(f"  {host.name}: " + _("not chosen, left as it is"))
        elif not configurable(host):
            out.write(f"  {host.name}: " + _("not installed yet, nothing set up: once it is (and has been opened "
                                              "once), run the configuration again (install --configure-lightcraft)"))
        else:
            out.write(f"  {host.name}:")
            state, msg = configure_lightcraft(d, cfg, editor, yes, host)
            out.write("  " + msg)
            results.append((host, state, msg))
    return results


# ------------------------------------------------------------------------------------------------ status / uninstall
def read_cfg(d):
    try:
        return json.loads((d / "airemove.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def write_cfg(d, cfg):
    (d / "airemove.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")


def status(d):
    """JSON: what is installed. The lightcraft_* keys are LightCraft's, as before Chromaforge; "apps" has both."""
    cfg = read_cfg(d)
    rep = {"installed": venv_python(d).exists(), "dir": str(d), "config": cfg, "os": system.system(), "apps": {}}
    for h in system.HOSTS:
        a = rep["apps"][h.key] = {"name": h.name, "app": h.app(), "running": lc_running(h),
                                  "reachable": h.reachable(int(cfg.get(h.cfg_key("port")) or h.default_port)),
                                  "settings": str(h.config_dir()), "configured": cfg.get(h.key)}
        try:
            st = json.loads(ui_json(h).read_text(encoding="utf-8-sig")).get("settings", {})
            a["editor"], a["shortcut"] = st.get("externalEditor"), (st.get("keymap") or {}).get(EDIT_COMMAND)
        except (OSError, ValueError):
            pass
    lc = rep["apps"]["lightcraft"]
    rep.update(lightcraft_app=lc["app"], lightcraft_running=lc["running"], lightcraft_reachable=lc["reachable"],
               lightcraft_settings=lc["settings"])
    if "editor" in lc:
        rep["lightcraft_editor"], rep["lightcraft_shortcut"] = lc["editor"], lc["shortcut"]
    if rep["installed"]:
        __, txt = run([venv_python(d), str(d / "airemove" / "airemove.py"), "--check"], check=False, quiet=True)
        try:
            rep["check"] = json.loads(txt[txt.index("{"):])
        except ValueError:
            rep["check_output"] = txt[-1000:]
    print(json.dumps(rep, indent=1, ensure_ascii=False))


def unhook(d, cfg, host=system.LIGHTCRAFT, yes=False):
    """The app's external editor and shortcut, when they are this install's: cleared live, else in its ui.json once
    the app is closed (LightCraft refuses the editor live: see configure_lightcraft)."""
    port = int(cfg.get(host.cfg_key("port")) or host.default_port)
    ours = lambda v: is_ours(v, d, cfg)  # noqa: E731
    live = lc_request(port, "ui.set", {}, host=host)  # no change: replies with the app's current settings
    if live and live.get("ok"):
        st = (live.get("result") or {}).get("settings") or {}
        if not ours(st.get("externalEditor")):
            out.write("  " + _("{app}: its external editor is not this installation, left as it is", app=host.name))
            return
        if (st.get("keymap") or {}).get(EDIT_COMMAND) == SHORTCUT:  # ours in any case: it would start what is gone
            lc_request(port, "engine.execute", {"command": "app.setShortcut",
                                                "params": {"id": EDIT_COMMAND, "shortcut": ""}}, host=host)
        r = lc_request(port, "ui.set", {"settings": {"externalEditor": ""}}, host=host)
        if r and r.get("ok"):
            out.write("  " + _("{app}: external editor removed", app=host.name))
            return
        out.write("  " + _("{app} does not let another program change its external editor while it is open",
                           app=host.name))
    if not wait_closed(host, yes):
        out.write("  ! " + _("{app} is open: remove the external editor yourself in Settings > External Editing",
                             app=host.name))
        return
    try:
        done = edit_ui_json("", remove=ours, host=host)
        out.write("  " + (_("{app}: external editor and shortcut removed", app=host.name) if done else
                          _("{app}: its external editor is not this installation, left as it is", app=host.name)))
    except (OSError, ValueError) as e:
        out.write("  ! " + _("ui.json not changed: {error}", error=e))


def uninstall(d, keep_models, yes):
    cfg = read_cfg(d)
    s = system.system()
    if not ask((_("Uninstall AI Remove from {dir}, keeping the models?", dir=d) if keep_models else
                _("Uninstall AI Remove from {dir}?", dir=d)) + " " +
               _("The photos, the DNGs made and the .airemove projects next to the RAWs stay."), True, yes):
        return
    for host in system.HOSTS:  # LightCraft as before; Chromaforge where this install set it up
        if host is system.LIGHTCRAFT or cfg.get(host.key):
            unhook(d, cfg, host, yes)
        if cfg.get(host.cfg_key("control_env")):
            unset_control_port(d, cfg, host)
    sc = cfg.get("shortcut")
    if sc and s == "macos" and Path(sc).exists():
        output([LSREGISTER, "-u", sc])  # its .airemove type goes with it
    if sc and Path(sc).exists():
        (shutil.rmtree if Path(sc).is_dir() else os.remove)(sc)
    if s == "windows":
        output(["reg", "delete", WIN_UNINSTALL_KEY, "/f"])
        win_project_type(None)
    elif s == "linux":
        data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        for pattern in ("*/apps/airemove.*", "*/mimetypes/airemove-project.*"):
            for f in (data / "icons" / "hicolor").glob(pattern):
                f.unlink(missing_ok=True)
        linux_project_type(data, remove=True)
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
    mine = sorted(set((cfg.get("model_paths") or {}).values()))
    if mine:
        out.write(_("Your own model folders are left as they are: {dirs}", dirs=", ".join(mine)))


# ------------------------------------------------------------------------------------------------ main
def parse():
    ap = argparse.ArgumentParser(description="Install AI Remove for LightCraft and Chromaforge")
    ap.add_argument("--dir", help="install folder (default: ~/AIRemove)")
    ap.add_argument("--models", default=None, help=",".join(MODELS) + " | recommended | none")
    ap.add_argument("--hf-token", default=None, help="Hugging Face token (only for SAM 3 / FLUX, models with a licence to accept)")
    ap.add_argument("--hf-token-file", default=None, help="file holding the token (read, then deleted: the MCP server uses it)")
    ap.add_argument("--torch", default="auto", choices=["auto"] + list(TORCH_FLAVOURS))
    ap.add_argument("--models-from", default=None, help="another install's models/ folder to reuse (linked)")
    ap.add_argument("--model-dir", action="append", metavar="MODEL=FOLDER",
                    help="a model you already have on disk (another install, a Hugging Face cache, ComfyUI's models): "
                         "used from there, not downloaded; once per model")
    ap.add_argument("--apps", default=None, help="the apps to set up: lightcraft, chromaforge, both or none (default: "
                                                 "asked; with --yes the ones chosen last time, else the installed)")
    ap.add_argument("--port", type=int, default=None, help="port of LightCraft's control channel (7980)")
    ap.add_argument("--no-lightcraft", action="store_true", help="leave the apps' settings alone (--apps none)")
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
    apps = [] if args.no_lightcraft else parse_apps(args.apps) if args.apps else None  # None: asked
    if args.configure_lightcraft:
        out.title(6, " · ".join(h.name for h in system.HOSTS))
        results = configure_apps(d, cfg, cfg.get("editor") or str(launcher_exe(d)),
                                 choose_apps(cfg, args.yes) if apps is None else apps, args.yes)
        write_cfg(d, cfg)
        pending = any(state != "done" for __, state, __ in results)
        msg = " · ".join(f"{h.name}: {m}" for h, __, m in results) or _("no app set up")
        out.status("pending" if pending else "done", msg)
        return 2 if pending else 0

    out.write(_("AI Remove for LightCraft and Chromaforge {version} — installation ({os})", version=VERSION,
                os=f"{platform.system()} {platform.machine()}"))
    out.title(1, _("The computer"))
    gpus = detect_gpus()
    for g in gpus:
        out.write("  " + _("graphics: {name}", name=g[1]) + (f" ({num(g[2])} GB)" if g[2] else ""))
    flavour, gpu = choose_torch(gpus) if args.torch == "auto" else (args.torch, gpus[0] if gpus else None)
    out.write(f"  PyTorch: {_(TORCH_FLAVOURS[flavour][0])}")
    if flavour == "cpu":
        out.write("  ! " + _("no usable GPU: LaMa and the selection will work; SDXL would be very slow"))
    for h in system.HOSTS:
        out.write(f"  {h.name}: " + (h.app() or _("not found")))
    if not system.installed_hosts():
        out.write("  " + _("AI Remove works inside LightCraft (getartcraft.com) or Chromaforge "
                           "(github.com/emmertex/lightcraft-classic): install one of them"))
    if apps is None:
        apps = choose_apps(cfg, args.yes)
    sam_host = system.sam3_host(mf.SAM3_WEIGHTS)  # an app that has SAM 3 already: linked, not downloaded

    # models: what this install has already — in its models/ or, from an earlier run, in the user's own folders (a
    # re-run keeps it and does not ask about it again) —, the folders given with --model-dir, then the questions
    models_dir = d / "models"
    kept = {p: f for p, f in (cfg.get("model_paths") or {}).items() if p in mf.PARTS and mf.part_ok(p, f)}
    installed = [m for m in MODELS if mf.has(m, models_dir, kept, optional=True)]
    other = Path(args.models_from).expanduser() if args.models_from else None
    asked = args.models is None and not args.yes
    given = {}  # model: {part: folder} — what the user already has in a folder of their own
    for spec in args.model_dir or []:
        m, __, folder = spec.partition("=")
        if m.strip().lower() not in MODELS or not folder.strip():
            raise Stop(_("--model-dir wants MODEL=FOLDER, MODEL one of {models} (it was: {value})",
                         models=", ".join(MODELS), value=spec))
        found, why = look(m.strip().lower(), folder)
        if not found:
            raise Stop(why)
        given[m.strip().lower()] = found
        if not asked:  # the questions show it with the model
            say_found(m.strip().lower(), found)
    if args.models in (None, "recommended"):
        wanted = choose_models(flavour, gpu, installed, given, sam_host) if asked else recommended_models(flavour, gpu)
    elif args.models == "none":
        wanted = []
    else:
        wanted = [m.strip() for m in args.models.split(",") if m.strip() in MODELS]
    wanted += list(given)  # a folder given for a model: that model is wanted
    if args.models != "none":  # LaMa always; what is installed stays (listed below as already there)
        wanted += installed + ["lama"]
    wanted = [m for m in MODELS if m in wanted]

    def mine():
        """{part: folder} used from the user's own folders: from an earlier run, and given now for a wanted model."""
        return dict(kept, **{p: f for m in wanted for p, f in given.get(m, {}).items()})

    def source(part):
        """Where a part comes from: 'there' (models/), 'yours' (a folder of the user's), 'app' (SAM 3, from
        LightCraft or Chromaforge), 'other' (--models-from, linked) or 'get' (downloaded)."""
        paths = mine()
        if mf.part_ok(part, mf.part_dir(part, models_dir, paths)):
            return "yours" if part in paths else "there"
        if part == "sam3" and sam_host:
            return "app"
        return "other" if other and mf.part_ok(part, other / part) else "get"

    def drop(model, why):
        out.write("  " + why)
        wanted.remove(model)

    if "osor" in wanted and "flux" not in wanted:
        drop("osor", _("OSOR runs on FLUX: add flux to the models (it is skipped now)"))
    token = args.hf_token or os.environ.get("HF_TOKEN")
    if args.hf_token_file:
        try:
            token = Path(args.hf_token_file).read_text(encoding="utf-8").strip() or token
            Path(args.hf_token_file).unlink()
        except OSError:
            pass
    gated = [p for m in wanted for p in MODELS[m].parts if mf.PARTS[p].gated and source(p) == "get"]
    if gated and not token and not args.yes:
        repos = ", ".join(mf.PARTS[p].repo for p in gated)
        out.write("\n  " + _("{models}: a licence to accept on Hugging Face:", models=repos)
                  + "\n  " + _("1) make an account on huggingface.co  2) open {pages} and accept the licence  "
                               "3) make a token (Read) at https://huggingface.co/settings/tokens",
                               pages=", ".join(f"https://huggingface.co/{mf.PARTS[p].repo}" for p in gated)))
        try:
            token = getpass.getpass("  " + _("Paste the token (hidden; Enter to skip these models): ")).strip()
        except (EOFError, KeyboardInterrupt):
            token = ""
    if gated and not token:
        for m in [m for m in wanted if set(MODELS[m].parts) & set(gated)]:
            drop(m, _("skipping {model}: it needs the Hugging Face token", model=m)
                 + (" " + _("(selection will be with the brush)") if m == "sam3" else ""))
        if "osor" in wanted and "flux" not in wanted + installed:
            drop("osor", _("OSOR runs on FLUX: add flux to the models (it is skipped now)"))
    paths = mine()
    need = list(dict.fromkeys(p for m in wanted for p in MODELS[m].parts if source(p) == "get"))
    total = TORCH_FLAVOURS[flavour][1] + sum(mf.PARTS[p].gb for p in need)
    out.write("\n  " + _("folder: {dir}  ·  free space {free} GB  ·  needed ~{need} GB", dir=d,
                           free=f"{gb_free(d):.0f}", need=f"{total:.0f}"))
    for m in [m for m in wanted if MODELS[m].offered]:
        mod = MODELS[m]
        src = {p: source(p) for p in mod.parts}
        get = sum(mf.PARTS[p].gb for p, s in src.items() if s == "get")
        state = (_("used from your folder, {gb} GB to download", gb=num(get)) if "yours" in src.values() and get else
                 _("used from your folder (0 GB)") if "yours" in src.values() else
                 _("already in {app}: linked (0 GB)", app=sam_host.name) if "app" in src.values() else
                 _("linked from {dir} (0 GB)", dir=other) if "other" in src.values() and not get else
                 _("already there (0 GB)") if not get else f"{num(get)} GB")
        # the questions said what each model is for; without them, the summary says it
        para(f"· {mod.name}" + ("" if asked else f" — {_(mod.what)}") + f" — {state} — "
             + _("licence {licence}", licence=mod.licence), "   ", "       ")
        for p in [p for p, s in src.items() if s == "yours"]:
            out.write(f"       {p}: {paths[p]}")
    if gb_free(d) < total + 2:
        raise Stop(_("not enough space: free at least {gb} GB or pick another folder (--dir)",
                     gb=f"{total + 2 - gb_free(d):.0f}"))
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
    # the parts in the user's own folders: recorded first, so the app finds them even if a download fails later
    cfg["model_paths"] = {p: str(f) for p, f in paths.items()}
    write_cfg(d, cfg)
    done, failed = get_models(d, wanted, token, args.models_from, paths) if wanted else ([], [])
    cfg["models"] = sorted(set(cfg.get("models", [])) | set(done))
    cfg["model_paths"] = {p: f for p, f in cfg["model_paths"].items() if mf.part_ok(p, f)}
    for m, why in failed:
        out.write("  ! " + _("{model} not installed: {why}", model=m, why=why))
    retire_models(models_dir)
    cfg["models"] = [m for m in cfg["models"] if m not in RETIRED]
    write_cfg(d, cfg)

    out.title(5, _("Program, icon and menu"))
    editor = make_shortcuts(d, cfg)
    write_cfg(d, cfg)

    out.title(6, " · ".join(h.name for h in system.HOSTS))
    if args.no_lightcraft:
        out.write("  " + _("skipped (--no-lightcraft)"))
    results = configure_apps(d, cfg, editor, apps, args.yes)
    write_cfg(d, cfg)
    names = " / ".join(h.name for h, __, __ in results)
    pending = " / ".join(h.name for h, state, __ in results if state == "pending")
    first_run = " / ".join(h.name for h, state, __ in results if state == "first_run")

    out.title(7, _("Check"))
    __, txt = run([venv_python(d), str(d / "airemove" / "airemove.py"), "--check"], check=False, quiet=True)
    try:
        rep = json.loads(txt[txt.index("{"):])
        conn = [f"{h.name} " + (_("connected") if (rep.get("apps") or {}).get(h.key, {}).get("connected") else
                                _("not reachable now")) for h, __, __ in results]
        out.write("  " + _("device: {gpu} · usable models: {models}", gpu=rep.get("gpu"),
                             models=", ".join(rep.get("usable_models", []))) + "".join(f" · {c}" for c in conn))
    except ValueError:
        out.write(txt[-800:])
    final = (_("Done. Restart {apps}, then select a photo and press {key} (Photo > Edit In > Open Original in Other "
               "Editor). Or open \"AI Remove\" from the menu.", apps=names, key=APP_KEY) if results else
             _("Done. Open \"AI Remove\" from the menu: it works on a photo on its own (no app was set up)."))
    if pending:
        final += " " + _("FIRST: close {apps} and finish the configuration (see above).", apps=pending)
    if first_run:
        final += " " + _("FIRST: open {apps} once, close it and finish the configuration (see above).", apps=first_run)
    if failed:
        final += " " + _("Some models were not installed (see above).")
    out.write("\n" + final)
    out.status("done" if not (pending or first_run) else "pending_lightcraft", final, models=cfg.get("models"),
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
