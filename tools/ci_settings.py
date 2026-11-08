"""Chromaforge's names and the Settings window's logic, for the CI runners (tools/ci_smoke.py check runs this): no app,
no window, nothing of the computer's own settings, variables or apps touched — the install, the apps' programs and
settings folders are made up in a temporary folder, the environment variables are this process's, the installer's
commands (setx, launchctl, systemctl) are recorded instead of run.
  - Chromaforge's names: a build from 26.45 on (chromaforge, CHROMAFORGE_*, "Chromaforge") and one from before
    (lightcraft-classic, LIGHTCRAFT_CLASSIC_*, "LightCraft Classic"): which program is which, the variables each
    reads in its order, its settings folder, its token in either folder;
  - the clash: with only AI Remove 1.7.0's variables (LIGHTCRAFT_CONTROL_PORT, LIGHTCRAFT_CLASSIC_CONTROL_PORT) the new
    build reads LightCraft's port; which app answers on it; the installer sets the app's own variables (all three
    systems' ways), and then there is none;
  - the Settings window's choices saved in airemove.json and used by system.Host (program, command line, host_cli): a
    program, a command line, a folder searched, automatic again; the models folder and a model's own folder
    (model_files, and engines when this Python has numpy);
  - "Set up again": the installer's step 6 for one app (done; never opened: first_run; open and locked: pending; not
    installed: failed), the variable then read by AI Remove's own process.
Exit status 1 at the first check that fails. Standard library only.

  ci_settings.py
"""
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="ci-settings-"))
# the apps' settings folders, menus and install folders: the temporary folder's, never the computer's
for var, sub in (("APPDATA", "appdata"), ("HOME", "home"), ("USERPROFILE", "home"), ("XDG_CONFIG_HOME", "config"),
                 ("XDG_DATA_HOME", "data"), ("XDG_DATA_DIRS", "share"), ("ProgramW6432", "pf"),
                 ("ProgramFiles", "pf"), ("LOCALAPPDATA", "local")):
    os.environ[var] = str(TMP / sub)
    (TMP / sub).mkdir(exist_ok=True)
for v in list(os.environ):
    if v.split("_")[0] in ("LIGHTCRAFT", "CHROMAFORGE", "NONAMEYET"):
        del os.environ[v]
sys.path.insert(0, str(ROOT / "installer"))
sys.path.insert(0, str(ROOT / "airemove"))
import i18n  # noqa: E402
import install  # noqa: E402
import model_files as mf  # noqa: E402
import settings  # noqa: E402
import system  # noqa: E402

i18n.set_language("en")
OS = system.system()
INSTALL = TMP / "AIRemove"
INSTALL.mkdir()
system.ROOT, system.CONFIG_FILE = INSTALL, INSTALL / "airemove.json"  # the install the Settings window changes
RUNNING = []  # the programs "running": none unless a check says so
system.running_programs = lambda fresh=False: list(RUNNING)
system._app_paths = lambda exe: []
CF, LC = system.CHROMAFORGE, system.LIGHTCRAFT
NEW, OLD = CF.names
SET_PORT, UNSET_PORT = install.set_control_port, install.unset_control_port  # FakeApp stubs the first one


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


def cfg():
    return json.loads(system.CONFIG_FILE.read_text(encoding="utf-8")) if system.CONFIG_FILE.exists() else {}


def same(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def make_app(folder, names):
    """A made-up build: (its program, its command line), laid out as its installers do on this system."""
    if OS == "macos":
        app = folder / names.mac_app
        bin_ = app / "Contents" / "MacOS"
        bin_.mkdir(parents=True)
        (bin_ / names.exe).write_bytes(b"")
        (bin_ / f"{names.exe}-cli").write_bytes(b"")
        return app, bin_ / f"{names.exe}-cli"
    ext = ".exe" if OS == "windows" else ""
    folder.mkdir(parents=True)
    (folder / f"{names.exe}{ext}").write_bytes(b"")
    (folder / f"{names.exe}-cli{ext}").write_bytes(b"")
    return folder / f"{names.exe}{ext}", folder / f"{names.exe}-cli{ext}"


def names_and_ports():
    print("Chromaforge's names")
    expect(CF.own_vars("CONTROL_PORT") == ["CHROMAFORGE_CONTROL_PORT", "LIGHTCRAFT_CLASSIC_CONTROL_PORT"],
           "Chromaforge's own variables: CHROMAFORGE_CONTROL_PORT, then LIGHTCRAFT_CLASSIC_CONTROL_PORT")
    expect(LC.own_vars("CONTROL_PORT") == ["LIGHTCRAFT_CONTROL_PORT"], "LightCraft's: LIGHTCRAFT_CONTROL_PORT alone")
    new_app, new_cli = make_app(TMP / "apps" / "Chromaforge", NEW)
    old_app, old_cli = make_app(TMP / "apps" / "Old", OLD)
    expect(CF.names_of(new_app) is NEW and CF.names_of(old_app) is OLD, "each build's program says its names")
    expect(CF.app() is None and CF.names_now() is NEW, "none installed: the current names")
    expect(Path(CF.config_dir()).name.lower() == "chromaforge", f"its settings folder: {CF.config_dir()}")
    progs = CF.programs()
    expect(any(p.startswith("chromaforge") for p in progs) and any(p.startswith("lightcraft-classic") for p in progs),
           f"the panel's tether knows both programs: {progs}")

    print("the clash: AI Remove 1.7.0's variables only")
    os.environ.update(LIGHTCRAFT_CONTROL_PORT="7980", LIGHTCRAFT_CLASSIC_CONTROL_PORT="7981")
    expect(CF.port() == 7980 and CF.clash() is LC, "the new build reads LIGHTCRAFT_CONTROL_PORT: LightCraft's port")
    system.save_config(app_paths={"chromaforge": {"app": str(old_app)}})
    expect(CF.names_now() is OLD and CF.port() == 7981 and CF.clash() is None,
           "a build from before reads LIGHTCRAFT_CLASSIC_CONTROL_PORT first: no clash")
    expect(Path(CF.config_dir()).name.lower() == "lightcraft classic",
           f"and its own settings folder: {CF.config_dir()}")
    system.save_config(app_paths=None)
    os.environ["CHROMAFORGE_CONTROL_PORT"] = "7981"
    expect(CF.port() == 7981 and CF.clash() is None, "with CHROMAFORGE_CONTROL_PORT: its own port")

    print("which app answers on a port they share")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = str(srv.getsockname()[1])
    os.environ.update(LIGHTCRAFT_CONTROL_PORT=port)
    del os.environ["CHROMAFORGE_CONTROL_PORT"]
    try:
        expect(CF.clash() is LC and LC.answers() and not CF.answers(), "neither running: LightCraft's")
        RUNNING[:] = [str(new_app)]
        expect(CF.answers() and not LC.answers(), "Chromaforge running, LightCraft not: Chromaforge's")
        RUNNING[:] = []
    finally:
        srv.close()
    os.environ.update(LIGHTCRAFT_CONTROL_PORT="7980")

    print("the token, in either build's settings folder")
    old_dir, new_dir = CF.config_dir(OLD), CF.config_dir(NEW)
    old_dir.mkdir(parents=True)
    (old_dir / "control-token-7981").write_text("a" * 64, encoding="utf-8")
    os.environ["CHROMAFORGE_CONTROL_PORT"] = "7981"
    expect(CF.token() == "a" * 64, "only the old folder has one: that one")
    new_dir.mkdir(parents=True)
    (new_dir / "control-token-7981").write_text("b" * 64, encoding="utf-8")
    expect(CF.token() == "b" * 64, "the build in use's own folder first")
    return new_app, new_cli, old_app, old_cli


def choices(new_app, new_cli, old_app, old_cli):
    print("the Settings window: the apps' programs")
    ok, msg = settings.choose_program(CF, new_app)
    ch = (cfg().get("app_paths") or {}).get("chromaforge") or {}
    expect(ok and same(ch.get("app"), new_app) and same(ch.get("cli"), new_cli), f"a program chosen, its command line "
                                                                                    f"with it: {msg}")
    expect(same(CF.app(), new_app) and same(CF.cli()[0], new_cli), "system.Host uses them")
    if LC.cli() is None:
        h, cli = system.host_cli()
        expect(h is CF and same(cli[0], new_cli), "a RAW opened on its own is read with that command line")
    ok, msg = settings.choose_program(CF, TMP / "apps" / "Old")
    expect(ok and same(CF.app(), old_app) and CF.names_now() is OLD, f"a folder searched: the build in it ({msg})")
    ok, msg = settings.choose_program(CF, TMP / "apps")
    expect(ok and CF.app() is not None, f"a folder above both: one of them ({msg})")
    other = TMP / "elsewhere"
    other.mkdir()
    shutil.copy(new_cli, other / new_cli.name)
    ok, msg = settings.choose_cli(CF, other / new_cli.name)
    expect(ok and same(CF.cli()[0], other / new_cli.name), f"a command line chosen on its own ({msg})")
    ok, msg = settings.choose_program(CF, other / new_cli.name)
    expect(ok and same(CF.cli()[0], other / new_cli.name),
           "a command line given as the program: kept as the command line")
    before = cfg()
    empty = TMP / "empty"
    empty.mkdir()
    ok, msg = settings.look_in(CF, empty)
    expect(not ok and cfg() == before, f"a folder without it: nothing changed ({msg})")
    ok, msg = settings.forget_choice(CF)
    expect(ok and "app_paths" not in cfg() and CF.app() is None, "found by itself again: the choice gone")
    st = settings.app_state(CF, live=False)
    expect(st["variables"] == CF.own_vars("CONTROL_PORT") and st["app"] is None, "the window's state of an app")


def models():
    print("the Settings window: the models")
    expect(same(mf.models_dir(), INSTALL / "models"), "the install's models folder at first")
    other = TMP / "models2"
    (other / "lama").mkdir(parents=True)
    (other / "lama" / "lama_fp32.onnx").write_bytes(b"onnx")
    ok, msg = settings.use_models_folder(other)
    expect(ok and same(cfg().get("models_dir"), other) and same(mf.models_dir(), other) and mf.has("lama"),
           f"another models folder, used at once ({msg})")
    expect(same(install.models_root(INSTALL, cfg()), other), "the installer downloads into it too")
    snap = TMP / "cache" / "models--Carve--LaMa-ONNX" / "snapshots" / "0123"
    snap.mkdir(parents=True)
    (snap / "lama_fp32.onnx").write_bytes(b"onnx")
    ok, msg = settings.use_model_folder("lama", TMP / "cache")
    expect(ok and same((cfg().get("model_paths") or {}).get("lama"), snap) and same(mf.part_dir("lama"), snap)
           and mf.where("lama")[0] == "yours", f"a model's own folder (a Hugging Face cache): {msg}")
    before = cfg()
    ok, msg = settings.use_model_folder("rorem", TMP / "empty")
    expect(not ok and cfg() == before, f"a folder without the model: nothing changed ({msg})")
    try:
        import numpy  # noqa: F401  (the install's Python: the app's own lookup too)
        import engines
        expect(engines.installed("lama") and same(engines.model_folders().get("lama"), snap),
               "engines finds it there")
    except ImportError:
        print("  --  engines not checked: no numpy in this Python")
    settings.forget_model_folder("lama")
    expect("lama" not in (cfg().get("model_paths") or {}) and mf.where("lama")[0] == "models",
           "from the models folder again")
    rows = {m["model"]: m for m in settings.models_state()}
    expect(rows["lama"]["state"] == "models" and rows["flux"]["state"] == "missing", "the window's model rows")
    settings.use_models_folder(None)
    expect("models_dir" not in cfg() and same(mf.models_dir(), INSTALL / "models"), "the default models folder again")


class FakeApp:
    """The app for the installer's step 6: open or not, locked (storytold/lightcraft#2638) or not."""

    def __init__(self, host):
        self.host, self.open, self.locked, self.ports = host, False, False, []
        install.lc_running = lambda host=None: self.open and host is self.host
        install.lc_request = self.request
        install.set_control_port = self.set_port

    def set_port(self, port, cfg_, host=system.LIGHTCRAFT):
        self.ports.append((port, host.key))
        cfg_[host.cfg_key("port")], cfg_[host.cfg_key("control_env")] = port, True
        return ["(recorded)"]

    def request(self, port, method, params, timeout=10, host=None):
        if not self.open:
            return None
        if method == "ui.set" and "externalEditor" in (params.get("settings") or {}) and self.locked:
            return {"ok": False, "error": "locked"}
        return {"ok": True, "result": {"settings": {}}}


def set_up(new_app):
    print("the Settings window: Set up again (the installer's step 6)")
    app = FakeApp(CF)  # first: the real set_control_port would change this computer's variables
    system.save_config(app_paths={"chromaforge": {"app": str(new_app)}})
    for v in CF.own_vars("CONTROL_PORT"):
        os.environ.pop(v, None)
    os.environ["LIGHTCRAFT_CONTROL_PORT"] = "7980"
    state, msg, __ = settings.setup(CF)
    expect(state == "failed" and "not installed by its installer" in msg, f"no AI Remove program: refused ({msg})")
    editor = INSTALL / "venv" / "airemove-program"
    editor.parent.mkdir()
    editor.write_bytes(b"")
    system.save_config(editor=str(editor), chromaforge_port=7981)
    shutil.rmtree(CF.config_dir(NEW))
    state, msg, __ = settings.setup(CF)
    expect(state == "first_run", f"never opened: open it once first ({msg})")
    CF.config_dir(NEW).mkdir(parents=True)
    for v in CF.own_vars("CONTROL_PORT"):
        os.environ.pop(v, None)
    expect(CF.clash() is LC, "before: the clash")
    state, msg, lines = settings.setup(CF)
    ui = json.loads(CF.ui_json().read_text(encoding="utf-8")).get("settings") or {}
    expect(state == "done" and same(ui.get("externalEditor"), editor)
           and (ui.get("keymap") or {}).get(install.EDIT_COMMAND) == install.SHORTCUT,
           f"closed: its ui.json gets the editor and the shortcut ({msg})")
    expect(app.ports[-1] == (7981, "chromaforge") and "chromaforge" in cfg().get("apps", []),
           "its port's variables set, and the update keeps it set up")
    expect(all(os.environ.get(v) == "7981" for v in CF.own_vars("CONTROL_PORT")) and CF.clash() is None,
           "AI Remove's own process reads the new variables: no clash")
    app.open, app.locked = True, True
    CF.ui_json().write_text("{}", encoding="utf-8")
    state, msg, lines = settings.setup(CF)
    expect(state == "pending" and CF.ui_json().read_text(encoding="utf-8") == "{}",
           f"open and locked: close it first, its ui.json untouched ({msg})")


def variables():
    """install.set_control_port / unset_control_port on each system, their commands recorded."""
    print("the installer's variables on each system")
    ran = []
    install.output = lambda cmd, timeout=30: ran.append([str(c) for c in cmd]) or ""
    CF.is_flatpak = lambda: False
    real = system.system
    want = ["CHROMAFORGE_CONTROL_PORT", "LIGHTCRAFT_CLASSIC_CONTROL_PORT"]
    try:
        system.system = lambda: "windows"
        SET_PORT(7981, {"dir": str(INSTALL)}, CF)
        expect([c[1] for c in ran if c[0] == "setx"] == want, "Windows: setx for both")
        ran.clear()
        UNSET_PORT(INSTALL, {}, CF)
        expect([c[4] for c in ran if c[:2] == ["reg", "delete"]] == want, "Windows: both removed")

        system.system = lambda: "macos"
        ran.clear()
        SET_PORT(7981, {"dir": str(INSTALL)}, CF)
        plist = (Path.home() / "Library" / "LaunchAgents" / "com.airemove.chromaforge-control.plist").read_text("utf-8")
        expect(all(f"setenv {v} 7981" in plist for v in want) and
               [c[2] for c in ran if c[:2] == ["launchctl", "setenv"]] == want, "macOS: the LaunchAgent sets both")

        system.system = lambda: "linux"
        apps = TMP / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        (apps / f"{CF.app_id}.desktop").write_text("[Desktop Entry]\nExec=chromaforge %F\n", encoding="utf-8")
        ran.clear()
        c = {"dir": str(INSTALL)}
        SET_PORT(7981, c, CF)
        conf = (TMP / "config" / "environment.d" / "60-chromaforge-control.conf").read_text("utf-8")
        expect(conf == "".join(f"{v}=7981\n" for v in want), "Linux: environment.d has both")
        if os.pathsep == ":":  # XDG_DATA_DIRS is a list split at ":", which a Windows path has in it
            entry = Path(c["chromaforge_desktop_override"]).read_text("utf-8")
            expect("Exec=env CHROMAFORGE_CONTROL_PORT=7981 LIGHTCRAFT_CLASSIC_CONTROL_PORT=7981 chromaforge %F"
                   in entry, "Linux: the menu entry starts it with both")
    finally:
        system.system = real


def main():
    try:
        apps = names_and_ports()
        choices(*apps)
        models()
        set_up(apps[0])
        variables()
    except Failed as e:
        print("FAILED: " + str(e))
        return 1
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("ci_settings: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
