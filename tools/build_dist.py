"""Build the packages to share, in dist/:

  AIRemove-<version>-windows.zip    AIRemove-<version>-macos.zip    AIRemove-<version>-linux.tar.gz
  AIRemove-<version>-all-platforms.zip   (all three installers)

Each holds one folder AIRemove-<version>/ with the app, the installer, the MCP server, the icon and the docs. Shell
scripts keep their executable bit (in the zip too: the Mac's Archive Utility honours it) and LF line endings;
Windows scripts get CRLF. Run with any Python 3.8+: python tools/build_dist.py
"""
import io
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "airemove"))
import system  # noqa: E402

VERSION = system.VERSION
NAME = f"AIRemove-{VERSION}"
SKIP_DIRS = {"__pycache__", "dist", ".git", ".github", "venv", "models", "work", "python", "bin", "launcher", ".idea", ".vscode"}
LAUNCHERS = {"windows": "Install on Windows.cmd", "macos": "Install on Mac.command", "linux": "Install on Linux.sh"}
EXEC = (".sh", ".command")


def files(for_os):
    other = {v for k, v in LAUNCHERS.items() if for_os not in ("all", k)}
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir() or set(rel.parts) & SKIP_DIRS or rel.name in other or p.suffix in (".pyc", ".log"):
            continue
        if rel.name in ("airemove.json", "install-status.json", "desktop.ini") or rel.name.startswith("."):
            continue
        if (p.suffix == ".vectorcraft" or (rel.parts[:3] == ("assets", "icon", "source") and p.suffix == ".png")
                or (rel.parent == Path("assets", "icon") and p.name.startswith("airemove-project") and p.suffix == ".svg")):
            continue  # the icons' working files stay here: the packages carry their scripts and outputs
        yield p, rel


def content(p):
    data = p.read_bytes()
    if p.suffix in (".cmd", ".ps1"):
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    elif p.suffix in EXEC + (".py", ".md", ".txt", ".json", ".svg", ".toml"):
        data = data.replace(b"\r\n", b"\n")
    return data


def build_zip(for_os, out):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, rel in files(for_os):
            info = zipfile.ZipInfo(f"{NAME}/{rel.as_posix()}", date_time=time.localtime()[:6])
            info.create_system = 3  # Unix: the mode below is honoured by macOS and Linux unzip tools
            info.external_attr = ((0o100755 if p.suffix in EXEC else 0o100644) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content(p))


def build_tar(for_os, out):
    with tarfile.open(out, "w:gz") as t:
        for p, rel in files(for_os):
            data = content(p)
            info = tarfile.TarInfo(f"{NAME}/{rel.as_posix()}")
            info.size, info.mtime = len(data), int(time.time())
            info.mode = 0o755 if p.suffix in EXEC else 0o644
            t.addfile(info, io.BytesIO(data))


def main():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    outs = [(build_zip, "windows", dist / f"{NAME}-windows.zip"), (build_zip, "macos", dist / f"{NAME}-macos.zip"),
            (build_tar, "linux", dist / f"{NAME}-linux.tar.gz"),
            (build_zip, "all", dist / f"{NAME}-all-platforms.zip")]
    for fn, os_name, out in outs:
        fn(os_name, out)
        print(f"{out.name:40s} {out.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    main()
