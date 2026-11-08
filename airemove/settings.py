"""AI Remove's Settings window: what the installer asked once, seen and changed afterwards (airemove --settings, the
gear in the window's header and in the panel's).

For each app (LightCraft, Chromaforge: system.Host):
- its program and its command line: the ones found (where its installers put them, and the program running now,
  wherever it is), one of them picked, a file chosen, or a folder searched for them (system.find_programs) — saved
  in airemove.json "app_paths", which system.Host.app / cli read at every use (so the panel's tether, a RAW read on its
  own through the command line, --check, the installer and the MCP server all follow it);
- its control channel: the port, the variable the app reads it from, whether it answers, and a clash (Chromaforge 26.45
  on LightCraft's port: system.Host.clash);
- its external editor and shortcut (live from the app when it answers, else its ui.json);
- "Set up again": the installer's own step 6 for that app (install.configure_lightcraft: the control port's variable,
  the external editor, the shortcut — live when the app lets it, else in its ui.json once it is closed: LightCraft
  from storytold/lightcraft#2638 on refuses another program's externalEditor while it runs).
The models: the install's models folder (airemove.json "models_dir") and, per model, a folder of the user's own
(airemove.json "model_paths", as the installer's --model-dir: model_files.use_folder), read by model_files at every use.

Every change is saved at once. The logic is in functions without Tk (app_state, models_state, choose_program,
choose_cli, look_in, setup...): tools/ci_settings.py runs them on the CI runners, without the apps."""
import os
import queue
import sys
import threading
from pathlib import Path

import model_files as mf
import system
from i18n import N_, _

_INSTALLER = None


def installer():
    """The installer module of this install (its step 6 functions; it prints nothing on import)."""
    global _INSTALLER
    if _INSTALLER is None:
        d = str(system.ROOT / "installer")
        if d not in sys.path:
            sys.path.insert(0, d)
        import install
        _INSTALLER = install
    return _INSTALLER


class Said:
    """The installer's output (install.out) while one of its functions runs here: kept, shown in the window."""

    def __init__(self):
        self.lines = []

    def write(self, text):
        for line in str(text).splitlines():
            if line.strip():
                self.lines.append(line.strip())

    def note(self, text):
        pass

    def status(self, *a, **k):
        pass

    def title(self, *a, **k):
        pass


# ------------------------------------------------------------------------------------------------ the apps
def _same(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def program_candidates(host):
    """[(program, how)]: the one chosen, the ones installed where its installers put them, the one running (anywhere):
    how is "chosen" | "installed" | "flatpak" | "running"; each program once."""
    out = []
    chosen = host.chosen().get("app")
    if chosen and Path(chosen).exists():
        out.append((chosen, "chosen"))
    out += host.found_apps()
    run = host.running()
    if run:
        out.append((run, "running"))
    seen, uniq = [], []
    for p, how in out:
        if not any(_same(p, s) for s in seen):
            seen.append(p)
            uniq.append((p, how))
    return uniq


def cli_candidates(host, app=None):
    """[(command line, how)]: "env" (<PREFIX>_CLI), "chosen", "next" (next to the program, or inside its bundle),
    "path" (on the PATH); each once."""
    import shutil
    out = []
    env = next((os.environ[x] for x in host.own_vars("CLI") if os.environ.get(x)), None)
    if env:
        out.append((env, "env"))
    chosen = host.chosen().get("cli")
    if chosen and Path(chosen).is_file():
        out.append((chosen, "chosen"))
    for p, __ in program_candidates(host) if app is None else [(app, "")]:
        if p and not p.startswith("flatpak:"):
            nxt = host.cli_next_to(p)
            if nxt:
                out.append((nxt, "next"))
    out += [(shutil.which(n), "path") for n in host.cli_names() if shutil.which(n)]
    seen, uniq = [], []
    for p, how in out:
        if not any(_same(p, s) for s in seen):
            seen.append(p)
            uniq.append((p, how))
    return uniq


def editor_state(host, live):
    """(external editor, shortcut set?) of the app: from the app itself when it answers (live), else its ui.json."""
    ins = installer()
    st = None
    if live:
        r = ins.lc_request(host.port(), "ui.set", {}, timeout=5, host=host)  # no change: its current settings
        if r and r.get("ok"):
            st = (r.get("result") or {}).get("settings") or {}
    if st is None:
        try:
            import json
            st = json.loads(host.ui_json().read_text(encoding="utf-8-sig")).get("settings") or {}
        except (OSError, ValueError, AttributeError):
            st = {}
    return st.get("externalEditor") or "", (st.get("keymap") or {}).get(ins.EDIT_COMMAND) == ins.SHORTCUT


def app_state(host, live=True):
    """Everything the window shows about one app, as plain values (live=False: nothing asked of the app itself)."""
    ins = installer()
    cfg = system.config()
    app = host.app()
    cands = program_candidates(host)
    how = next((h for p, h in cands if _same(p, app)), None) if app else None
    if app and app.startswith("flatpak:"):
        how = "flatpak"
    clis = cli_candidates(host)
    cli = host.cli()
    cli = cli[-1] if cli else None
    cli_how = next((h for p, h in clis if _same(p, cli)), "path" if cli else None)
    running = host.running()
    answers = host.answers(timeout=0.5)
    editor, shortcut = editor_state(host, live and answers)
    clash = host.clash()
    return {"key": host.key, "name": host.name, "app": app, "app_how": how, "apps": cands,
            "cli": cli, "cli_how": cli_how, "clis": clis, "program": host.names_now().exe,
            "running": running, "port": host.port(), "variable": host.var("CONTROL_PORT"),
            "variables": host.own_vars("CONTROL_PORT"), "answers": answers,
            "clash": clash.name if clash and host.app() else None,
            "editor": editor, "editor_ours": ins.is_ours(editor, system.ROOT, cfg), "shortcut": shortcut,
            "settings": str(host.config_dir()), "configured": cfg.get(host.key)}


def _save_choice(host, **kw):
    """airemove.json "app_paths" for the app: kw's keys set (None: removed); an empty choice removes the app's entry."""
    paths = dict(system.config().get("app_paths") or {})
    mine = {k: v for k, v in dict(paths.get(host.key) or {}).items() if k in ("app", "cli")}
    for k, v in kw.items():
        if v:
            mine[k] = str(v)
        else:
            mine.pop(k, None)
    if mine:
        paths[host.key] = mine
    else:
        paths.pop(host.key, None)
    system.save_config(app_paths=paths or None)


def choose_program(host, path):
    """The app's program chosen by the user: a file (on a Mac its .app), or a folder searched for it. Its command line
    goes with it when it is next to it (or a command line chosen as the program: kept as that). The automatic one
    chosen again: the choice is dropped (automatic again). Returns (ok, message)."""
    p = Path(path)
    if p.is_dir() and p.suffix.lower() != ".app":
        return look_in(host, p)
    if not p.exists():
        return False, _("{file} is not there", file=p)
    if p.name.lower() in [c.lower() for c in host.cli_names()] + [f"{c}.exe".lower() for c in host.cli_names()]:
        return choose_cli(host, p)
    if host.names_of(p) is None:
        note = " " + _("Its name is not one {app} has had: AI Remove uses it all the same.", app=host.name)
    else:
        note = ""
    found = [a for a, how in host.found_apps()]
    nxt = host.cli_next_to(p)
    if found and _same(found[0], p):
        _save_choice(host, app=None, cli=None)
        return True, _("{app}: the one installed, found by itself", app=host.name) + note
    _save_choice(host, app=p, cli=nxt)
    return True, (_("{app}: {file}, and its command line next to it", app=host.name, file=p) if nxt else
                  _("{app}: {file} (its command line is not next to it: choose it too)", app=host.name, file=p)) + note


def choose_cli(host, path):
    p = Path(path)
    if not p.is_file():
        return False, _("{file} is not there", file=p)
    nxt = host.cli_next_to(host.app()) if host.app() else None
    _save_choice(host, cli=None if _same(nxt, p) else p)
    return True, _("{app}'s command line: {file}", app=host.name, file=p)


def look_in(host, folder):
    """The app's program and command line searched for in a folder the user chose (system.find_programs)."""
    found = system.find_programs(host, folder)
    if not found:
        return False, _("{app} was not found in {dir} (looked for {names}, a few levels deep)", app=host.name,
                        dir=folder, names=", ".join(sorted({n.exe for n in host.names} | set(host.cli_names()))))
    if "app" in found:
        ok, msg = choose_program(host, found["app"])
        if found.get("cli") and not host.cli_next_to(found["app"]):
            choose_cli(host, found["cli"])
        return ok, msg
    return choose_cli(host, found["cli"])


def forget_choice(host):
    """Back to the program and command line found by themselves."""
    _save_choice(host, app=None, cli=None)
    return True, _("{app}: found by itself again", app=host.name)


def setup(host):
    """The installer's step 6 for this app (install.configure_lightcraft, without questions): its control port's
    variable, AI Remove as its external editor, the shortcut. Returns (state, message, the installer's lines): state
    'done' | 'pending' (the app must be closed first: its ui.json then) | 'first_run' | 'failed'."""
    ins = installer()
    d = system.ROOT
    cfg = ins.read_cfg(d)
    editor = cfg.get("editor") or str(ins.launcher_exe(d))
    if not Path(editor).exists():
        return "failed", _("AI Remove's program is not there ({file}): this copy was not installed by its installer, "
                           "run the installer instead", file=editor), []
    if not ins.configurable(host):
        return "failed", _("{app} was not found on this computer: choose its program first", app=host.name), []
    said, before = Said(), ins.out
    ins.out = said
    try:
        state, msg = ins.configure_lightcraft(d, cfg, editor, yes=True, host=host)
    except Exception as e:  # shown, never the window gone
        state, msg = "failed", f"{type(e).__name__}: {e}"
    finally:
        ins.out = before
    # the installer's own words point at the installer: here the next step is this window's button
    if state == "pending":
        msg = _("{app} is open and its external editor could not be set from here: close it, then press Set up "
                "again (its settings file is written while it is closed)", app=host.name)
    elif state == "first_run":
        msg = _("{app} has never been opened: open it once and close it (it makes its settings folder), then press "
                "Set up again", app=host.name)
    if state != "failed":
        # its variable is set for the programs started from now on: AI Remove's own process reads it as they will
        port = str(cfg.get(host.cfg_key("port")) or host.default_port)
        for v in host.own_vars("CONTROL_PORT"):
            os.environ[v] = port
        keep = {h.key for h in ins.default_apps(cfg)} | {host.key}  # the update keeps it set up
        cfg["apps"] = [h.key for h in system.HOSTS if h.key in keep]
    ins.write_cfg(d, cfg)
    return state, msg, said.lines


# ------------------------------------------------------------------------------------------------ the models
def models_state():
    """[{model, name, what, state, folders, gb}] for the models the installer offers; state "models" (in the models
    folder) | "yours" (some parts from a folder of the user's own: folders) | "app" (SAM 3: the app's, linked when
    used) | "missing"."""
    out = []
    for m, mod in mf.MODELS.items():
        if not mod.offered:
            continue
        state, mine = mf.where(m)
        app = None
        if m == "sam3" and state == "missing" and system.sam3_file(mf.SAM3_WEIGHTS):
            state, app = "app", system.sam3_host(mf.SAM3_WEIGHTS).name
        out.append({"model": m, "name": mod.name, "what": mod.what, "state": state, "folders": mine, "gb": mod.gb,
                    "app": app})
    return out


def models_dir_state():
    d = mf.models_dir()
    return {"dir": str(d), "default": _same(d, system.ROOT / "models"), "exists": d.is_dir(),
            "models": mf.models_in(d) if d.is_dir() else []}


def use_models_folder(folder):
    """The install's models folder: another one (folder), or None for <install>/models. (ok, message)."""
    mf.set_models_dir(folder)
    d = mf.models_dir()
    found = mf.models_in(d)
    return True, (_("Models folder: {dir} ({n} models there)", dir=d, n=len(found)) if found else
                  _("Models folder: {dir} — no model there yet: the installer downloads the ones you choose into it",
                    dir=d))


def use_model_folder(model, folder):
    found = mf.use_folder(model, folder)
    name = mf.MODELS[model].name
    if not found:
        return False, _("{model} was not found in {dir} (looked for {files}, a few levels deep)", model=name,
                        dir=folder, files=mf.looks_for(model))
    left = [p for p in mf.MODELS[model].parts if p not in found and not mf.PARTS[p].optional]
    return True, (_("{model}: used from {dir}", model=name, dir=folder) if not left else
                  _("{model}: used from {dir}; the rest ({parts}) from the models folder", model=name, dir=folder,
                    parts=", ".join(left)))


def forget_model_folder(model):
    mf.forget_folder(model)
    return True, _("{model}: from the models folder again", model=mf.MODELS[model].name)


# ------------------------------------------------------------------------------------------------ the window
HOW = {"chosen": N_("chosen by you"), "installed": N_("installed"), "flatpak": N_("Flatpak"),
       "running": N_("running now"), "env": N_("from {variable}"), "next": N_("next to the program"),
       "path": N_("on the PATH")}
MODEL_STATE = {"models": N_("in the models folder"), "yours": N_("from your folder"), "missing": N_("not installed"),
               "app": N_("{app}'s, linked when used")}

_OPEN = {}  # the window, while it is open (one per process)


def open_window(master=None, on_change=None):
    """The Settings window, over master (the window's or the panel's root); the one open comes forward instead."""
    w = _OPEN.get("w")
    if w is not None and w.alive():
        w.top.deiconify()
        w.top.lift()
        w.top.focus_force()
        return w
    w = _OPEN["w"] = Window(master, on_change)
    return w


def run():
    """airemove --settings: the window on its own."""
    w = Window(None, None)
    w.top.mainloop()
    return 0


class Window:
    def __init__(self, master, on_change):
        import tkinter as tk
        from tkinter import ttk
        import ui
        self.tk, self.ui, self.on_change = tk, ui, on_change
        self.own_root = master is None
        top = self.top = tk.Tk(className="airemove") if master is None else tk.Toplevel(master)
        self.k = k = max(1.0, top.winfo_fpixels("1i") / 96.0)
        win = sys.platform == "win32"
        fam = "Segoe UI" if win else ("Helvetica" if sys.platform == "darwin" else "TkDefaultFont")
        base = 9 if win else 11
        self.f_txt, self.f_small = (fam, base), (fam, base - 1)
        self.f_bold, self.f_head = (fam, base, "bold"), (fam, base - 2, "bold")
        self.f_title = (fam, base + 4, "bold")
        top.title(_("AI Remove — Settings"))
        top.configure(bg=ui.BG)
        top.minsize(int(560 * k), int(420 * k))
        top.geometry(f"{int(720 * k)}x{int(min(820 * k, top.winfo_screenheight() * 0.85))}")
        if master is not None:
            top.transient(master)
        try:
            self._icon = tk.PhotoImage(file=str(ui.ICON))
            top.iconphoto(False, self._icon)
        except (tk.TclError, OSError):
            pass
        st = ttk.Style(top)
        if master is None:  # its own root: the theme whose colours can be set (the window and the panel use it too)
            st.theme_use("clam")
        st.configure("AISettings.Vertical.TScrollbar", troughcolor=ui.BG, background="#3a3a3a", bordercolor=ui.BG,
                     arrowcolor=ui.DIM, lightcolor="#3a3a3a", darkcolor="#3a3a3a", gripcount=0)
        self.events, self.jobs = queue.Queue(), queue.Queue()
        self.apps, self.models, self.mdir, self.busy = {}, [], None, set()
        self.notes = {}  # app key / "models" -> (text, colour): what the last action said there
        self.closed = False
        self.build()
        top.protocol("WM_DELETE_WINDOW", self.close)
        top.bind("<Escape>", lambda e: self.close())
        # the wheel scrolls this window: bound on it (before the "all" tag, where the AI Remove window zooms)
        top.bind("<MouseWheel>", self.on_wheel)
        if not (win or sys.platform == "darwin"):
            top.bind("<Button-4>", lambda e: self.scroll(-3))
            top.bind("<Button-5>", lambda e: self.scroll(3))
        threading.Thread(target=self.worker, daemon=True).start()
        self.refresh()
        top.after(100, self.pump)
        ui.bring_to_front(top)

    def alive(self):
        return not self.closed

    # -------------------------------------------------------------- layout
    def button(self, master, text, cmd, accent=False, small=True):
        ui = self.ui
        bg, fg, hi = (ui.ACCENT, "#1b1b1b", ui.ACCENT_HI) if accent else (ui.BTN, ui.FG, ui.BTN_HI)
        b = self.tk.Button(master, text=text, command=cmd, relief="flat", bd=0, cursor="hand2",
                           font=self.f_bold if accent else (self.f_small if small else self.f_txt), bg=bg, fg=fg,
                           activebackground=hi, activeforeground=fg, disabledforeground=ui.OFF,
                           padx=int(9 * self.k), pady=int(3 * self.k))
        return b

    def label(self, master, text, fg=None, font=None, wrap=0, **kw):
        ui = self.ui
        return self.tk.Label(master, text=text, fg=fg or ui.FG, bg=kw.pop("bg", ui.CARD), font=font or self.f_txt,
                             anchor="w", justify="left", wraplength=wrap, **kw)

    def build(self):
        tk, ui, k = self.tk, self.ui, self.k
        from tkinter import ttk
        pad = int(16 * k)
        head = tk.Frame(self.top, bg=ui.BG)
        head.pack(fill="x", padx=pad, pady=(pad, int(4 * k)))
        self.label(head, _("Settings"), fg=ui.ACCENT, font=self.f_title, bg=ui.BG).pack(side="left")
        self.label(head, f"AI Remove {system.VERSION}", fg=ui.DIM, font=self.f_small, bg=ui.BG).pack(
            side="left", padx=(int(10 * k), 0), anchor="s")
        where = self.label(self.top, _("Every change is saved at once in {file}", file=system.CONFIG_FILE), fg=ui.DIM,
                           font=self.f_small, bg=ui.BG)
        where.pack(fill="x", padx=pad, pady=(0, int(4 * k)))
        where.bind("<Configure>", lambda e: where.configure(wraplength=max(100, e.width)))
        foot = tk.Frame(self.top, bg=ui.BG)
        foot.pack(side="bottom", fill="x", padx=pad, pady=(int(8 * k), pad))
        self.button(foot, _("Close"), self.close, small=False).pack(side="right")
        self.refresh_btn = self.button(foot, "⟳  " + _("Look again"), self.refresh, small=False)
        self.refresh_btn.pack(side="right", padx=(0, int(8 * k)))
        self.status = self.label(foot, "", fg=ui.DIM, font=self.f_small, bg=ui.BG)
        self.status.pack(side="left", fill="x", expand=True)
        body = tk.Frame(self.top, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=(pad, int(6 * k)))
        self.canvas = tk.Canvas(body, bg=ui.BG, highlightthickness=0, yscrollincrement=int(20 * k))
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview,
                           style="AISettings.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=ui.BG)
        self.win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win_id, width=e.width))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.draw()

    def on_wheel(self, e):
        if sys.platform == "darwin":
            self.scroll(-e.delta)
        else:
            self.scroll(-int(e.delta / 40))
        return "break"

    def scroll(self, n):
        self.canvas.yview_scroll(int(n), "units")

    def section(self, title):
        ui, k = self.ui, self.k
        self.label(self.inner, title.upper(), fg=ui.DIM, font=self.f_head, bg=ui.BG).pack(
            fill="x", pady=(int(14 * k), int(5 * k)))

    def card(self):
        tk, ui, k = self.tk, self.ui, self.k
        outer = tk.Frame(self.inner, bg=ui.LINE)
        outer.pack(fill="x", pady=(0, int(8 * k)), padx=(0, int(8 * k)))
        c = tk.Frame(outer, bg=ui.CARD)
        c.pack(fill="both", padx=1, pady=1)
        box = tk.Frame(c, bg=ui.CARD)
        box.pack(fill="x", padx=int(12 * k), pady=int(10 * k))
        box.columnconfigure(1, weight=1)
        return box

    def row(self, box, r, name, value, note="", note_fg=None, buttons=()):
        tk, ui, k = self.tk, self.ui, self.k
        self.label(box, name, fg=ui.DIM, font=self.f_small).grid(row=r, column=0, sticky="nw", padx=(0, int(12 * k)),
                                                                  pady=int(3 * k))
        cell = tk.Frame(box, bg=ui.CARD)
        cell.grid(row=r, column=1, sticky="ew", pady=int(3 * k))
        width = max(200, self.canvas.winfo_width() - int(330 * k)) if self.canvas.winfo_width() > 1 else int(380 * k)
        self.label(cell, value, wrap=width).pack(fill="x")
        if note:
            self.label(cell, note, fg=note_fg or ui.DIM, font=self.f_small, wrap=width).pack(fill="x")
        bf = tk.Frame(box, bg=ui.CARD)
        bf.grid(row=r, column=2, sticky="ne", pady=int(2 * k))
        for text, cmd in buttons:
            self.button(bf, text, cmd).pack(side="left", padx=(int(4 * k), 0))
        return cell

    def draw(self):
        """The window's content from the last state read (refresh)."""
        for w in self.inner.winfo_children():
            w.destroy()
        self.section(_("Apps"))
        for h in system.HOSTS:
            self.draw_app(h, self.apps.get(h.key))
        self.section(_("Models"))
        self.draw_models()
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def draw_app(self, h, a):
        tk, ui, k = self.tk, self.ui, self.k
        box = self.card()
        title = tk.Frame(box, bg=ui.CARD)
        title.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, int(6 * k)))
        self.label(title, h.name, font=self.f_bold).pack(side="left")
        if a is None:
            self.label(title, _("looking…"), fg=ui.DIM, font=self.f_small).pack(side="left", padx=(int(10 * k), 0))
            return
        if not a["app"] and not a["running"]:
            state, fg = _("not found on this computer"), ui.WARN
        elif a["answers"]:
            state, fg = _("open · answers on port {port}", port=a["port"]), ui.GREEN_HI
        elif a["running"]:
            state, fg = _("open · does not answer on port {port}", port=a["port"]), ui.WARN
        else:
            state, fg = _("closed"), ui.DIM
        self.label(title, "●  " + state, fg=fg, font=self.f_small).pack(side="left", padx=(int(10 * k), 0))
        busy = h.key in self.busy
        # the program and the command line
        how = a["app_how"]
        note = _(HOW[how], variable="") if how in HOW else ""
        if a["app"] and h.names_of(a["app"]) is not None:
            note += (" · " if note else "") + _("its program's name: {name}", name=h.names_of(a["app"]).exe)
        self.row(box, 1, _("Program"), a["app"] or _("not found"), note,
                 buttons=[(_("Change") + "  ▾", lambda b=None, h=h: self.program_menu(h))])
        cli_note = _(HOW[a["cli_how"]], variable=next((v for v in h.own_vars("CLI") if os.environ.get(v)), "")) \
            if a["cli_how"] in HOW else ""
        if not a["cli"]:
            cli_note = _("AI Remove reads a RAW opened on its own with it: without it, with the other app's")
        self.row(box, 2, _("Command line"), a["cli"] or _("not found"), cli_note,
                 buttons=[(_("Choose…"), lambda h=h: self.pick_cli(h))])
        # the control channel
        port_note = _("{variables} (read when {app} starts)", variables=", ".join(a["variables"]), app=h.name)
        port_fg = None
        if a["clash"]:
            port_note = _("{app} reads LightCraft's variable and wants port {port} too: only the first one opened "
                          "gets it. Set it up again to give it its own ({variable}), then restart it.",
                          app=h.name, port=a["port"], variable=a["variable"])
            port_fg = ui.WARN
        self.row(box, 3, _("Control channel"), _("port {port}", port=a["port"]), port_note, port_fg)
        # the external editor and the shortcut
        if a["editor_ours"]:
            ed, ed_fg = _("AI Remove (this installation)"), None
        elif a["editor"]:
            ed, ed_fg = _("another program: {file}", file=a["editor"]), ui.WARN
        else:
            ed, ed_fg = _("none"), ui.WARN
        key = installer().APP_KEY
        sc = (_("{key}: opens AI Remove", key=key) if a["shortcut"] and a["editor_ours"] else
              _("{key}: set, for another program", key=key) if a["shortcut"] else _("{key}: not set", key=key))
        self.row(box, 4, _("External editor"), ed, sc + ("" if a["answers"] else
                                                         " · " + _("as its settings file says ({file})",
                                                                   file=Path(a["settings"]) / "ui.json")),
                 ed_fg if ed_fg else (None if a["shortcut"] else ui.WARN))
        # set up again: the installer's own step 6
        act = tk.Frame(box, bg=ui.CARD)
        act.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(int(8 * k), 0))
        b = self.button(act, _("Set up again") if a["configured"] else _("Set up {app}", app=h.name),
                        lambda h=h: self.do("setup", h), accent=True)
        b.pack(side="left")
        if busy:
            b.configure(state="disabled", text=_("Setting up…"))
        self.label(act, _("the control port's variable, AI Remove as the external editor and {key}, as the "
                          "installer does", key=key), fg=ui.DIM, font=self.f_small,
                   wrap=int(420 * k)).pack(side="left", padx=(int(10 * k), 0))
        if h.key in self.notes:
            text, fg = self.notes[h.key]
            self.label(box, text, fg=fg, font=self.f_small, wrap=int(620 * k)).grid(
                row=6, column=0, columnspan=3, sticky="ew", pady=(int(6 * k), 0))

    def draw_models(self):
        tk, ui, k = self.tk, self.ui, self.k
        box = self.card()
        md = self.mdir
        if md is None:
            self.label(box, _("looking…"), fg=ui.DIM, font=self.f_small).grid(row=0, column=0, sticky="w")
            return
        note = (_("the installation's own") if md["default"] else _("chosen by you")) + " · " + (
            _("{n} models there", n=len(md["models"])) if md["exists"] else _("this folder is not there"))
        btns = [(_("Change…"), self.pick_models_dir)]
        if not md["default"]:
            btns.append((_("Default"), lambda: self.do("models_dir", None)))
        self.row(box, 0, _("Models folder"), md["dir"], note, None if md["exists"] else ui.WARN, btns)
        for i, m in enumerate(self.models, 1):
            if m["state"] == "yours":
                val = _(MODEL_STATE["yours"]) + ": " + ", ".join(sorted(set(m["folders"].values())))
            else:
                val = _(MODEL_STATE[m["state"]], app=m["app"] or "")
            btns = [(_("Use a folder…"), lambda m=m["model"]: self.pick_model_dir(m))]
            if m["state"] == "yours":
                btns.append((_("Models folder"), lambda m=m["model"]: self.do("forget_model", m)))
            self.row(box, i, m["name"], val, None, ui.WARN if m["state"] == "missing" else None, btns)
        tail = tk.Frame(box, bg=ui.CARD)
        tail.grid(row=len(self.models) + 1, column=0, columnspan=3, sticky="ew", pady=(int(8 * k), 0))
        self.label(tail, _("A model already loaded keeps its files until AI Remove is closed. A model not installed: "
                           "run the installer again (or the update) and choose it."), fg=ui.DIM, font=self.f_small,
                   wrap=int(640 * k)).pack(fill="x")
        if "models" in self.notes:
            text, fg = self.notes["models"]
            self.label(tail, text, fg=fg, font=self.f_small, wrap=int(640 * k)).pack(fill="x", pady=(int(4 * k), 0))

    # -------------------------------------------------------------- the user's choices
    def program_menu(self, h):
        """The programs found (installed, running), a file, a folder to search, or back to automatic."""
        tk, ui = self.tk, self.ui
        a = self.apps.get(h.key) or {}
        m = tk.Menu(self.top, tearoff=0, bg=ui.CARD, fg=ui.FG, activebackground=ui.ACCENT,
                    activeforeground="#1b1b1b", bd=0, relief="flat", font=self.f_small)
        for p, how in a.get("apps") or []:
            mark = "✓  " if _same(p, a.get("app")) else "     "
            m.add_command(label=f"{mark}{p}   ({_(HOW.get(how, how), variable='')})",
                          command=lambda p=p: self.do("program", h, p))
        if a.get("apps"):
            m.add_separator()
        m.add_command(label=_("Choose the program…"), command=lambda: self.pick_program(h))
        m.add_command(label=_("Look in a folder…"), command=lambda: self.pick_folder(h))
        if h.chosen():
            m.add_separator()
            m.add_command(label=_("Find it by itself again"), command=lambda: self.do("forget", h))
        x, y = self.top.winfo_pointerxy()
        m.tk_popup(x, y)

    def pick_program(self, h):
        from tkinter import filedialog
        if sys.platform == "darwin":  # an app is a folder there
            f = filedialog.askdirectory(parent=self.top, title=_("{app}'s app", app=h.name),
                                        initialdir="/Applications")
        else:
            types = [(_("Programs"), "*.exe"), (_("All files"), "*")] if sys.platform == "win32" else \
                [(_("All files"), "*")]
            f = filedialog.askopenfilename(parent=self.top, title=_("{app}'s program", app=h.name),
                                           initialdir=self.start_dir(h), filetypes=types)
        if f:
            self.do("program", h, f)

    def pick_cli(self, h):
        from tkinter import filedialog
        types = ([(_("Programs"), "*.exe"), (_("All files"), "*")] if sys.platform == "win32" else
                 [(_("All files"), "*")])
        f = filedialog.askopenfilename(parent=self.top, title=_("{app}'s command line", app=h.name),
                                       initialdir=self.start_dir(h), filetypes=types)
        if f:
            self.do("cli", h, f)

    def pick_folder(self, h):
        from tkinter import filedialog
        f = filedialog.askdirectory(parent=self.top, title=_("The folder {app} is in", app=h.name),
                                    initialdir=self.start_dir(h))
        if f:
            self.do("folder", h, f)

    def start_dir(self, h):
        a = (self.apps.get(h.key) or {}).get("app")
        if a and not a.startswith("flatpak:"):
            return str(Path(a).parent)
        return os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or str(Path.home())

    def pick_models_dir(self):
        from tkinter import filedialog, messagebox
        f = filedialog.askdirectory(parent=self.top, title=_("AI Remove's models folder"),
                                    initialdir=(self.mdir or {}).get("dir") or str(system.ROOT))
        if not f:
            return
        if not mf.models_in(f) and not messagebox.askyesno(
                "AI Remove", _("No model is in {dir} (as the models folder holds them: one folder per model's part). "
                               "Use it anyway? Until the models are there AI Remove has none of them.", dir=f),
                parent=self.top):
            return
        self.do("models_dir", f)

    def pick_model_dir(self, model):
        from tkinter import filedialog
        f = filedialog.askdirectory(parent=self.top, initialdir=str(Path.home()),
                                    title=_("A folder that holds {model}", model=mf.MODELS[model].name))
        if f:
            self.do("use_model", model, f)

    # -------------------------------------------------------------- work in a thread, results in the window
    def do(self, what, *args):
        h = args[0] if args and isinstance(args[0], system.Host) else None
        if h is not None:
            self.busy.add(h.key)
        self.status.configure(text=_("Working…"))
        self.jobs.put((what, args))
        if what == "setup":
            self.draw()

    def refresh(self):
        self.status.configure(text=_("Looking for the apps and the models…"))
        self.jobs.put(("refresh", ()))

    def worker(self):
        acts = {"program": choose_program, "cli": choose_cli, "folder": look_in, "forget": forget_choice,
                "models_dir": use_models_folder, "use_model": use_model_folder, "forget_model": forget_model_folder}
        while True:
            what, args = self.jobs.get()
            if what == "quit":
                return
            try:
                if what == "setup":
                    state, msg, lines = setup(args[0])
                    self.events.put(("note", args[0].key, state, msg, lines))
                elif what in acts:
                    ok, msg = acts[what](*args)
                    key = args[0].key if args and isinstance(args[0], system.Host) else "models"
                    self.events.put(("note", key, "done" if ok else "failed", msg, []))
                    self.events.put(("changed",))
                self.events.put(("state", {h.key: app_state(h) for h in system.HOSTS}, models_state(),
                                 models_dir_state()))
            except Exception as e:  # shown in the window, which stays
                import traceback
                traceback.print_exc()
                self.events.put(("error", f"{type(e).__name__}: {e}"))

    def pump(self):
        if self.closed:
            return
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "state":
                    self.apps, self.models, self.mdir = ev[1], ev[2], ev[3]
                    self.busy.clear()
                    self.status.configure(text="")
                    self.draw()
                elif ev[0] == "note":
                    __, key, state, msg, lines = ev
                    ui = self.ui
                    fg = {"done": ui.GREEN_HI, "failed": ui.WARN}.get(state, ui.ACCENT)
                    extra = [x for x in lines if x and x not in msg]
                    if state == "done" and key != "models" and system.host_named(key) is not None and \
                            system.host_named(key).running():
                        extra.append(_("Restart {app} if its control port was changed: it reads it when it starts",
                                       app=system.host_named(key).name))
                    self.notes[key] = ("\n".join([msg] + extra), fg)
                elif ev[0] == "changed":
                    if self.on_change:
                        try:
                            self.on_change()
                        except Exception:
                            pass
                elif ev[0] == "error":
                    self.busy.clear()
                    self.status.configure(text=ev[1], fg=self.ui.WARN)
        except queue.Empty:
            pass
        self.top.after(150, self.pump)

    def close(self):
        self.closed = True
        self.jobs.put(("quit", ()))
        _OPEN.pop("w", None)
        try:
            self.top.destroy()
        except self.tk.TclError:
            pass
