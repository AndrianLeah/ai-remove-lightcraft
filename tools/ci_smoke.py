"""Smoke test of a real install, for the CI runners (.github/workflows/ci.yml). DIR is an install folder made by
installer/bootstrap.(ps1|sh) --models lama --no-lightcraft: LightCraft is not on the runners.

  ci_smoke.py check DIR        airemove-cli --check prints JSON: PyTorch of the build asked for, LaMa installed and
                               usable, LightCraft not connected; uv in DIR/bin, the menu entry / app made, the
                               .airemove file type registered to open with it, with the project icon
  ci_smoke.py folder DIR       a model the user already has in a folder of their own (--model-dir): DIR's LaMa moved
                               into a folder laid out like a Hugging Face cache, next to DIR; the installer run again
                               with --model-dir lama=<an empty folder> must stop, changing nothing, and with
                               --model-dir lama=<that cache> must record it (airemove.json "model_paths") and download
                               nothing; --check finds LaMa there. The steps after this one use LaMa from there
  ci_smoke.py mcp DIR          the MCP server over stdio through its launcher (mcp/run_mcp.cmd|sh), AIREMOVE_HOME=DIR:
                               initialize, tools/list, check_system (which must see whether DIR is installed),
                               check_system with model_dirs; the install tool's --model-dir arguments
  ci_smoke.py remove DIR       one removal end to end with the install's Python and code, LightCraft left out:
                               tools/ci_removal.py (a synthetic raw DNG, LaMa, the blend, the DNG and the project),
                               then a long one in tiles: tools/ci_tiles.py (a cord across a synthetic area, LaMa),
                               then one on each kind of picture: tools/ci_pictures.py (JPEG, PNG, TIFF, WebP, HEIC,
                               AVIF opened on their own, LaMa, the copy in the same format, its metadata), and
                               Describe's masks from synthetic SAM 3 output: tools/ci_describe.py
  ci_smoke.py uninstall DIR    the uninstaller the install made (Settings > Apps / the install folder) with --yes: the
                               app, its menu entry, its .airemove file type and, on Windows, its Settings > Apps entry
                               are gone; the user's own model folders are still there
Exit status 1 at the first check that fails. Standard library only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "airemove"))
import system  # noqa: E402

OS = system.system()
WIN = OS == "windows"
PROTOCOL = "2025-06-18"
TOOLS = ["ai_remove_guide", "check_system", "install", "install_status", "configure_lightcraft", "open_ai_remove",
         "remove_with_masks", "project_info", "uninstall"]
WIN_UNINSTALL_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIRemoveLightCraft"


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok   " + what, flush=True)


def run(cmd, show=True, **kw):
    """Run cmd; its output goes to the CI log (stdout only when show: the MCP protocol stream is too long)."""
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=900, **kw)
    for name, text in (("stdout", r.stdout if show else ""), ("stderr", r.stderr)):
        if text.strip():
            print(f"  --- {name}\n" + text.rstrip()[-6000:] + f"\n  --- end of {name}", flush=True)
    return r


def report(text):
    """The JSON object a program prints (after whatever it printed before it)."""
    try:
        return json.loads(text[text.index("{"):])
    except ValueError:
        raise Failed("no JSON report in the output")


def config(d):
    try:
        return json.loads((d / "airemove.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise Failed(f"no readable {d / 'airemove.json'}")


def project_type(shortcut):
    """What a double-clicked .airemove (a photo's project) opens, as registered for this user, "" when nothing:
    Windows the command, macOS the extensions the app declares, Linux the type's definition and the menu entry's
    MimeType=."""
    if WIN:
        cls = "HKCU\\Software\\Classes\\"
        ext = subprocess.run(["reg", "query", cls + ".airemove", "/ve"], capture_output=True, text=True)
        cmd = subprocess.run(["reg", "query", cls + "AIRemove.Project\\shell\\open\\command", "/ve"],
                             capture_output=True, text=True)
        return cmd.stdout.strip() if "AIRemove.Project" in ext.stdout and cmd.returncode == 0 else ""
    if OS == "macos":
        import plistlib
        plist = Path(shortcut) / "Contents" / "Info.plist"
        info = plistlib.loads(plist.read_bytes()) if plist.exists() else {}
        return " ".join(e for t in info.get("UTExportedTypeDeclarations", [])
                        for e in t.get("UTTypeTagSpecification", {}).get("public.filename-extension", []))
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    xml, entry = data / "mime" / "packages" / "airemove.xml", Path(shortcut)
    lines = entry.read_text(encoding="utf-8").splitlines() if entry.is_file() else []
    return " ".join(([str(xml)] if xml.exists() else []) + [x for x in lines if x.startswith("MimeType=")])


def project_icon(shortcut):
    """The icon file .airemove files show, as registered ("" when none): Windows the type's DefaultIcon, macOS the
    document type's .icns in the app, Linux the 48 px one of the icon the type's definition names."""
    if WIN:
        r = subprocess.run(["reg", "query", "HKCU\\Software\\Classes\\AIRemove.Project\\DefaultIcon", "/ve"],
                           capture_output=True, text=True)
        return r.stdout.split("REG_SZ", 1)[1].strip() if r.returncode == 0 and "REG_SZ" in r.stdout else ""
    if OS == "macos":
        import plistlib
        plist = Path(shortcut) / "Contents" / "Info.plist"
        info = plistlib.loads(plist.read_bytes()) if plist.exists() else {}
        name = next((t.get("CFBundleTypeIconFile") for t in info.get("CFBundleDocumentTypes", [])
                     if "com.airemove.project" in t.get("LSItemContentTypes", [])), None)
        return str(Path(shortcut) / "Contents" / "Resources" / f"{name}.icns") if name else ""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    xml = data / "mime" / "packages" / "airemove.xml"
    m = re.search(r'<icon name="([^"]+)"', xml.read_text(encoding="utf-8")) if xml.exists() else None
    return str(data / "icons" / "hicolor" / "48x48" / "mimetypes" / f"{m.group(1)}.png") if m else ""


def app_check(d):
    cli = d / "venv" / ("Scripts/airemove-cli.exe" if WIN else "bin/airemove-cli")
    expect(cli.exists(), f"{cli} exists")
    r = run([cli, "--check"])
    expect(r.returncode == 0, f"--check exit status 0 (it was {r.returncode})")
    return report(r.stdout)


def check(d):
    cfg = config(d)
    rep = app_check(d)
    expect(rep.get("version") == system.VERSION and rep.get("os") == OS, f"version {system.VERSION} on {OS}")
    expect("torch" in rep, f"PyTorch imports: {rep.get('torch') or rep.get('torch_error')}")
    if cfg.get("torch") == "cpu":  # PyTorch's own index, not PyPI's build (CUDA on Linux)
        expect(rep["torch"].endswith("+cpu"), f"PyTorch is the processor build ({rep['torch']})")
    print(f"  info device {rep.get('device')}: {rep.get('gpu')}")
    expect((rep.get("models") or {}).get("lama") is True, "models.lama true")
    expect(rep.get("heic") is True, "HEIC pictures: pillow-heif installed")
    expect("lama" in (rep.get("usable_models") or []), "LaMa usable")
    expect((rep.get("lightcraft") or {}).get("connected") is False,
           f"lightcraft.connected false (no LightCraft here: {(rep.get('lightcraft') or {}).get('error')})")
    uv = "uv.exe" if WIN else "uv"
    expect((d / "bin" / uv).exists() or (d / "bin" / "bin" / uv).exists(), "uv fetched into <install>/bin")
    expect(cfg.get("shortcut") and Path(cfg["shortcut"]).exists(), f"menu entry / app: {cfg.get('shortcut')}")
    pt = project_type(cfg["shortcut"])
    want = {"windows": [str(d / "venv" / "Scripts" / "airemove.exe").lower(), "%1"], "macos": ["airemove"],
            "linux": ["airemove.xml", "mimetype=application/x-airemove-project"]}[OS]
    expect(all(w in pt.lower() for w in want), f".airemove projects open AI Remove: {pt}")
    ic = project_icon(cfg["shortcut"])
    expect(ic and Path(ic).is_file() and "project" in Path(ic).name, f".airemove files show the project icon: {ic}")


def installer(d, args):
    """The installer run again on DIR the way a user starts it (bootstrap), without questions."""
    cmd = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ROOT / "installer" / "bootstrap.ps1"]
           if WIN else ["sh", ROOT / "installer" / "bootstrap.sh"])
    return run(cmd + ["--yes", "--dir", d, "--no-lightcraft", "--torch", config(d).get("torch") or "cpu"] + args)


def folder(d):
    lama = d / "models" / "lama" / "lama_fp32.onnx"
    expect(lama.is_file(), f"LaMa installed in {lama.parent}")
    cache = d.parent / "ci-hf-cache"  # what a user has: ~/.cache/huggingface, with LaMa in it
    snap = cache / "hub" / "models--Carve--LaMa-ONNX" / "snapshots" / "0123456789abcdef"
    snap.mkdir(parents=True, exist_ok=True)
    shutil.move(str(lama), str(snap / lama.name))
    shutil.rmtree(lama.parent)
    empty = d.parent / "ci-empty-folder"
    empty.mkdir(exist_ok=True)
    before = (d / "airemove.json").read_bytes()

    r = installer(d, ["--models", "lama", "--model-dir", f"lama={empty}"])
    expect(r.returncode != 0, f"--model-dir lama=<an empty folder>: the installer stops (exit status {r.returncode})")
    expect("nothing of it" in r.stdout and "lama/lama_fp32.onnx" in r.stdout,
           "and says what it looked for (lama/lama_fp32.onnx)")
    expect((d / "airemove.json").read_bytes() == before and not (d / "models" / "lama").exists(),
           "nothing changed: airemove.json as it was, no LaMa downloaded")

    r = installer(d, ["--models", "lama", "--model-dir", f"lama={cache}"])
    expect(r.returncode == 0, f"--model-dir lama=<a Hugging Face cache>: exit status 0 (it was {r.returncode})")
    expect(f"found: lama in {snap}" in r.stdout, f"the installer found LaMa in {snap}")
    expect("MODEL_OK lama" in r.stdout and "downloading" not in r.stdout, "LaMa ok, nothing downloaded")
    expect(not (d / "models" / "lama").exists(), "no LaMa in the install's own models folder")
    paths = config(d).get("model_paths") or {}
    expect(Path(paths.get("lama", "")) == snap, f"airemove.json model_paths: {paths}")
    rep = app_check(d)
    expect((rep.get("models") or {}).get("lama") is True and "lama" in (rep.get("usable_models") or []),
           "--check: LaMa installed and usable")
    expect(Path((rep.get("model_folders") or {}).get("lama", "")) == snap, f"--check: LaMa from {snap}")


def mcp(d):
    installed = (d / "venv").exists()
    server = ROOT / "mcp" / ("run_mcp.cmd" if WIN else "run_mcp.sh")
    mine = Path(tempfile.mkdtemp(prefix="ci-models-"))  # a folder holding LaMa's file (an empty one: enough to find)
    (mine / "lama_fp32.onnx").write_bytes(b"")
    # RORem's UNet in a Hugging Face cache, and SDXL Inpainting's UNet in a folder of another name next to it: the same
    # config, so only the folder's name says which is RORem (no weights: empty files are enough to find)
    unet = {"_class_name": "UNet2DConditionModel", "in_channels": 9, "cross_attention_dim": 2048}
    rorem = mine / "hub" / "models--LetsThink--RORem" / "snapshots" / "0123abc"
    for f in (rorem, mine / "a-sdxl-unet"):
        (f / "unet").mkdir(parents=True)
        (f / "unet" / "config.json").write_text(json.dumps(unet), encoding="utf-8")
        (f / "unet" / "diffusion_pytorch_model.safetensors").write_bytes(b"")
    dirs = {"lama": str(mine), "sdxl": str(mine), "rorem": str(mine)}
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "ci", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "check_system", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "check_system", "arguments": {"model_dirs": dirs}}}]
    r = run(["cmd", "/c", server] if WIN else ["sh", server], show=False,
            input="".join(json.dumps(m) + "\n" for m in msgs), env=dict(os.environ, AIREMOVE_HOME=str(d)))
    expect(r.returncode == 0, f"server exit status 0 at the end of its input (it was {r.returncode})")
    replies = {}
    for line in r.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            raise Failed(f"stdout carries something that is not the protocol: {line[:200]!r}")
        replies[msg.get("id")] = msg
    expect(sorted(replies, key=str) == [1, 2, 3, 4], "one reply per request, none for the notification")
    for i in (1, 2, 3, 4):
        expect("result" in replies[i], f"request {i}: no error ({replies[i].get('error')})")
    init = replies[1]["result"]
    expect(init.get("protocolVersion") == PROTOCOL and (init.get("serverInfo") or {}).get("name") == "ai-remove",
           f"initialize: ai-remove {(init.get('serverInfo') or {}).get('version')}, protocol {PROTOCOL}")
    names = [t.get("name") for t in replies[2]["result"].get("tools", [])]
    expect(names == TOOLS, "tools/list: " + ", ".join(map(str, names)))
    res = replies[3]["result"]
    text = (res.get("content") or [{}])[0].get("text", "")
    expect(res.get("isError") is False, "check_system: no error" + (f" ({text[:300]})" if res.get("isError") else ""))
    print("  --- check_system\n" + text + "\n  --- end of check_system")
    rep = json.loads(text)
    expect(rep.get("os") == OS and rep.get("supported") is True, f"check_system: {OS}, supported")
    print(f"  info PyTorch build {(rep.get('pytorch_build') or {}).get('id')}, GPUs {rep.get('gpus')}")
    expect(rep.get("installed") is installed, f"check_system: installed {installed}")
    expect((rep.get("lightcraft") or {}).get("reachable") is False, "check_system: LightCraft not reachable")
    m = rep.get("models") or {}
    expect(sorted(m) == ["flux", "lama", "objectclear", "osor", "qwen", "rorem", "sam3", "sdxl"]
           and all(v.get("what") and v.get("licence") and v.get("gb") is not None for v in m.values()),
           "check_system: every model with what it is for, its size and licence")
    expect((m.get("lama") or {}).get("installed") is installed, f"check_system: LaMa installed {installed}")
    if installed:
        app = rep.get("app_check") or {}
        expect((app.get("models") or {}).get("lama") is True, "check_system app_check: models.lama true")
        expect((app.get("lightcraft") or {}).get("connected") is False, "check_system app_check: LightCraft not connected")
    res = json.loads((replies[4]["result"].get("content") or [{}])[0].get("text", "{}")).get("model_dirs") or {}
    expect((res.get("lama") or {}).get("ok") is True and Path(res["lama"]["found"]["lama"]) == mine,
           f"check_system model_dirs: LaMa found in {mine}")
    expect((res.get("sdxl") or {}).get("ok") is False and "sdxl-inpaint/model_index.json" in res["sdxl"].get("error", ""),
           f"check_system model_dirs: no SDXL there ({(res.get('sdxl') or {}).get('error')})")
    found = (res.get("rorem") or {}).get("found") or {}
    expect((res.get("rorem") or {}).get("ok") is True and Path(found.get("rorem", "")) == rorem,
           f"check_system model_dirs: RORem found in the Hugging Face cache, not in the SDXL UNet's folder ({found})")
    sys.path.insert(0, str(ROOT / "mcp"))
    import airemove_mcp
    args = airemove_mcp.install_args({"models": ["lama"], "model_dirs": {"lama": str(mine)}}, d)
    expect(args[args.index("--model-dir") + 1] == f"lama={mine}", "install tool: --model-dir lama=<folder>")
    shutil.rmtree(mine, ignore_errors=True)


def remove(d):
    py = d / "venv" / ("Scripts/python.exe" if WIN else "bin/python")
    expect(py.exists(), f"{py} exists")
    r = run([py, ROOT / "tools" / "ci_removal.py", d])
    expect(r.returncode == 0, f"removal end to end: exit status 0 (it was {r.returncode})")
    r = run([py, ROOT / "tools" / "ci_tiles.py", d])
    expect(r.returncode == 0, f"long removal in tiles: exit status 0 (it was {r.returncode})")
    r = run([py, ROOT / "tools" / "ci_pictures.py", d])
    expect(r.returncode == 0, f"removals on JPEG, PNG, TIFF, WebP, HEIC, AVIF: exit status 0 (it was {r.returncode})")
    r = run([py, ROOT / "tools" / "ci_describe.py", d])
    expect(r.returncode == 0, f"Describe's masks: exit status 0 (it was {r.returncode})")


def uninstall(d):
    shortcut = config(d).get("shortcut")
    mine = sorted(set((config(d).get("model_paths") or {}).values()))
    script = d / {"windows": "Uninstall AI Remove.cmd", "macos": "Uninstall AI Remove.command"}.get(OS, "uninstall.sh")
    expect(script.exists(), f"uninstaller {script.name} exists")
    r = run((["cmd", "/c"] if WIN else ["sh"]) + [script, "--yes"])
    expect(r.returncode == 0, f"uninstaller exit status 0 (it was {r.returncode})")
    expect(not (d / "venv").exists() and not (d / "airemove.json").exists(), "venv and airemove.json removed")
    expect(not shortcut or not Path(shortcut).exists(), f"menu entry / app removed: {shortcut}")
    expect(not project_type(shortcut or ""), ".airemove file type removed")
    if OS == "linux":
        data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        left = sorted(str(p) for p in (data / "icons" / "hicolor").glob("*/*/airemove*"))
        expect(not left, f"the app's and the .airemove files' icons removed (left: {left})")
    expect(all(Path(f).is_dir() and any(Path(f).iterdir()) for f in mine), f"the user's model folders are left: {mine}")
    if WIN:
        q = subprocess.run(["reg", "query", WIN_UNINSTALL_KEY], capture_output=True)
        expect(q.returncode != 0, "Settings > Apps entry removed")
        for __ in range(30):  # what was in use goes a few seconds after the uninstaller (a detached cmd)
            if not d.exists():
                break
            time.sleep(1)
        expect(not d.exists(), "install folder removed" + (f" (left: {[p.name for p in d.iterdir()]})"
                                                           if d.exists() else ""))
    else:
        left = [p.name for p in d.iterdir()] if d.exists() else []
        expect(not left, f"install folder emptied (left: {left})")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "folder", "mcp", "remove", "uninstall"):
        print(__doc__)
        return 2
    d = Path(sys.argv[2]).expanduser().resolve()
    print(f"{sys.argv[1]} {d}")
    try:
        {"check": check, "folder": folder, "mcp": mcp, "remove": remove, "uninstall": uninstall}[sys.argv[1]](d)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
