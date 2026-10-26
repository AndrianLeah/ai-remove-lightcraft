"""The installer with an app that refuses to have its external editor changed while it runs, for the CI runners:
tools/ci_smoke.py check runs this. LightCraft from storytold/lightcraft#2638 on lets only the user choose the
programs Edit In starts (Settings > External Editing): `ui.set` refuses settings.externalEditor. Its ui.json, read
when it starts, still takes them while it is closed.

A fake app answers the installer's control-channel requests (install.lc_request), says whether it runs
(install.lc_running) and keeps its ui.json in a temporary folder; nothing of the computer's own apps, variables or
settings is touched (install.set_control_port is a stub).
  - set up while it is open, with --yes: "pending" (close it, run the configuration again); no shortcut set, which
    would start the editor the app had; its ui.json untouched;
  - the same, asked: the user closes it, then its ui.json gets the editor and the shortcut;
  - an update while it is open, the editor already this install's: no change, so not refused: set at once;
  - an app from before the lock: set at once, as before;
  - removed while it is open, with --yes: the shortcut cleared, never "external editor removed" when it was refused;
    the user is told to remove it in Settings; asked: once closed, its ui.json cleared;
  - removed from an app from before the lock: cleared at once; an editor that is not this install's: left alone.
Exit status 1 at the first check that fails. Standard library only.

  ci_editor_lock.py
"""
import builtins
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "installer"))
sys.path.insert(0, str(ROOT / "airemove"))
import i18n  # noqa: E402
import install  # noqa: E402
import system  # noqa: E402

i18n.set_language("en")
LOCKED = ("ui.set: the programs Edit In starts (settings.externalEditor, settings.photocraftPath) are chosen in "
          "Settings ▸ External Editing, not by a client")  # LightCraft's own words


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


class FakeApp:
    """The app, open or closed, with or without the lock; what the installer asked of it."""

    def __init__(self, folder, editor="", locked=True, running=True, closes_when_asked=False):
        self.ui_json = Path(folder) / "ui.json"
        self.settings = {"externalEditor": editor, "keymap": {}}
        self.ui_json.write_text(json.dumps({"settings": self.settings}), encoding="utf-8")
        self.locked, self.running, self.closes_when_asked = locked, running, closes_when_asked
        self.asked = []

    def request(self, port, method, params, timeout=10, host=system.LIGHTCRAFT):
        if not self.running:
            return None
        self.asked.append((method, params))
        if method == "ui.set":
            want = (params.get("settings") or {}).get("externalEditor", self.settings["externalEditor"])
            if self.locked and want != self.settings["externalEditor"]:
                return {"ok": False, "error": LOCKED}
            self.settings["externalEditor"] = want
            return {"ok": True, "result": {"settings": json.loads(json.dumps(self.settings))}}
        if method == "engine.execute" and params["command"] == "app.setShortcut":
            p = params["params"]
            if p["shortcut"]:
                self.settings["keymap"][p["id"]] = p["shortcut"]
            else:
                self.settings["keymap"].pop(p["id"], None)
            return {"ok": True, "result": {}}
        return {"ok": True, "result": {}}

    def quit(self):
        """It rewrites its ui.json when it quits, with what it has."""
        self.running = False
        self.ui_json.write_text(json.dumps({"settings": self.settings}), encoding="utf-8")

    def ask(self, prompt=""):
        if not self.closes_when_asked:
            raise Failed(f"asked to close the app with --yes or when it never closes: {prompt!r}")
        self.quit()
        return ""

    def file(self):
        return json.loads(self.ui_json.read_text(encoding="utf-8"))["settings"]

    def shortcut_asked(self):
        return [p for m, p in self.asked if m == "engine.execute" and p["command"] == "app.setShortcut"]


def use(app):
    install.lc_request = app.request
    install.lc_running = lambda host=system.LIGHTCRAFT: app.running
    install.ui_json = lambda host=system.LIGHTCRAFT: app.ui_json
    install.set_control_port = lambda port, cfg, host=system.LIGHTCRAFT: ["(stub)"]
    builtins.input = app.ask


def said():
    """What the installer wrote since the last call."""
    text, said.lines = "\n".join(said.lines), []
    return text


said.lines = []


def main():
    install.out.write = lambda text: said.lines.append(text)
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "AI Remove"
        d.mkdir()
        editor = str(d / "venv" / "Scripts" / "airemove.exe")
        km = lambda app: app.file().get("keymap") or {}  # noqa: E731

        print("set up while the app is open and locked")
        app = FakeApp(t, editor="DxO PhotoLab")
        use(app)
        cfg = {}
        state, msg = install.configure_lightcraft(d, cfg, editor, yes=True)
        expect(state == "pending" and cfg["lightcraft"] == "pending", f"--yes: pending ({msg})")
        expect("close it, then run the configuration again" in msg, "it says to close the app and run it again")
        expect("does not let another program change its external editor" in said(), "it says why")
        expect(not app.shortcut_asked(), "no shortcut set while the editor is still the app's own")
        expect(app.file()["externalEditor"] == "DxO PhotoLab" and not km(app), "its ui.json untouched")

        app = FakeApp(t, editor="DxO PhotoLab", closes_when_asked=True)
        use(app)
        state, msg = install.configure_lightcraft(d, {}, editor, yes=False)
        expect(state == "done" and not app.running, f"asked: closed by the user, then done ({msg})")
        expect(app.file()["externalEditor"] == editor and km(app).get(install.EDIT_COMMAND) == install.SHORTCUT,
               "its ui.json has this AI Remove and the shortcut")
        said()

        print("an update while the app is open and locked, the editor already this install's")
        app = FakeApp(t, editor=editor)
        use(app)
        state, msg = install.configure_lightcraft(d, {}, editor, yes=True)
        expect(state == "done" and app.running, f"set at once ({msg})")
        expect(app.settings["keymap"].get(install.EDIT_COMMAND) == install.SHORTCUT, "the shortcut set live")
        said()

        print("an app from before the lock")
        app = FakeApp(t, editor="DxO PhotoLab", locked=False)
        use(app)
        state, msg = install.configure_lightcraft(d, {}, editor, yes=True)
        expect(state == "done" and app.settings["externalEditor"] == editor, f"set at once, as before ({msg})")
        said()

        cfg = {"editor": editor}
        print("removed while the app is open and locked")
        app = FakeApp(t, editor=editor)
        app.settings["keymap"][install.EDIT_COMMAND] = install.SHORTCUT
        use(app)
        install.unhook(d, cfg, yes=True)
        text = said()
        expect("external editor removed" not in text, "never \"external editor removed\" when it was refused")
        expect("remove the external editor yourself in Settings > External Editing" in text,
               "the user is told where to remove it")
        expect(install.EDIT_COMMAND not in app.settings["keymap"], "the shortcut cleared: it would start what is gone")
        expect(app.settings["externalEditor"] == editor, "the editor still there, as the app said")

        app = FakeApp(t, editor=editor, closes_when_asked=True)
        app.settings["keymap"][install.EDIT_COMMAND] = install.SHORTCUT
        use(app)
        install.unhook(d, cfg, yes=False)
        text = said()
        expect("external editor and shortcut removed" in text, "asked: closed by the user, then removed")
        expect(app.file()["externalEditor"] == "" and install.EDIT_COMMAND not in km(app), "its ui.json cleared")

        print("removed from an app from before the lock")
        app = FakeApp(t, editor=editor, locked=False)
        use(app)
        install.unhook(d, cfg, yes=True)
        expect("external editor removed" in said() and app.settings["externalEditor"] == "", "cleared at once")

        print("an editor that is not this install's")
        app = FakeApp(t, editor="DxO PhotoLab")
        use(app)
        install.unhook(d, cfg, yes=True)
        expect("not this installation, left as it is" in said() and app.settings["externalEditor"] == "DxO PhotoLab",
               "left alone")
    print("all checks passed")


if __name__ == "__main__":
    try:
        main()
    except Failed as e:
        print("  FAILED  " + str(e))
        sys.exit(1)
