"""Smoke test of a real install, for the CI runners (.github/workflows/ci.yml). DIR is an install folder made by
installer/bootstrap.(ps1|sh) --models lama --no-lightcraft: LightCraft is not on the runners.

  ci_smoke.py check DIR        airemove-cli --check prints JSON: PyTorch of the build asked for, LaMa installed and
                               usable, LightCraft not connected; uv in DIR/bin, the menu entry / app made
  ci_smoke.py mcp DIR          the MCP server over stdio through its launcher (mcp/run_mcp.cmd|sh), AIREMOVE_HOME=DIR:
                               initialize, tools/list, check_system (which must see whether DIR is installed)
  ci_smoke.py remove DIR       one removal end to end with the install's Python and code, LightCraft left out:
                               tools/ci_removal.py (a synthetic raw DNG, LaMa, the blend, the DNG and the project)
  ci_smoke.py uninstall DIR    the uninstaller the install made (Settings > Apps / the install folder) with --yes: the
                               app, its menu entry and, on Windows, its Settings > Apps entry are gone
Exit status 1 at the first check that fails. Standard library only.
"""
import json
import os
import subprocess
import sys
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


def check(d):
    cfg = config(d)
    cli = d / "venv" / ("Scripts/airemove-cli.exe" if WIN else "bin/airemove-cli")
    expect(cli.exists(), f"{cli} exists")
    r = run([cli, "--check"])
    expect(r.returncode == 0, f"--check exit status 0 (it was {r.returncode})")
    rep = report(r.stdout)
    expect(rep.get("version") == system.VERSION and rep.get("os") == OS, f"version {system.VERSION} on {OS}")
    expect("torch" in rep, f"PyTorch imports: {rep.get('torch') or rep.get('torch_error')}")
    if cfg.get("torch") == "cpu":  # PyTorch's own index, not PyPI's build (CUDA on Linux)
        expect(rep["torch"].endswith("+cpu"), f"PyTorch is the processor build ({rep['torch']})")
    print(f"  info device {rep.get('device')}: {rep.get('gpu')}")
    expect((rep.get("models") or {}).get("lama") is True, "models.lama true")
    expect("lama" in (rep.get("usable_models") or []), "LaMa usable")
    expect((rep.get("lightcraft") or {}).get("connected") is False,
           f"lightcraft.connected false (no LightCraft here: {(rep.get('lightcraft') or {}).get('error')})")
    uv = "uv.exe" if WIN else "uv"
    expect((d / "bin" / uv).exists() or (d / "bin" / "bin" / uv).exists(), "uv fetched into <install>/bin")
    expect(cfg.get("shortcut") and Path(cfg["shortcut"]).exists(), f"menu entry / app: {cfg.get('shortcut')}")


def mcp(d):
    installed = (d / "venv").exists()
    server = ROOT / "mcp" / ("run_mcp.cmd" if WIN else "run_mcp.sh")
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "ci", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "check_system", "arguments": {}}}]
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
    expect(sorted(replies, key=str) == [1, 2, 3], "one reply per request, none for the notification")
    for i in (1, 2, 3):
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
    if installed:
        app = rep.get("app_check") or {}
        expect((app.get("models") or {}).get("lama") is True, "check_system app_check: models.lama true")
        expect((app.get("lightcraft") or {}).get("connected") is False, "check_system app_check: LightCraft not connected")


def remove(d):
    py = d / "venv" / ("Scripts/python.exe" if WIN else "bin/python")
    expect(py.exists(), f"{py} exists")
    r = run([py, ROOT / "tools" / "ci_removal.py", d])
    expect(r.returncode == 0, f"removal end to end: exit status 0 (it was {r.returncode})")


def uninstall(d):
    shortcut = config(d).get("shortcut")
    script = d / {"windows": "Uninstall AI Remove.cmd", "macos": "Uninstall AI Remove.command"}.get(OS, "uninstall.sh")
    expect(script.exists(), f"uninstaller {script.name} exists")
    r = run((["cmd", "/c"] if WIN else ["sh"]) + [script, "--yes"])
    expect(r.returncode == 0, f"uninstaller exit status 0 (it was {r.returncode})")
    expect(not (d / "venv").exists() and not (d / "airemove.json").exists(), "venv and airemove.json removed")
    expect(not shortcut or not Path(shortcut).exists(), f"menu entry / app removed: {shortcut}")
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
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "mcp", "remove", "uninstall"):
        print(__doc__)
        return 2
    d = Path(sys.argv[2]).expanduser().resolve()
    print(f"{sys.argv[1]} {d}")
    try:
        {"check": check, "mcp": mcp, "remove": remove, "uninstall": uninstall}[sys.argv[1]](d)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
