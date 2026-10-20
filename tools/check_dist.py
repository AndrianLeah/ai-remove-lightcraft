"""Check the packages tools/build_dist.py made before they are shared (the release workflow runs this; it works by
hand too):

  python tools/check_dist.py [--tag vX.Y.Z] [DIST]      DIST: default dist/

The four packages AIRemove-<version>-windows.zip, -macos.zip, -linux.tar.gz and -all-platforms.zip must be there,
<version> being airemove/system.py's VERSION — and the tag's, when given (vX.Y.Z, or vX.Y.Z-suffix for a
pre-release). In each package:
  - one top folder AIRemove-<version>/, and the VERSION inside it is <version>;
  - the install launcher for its system and no other (all three in all-platforms);
  - the executable bit on .sh and .command files; LF line endings in shell and Python files, CRLF in .cmd / .ps1;
  - nothing that must not be shared: no .github or other dot files, no __pycache__ / .pyc, nothing an install leaves
    (venv, models, work, airemove.json, logs...), no ObjectClear code or licence (S-Lab, non-commercial: the
    installer downloads it, AI Remove never ships it);
  - the files the installer and the app need.
The three per-system packages hold the same files as all-platforms, launchers apart. Standard library only.
Exit status 1 when anything is wrong (every problem is listed).
"""
import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHERS = {"windows": "Install on Windows.cmd", "macos": "Install on Mac.command", "linux": "Install on Linux.sh"}
PACKAGES = {"windows": "windows.zip", "macos": "macos.zip", "linux": "linux.tar.gz", "all": "all-platforms.zip"}
NEEDED = ["airemove/airemove.py", "airemove/ui.py", "airemove/engines.py", "airemove/blend.py", "airemove/rawdng.py",
          "airemove/project.py", "airemove/system.py", "airemove/i18n.py", "airemove/locales/it.json",
          "installer/install.py", "installer/fetch_models.py", "installer/bootstrap.ps1", "installer/bootstrap.sh",
          "mcp/airemove_mcp.py", "mcp/run_mcp.cmd", "mcp/run_mcp.sh", "README.md", "LICENSE.txt",
          "THIRD-PARTY-NOTICES.md"]
INSTALL_LEFTOVERS = {"venv", "models", "work", "python", "bin", "launcher", "dist", "__pycache__"}
LEFTOVER_FILES = {"airemove.json", "install.log", "install-status.json", "run-installer.cmd", "desktop.ini",
                  "Thumbs.db"}
EXEC = (".sh", ".command")
LF_ONLY = EXEC + (".py",)
CRLF = (".cmd", ".ps1")
# ObjectClear's code (github.com/zjx0101/ObjectClear) and its licence: what fetch_models.py puts in models/objectclear
OBJECTCLEAR = [re.compile(rb"class\s+ObjectClearPipeline\b"), re.compile(rb"class\s+PostfuseModule\b"),
               re.compile(rb"def\s+attention_guided_fusion\("), re.compile(rb"Copyright\s+\d{4}\s+S-Lab"),
               re.compile(rb"Redistribution\s+and\s+use\s+for\s+non-commercial\s+purpose")]  # \s+: no self-match


def version_in(text):
    m = re.search(r'^VERSION = "([^"]+)"', text, re.M)
    return m.group(1) if m else None


def entries(path):
    """{name: (mode, data)} of the package's files, and the names of anything that is neither file nor folder."""
    files, odd = {}, []
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if i.is_dir():
                    continue
                mode = (i.external_attr >> 16) & 0o7777 if i.create_system == 3 else None
                files[i.filename] = (mode, z.read(i))
    else:
        with tarfile.open(path) as t:
            for m in t.getmembers():
                if m.isfile():
                    files[m.name] = (m.mode & 0o7777, t.extractfile(m).read())
                elif not m.isdir():
                    odd.append(m.name)
    return files, odd


def check_package(path, os_name, version):
    """Problems of one package, and its files (paths inside the top folder) for comparing."""
    bad = []
    files, odd = entries(path)
    bad += [f"{n}: a link or special file" for n in odd]
    top = f"AIRemove-{version}/"
    rel = {}
    for name, (mode, data) in files.items():
        if not name.startswith(top):
            bad.append(f"{name}: outside the folder {top}")
            continue
        r = name[len(top):]
        rel[r] = (mode, data)
        parts = r.split("/")
        if any(p.startswith(".") for p in parts):
            bad.append(f"{r}: a dot file or folder (.github, .git...) must not be shared")
        if set(parts[:-1]) & INSTALL_LEFTOVERS or parts[-1] in LEFTOVER_FILES or r.endswith((".pyc", ".log")):
            bad.append(f"{r}: left by an install or a build, must not be shared")
        if any(p.lower() == "objectclear" for p in parts[:-1]) or parts[-1] == "pipeline_objectclear.py" or \
                any(sig.search(data) for sig in OBJECTCLEAR):
            bad.append(f"{r}: ObjectClear's code or licence (S-Lab, non-commercial) must never be shipped")
        if r.endswith(EXEC) and (mode is None or mode & 0o111 != 0o111):
            bad.append(f"{r}: not executable (mode {oct(mode) if mode is not None else 'none: not a Unix zip entry'})")
        if r.endswith(LF_ONLY) and b"\r\n" in data:
            bad.append(f"{r}: CRLF line endings (macOS / Linux need LF)")
        if r.endswith(CRLF) and data.count(b"\n") != data.count(b"\r\n"):
            bad.append(f"{r}: LF line endings (Windows scripts need CRLF)")
    inside = version_in(rel.get("airemove/system.py", (None, b""))[1].decode("utf-8", "replace"))
    if inside != version:
        bad.append(f"airemove/system.py says VERSION {inside}, the package is {version}")
    want = set(LAUNCHERS.values()) if os_name == "all" else {LAUNCHERS[os_name]}
    have = {r for r in rel if r in LAUNCHERS.values()}
    if have != want:
        bad.append(f"launchers {sorted(have)}, expected {sorted(want)}")
    bad += [f"{n}: missing" for n in NEEDED if n not in rel]
    return bad, {r: d for r, (__, d) in rel.items() if r not in LAUNCHERS.values()}


def main():
    ap = argparse.ArgumentParser(description="Check the packages tools/build_dist.py made")
    ap.add_argument("dist", nargs="?", default=str(ROOT / "dist"))
    ap.add_argument("--tag", help="the release tag (vX.Y.Z or vX.Y.Z-suffix): its version must be the packages'")
    a = ap.parse_args()
    dist = Path(a.dist)
    version = version_in((ROOT / "airemove" / "system.py").read_text(encoding="utf-8"))
    problems = []
    if a.tag:
        m = re.fullmatch(r"v(\d+\.\d+\.\d+)(-[0-9A-Za-z.-]+)?", a.tag)
        if not m:
            problems.append(f"tag {a.tag}: not vX.Y.Z or vX.Y.Z-suffix")
        elif m.group(1) != version:
            problems.append(f"tag {a.tag} is version {m.group(1)}, airemove/system.py says {version}")
    print(f"AI Remove {version} packages in {dist}" + (f", tag {a.tag}" if a.tag else ""))
    contents = {}
    for os_name, suffix in PACKAGES.items():
        p = dist / f"AIRemove-{version}-{suffix}"
        if not p.exists():
            problems.append(f"{p.name}: missing")
            continue
        bad, contents[os_name] = check_package(p, os_name, version)
        problems += [f"{p.name}: {b}" for b in bad]
        print(f"  {'ok  ' if not bad else 'FAIL'} {p.name:40s} {p.stat().st_size / 1024:8.0f} KB, "
              f"{len(contents[os_name]) + (3 if os_name == 'all' else 1)} files")
    others = sorted(p.name for p in dist.glob("AIRemove-*") if not any(p.name.endswith(s) for s in PACKAGES.values())
                    or not p.name.startswith(f"AIRemove-{version}-"))
    problems += [f"{n}: not one of this version's four packages" for n in others]
    if "all" in contents:
        for os_name in ("windows", "macos", "linux"):
            if os_name in contents and contents[os_name] != contents["all"]:
                diff = sorted(set(contents[os_name]) ^ set(contents["all"])) or \
                    sorted(n for n in contents["all"] if contents[os_name].get(n) != contents["all"][n])
                problems.append(f"{os_name} and all-platforms differ (launchers apart): {diff[:5]}")
    for pr in problems:
        print("  FAIL " + pr)
    print("all checks passed" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
