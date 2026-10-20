"""install-status.json read while the installer writes it, for the CI runners (.github/workflows/ci.yml): needs only
this checkout, runs before the install.

On Windows a program that has the file open makes the installer's replace of it fail (PermissionError, WinError 5;
opening it with FILE_SHARE_DELETE does not help). On 2026-10-20 that stopped an install at step 2/7 with a traceback: a
Get-Content poll was reading the file at that moment. With installer/install.py's Out and the MCP server's read_json,
in this process:
- a thread opens the file and holds it a moment, over and over (a fast poll), while Out.status() writes it 200 times:
  no write raises; on Windows the replace was refused at least once (the check met the race; where a rename replaces
  open files, macOS and Linux, it cannot happen); once the thread stops, the next status is in the file;
- the file kept open throughout: Out.status() gives up within a second without raising, the next one after the file
  is closed is in it;
- read_json reads the file over and over while a thread writes it with Out.status(): never None, never half a file,
  nothing raised in the thread.
Exit status 1 at the first check that fails. Standard library only.

  ci_status.py
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "installer"))
sys.path.insert(0, str(ROOT / "mcp"))
import install  # noqa: E402  (prints nothing on import)
import airemove_mcp  # noqa: E402

WIN = sys.platform == "win32"
WRITES = 200


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok   " + what, flush=True)


class Replaces:
    """os.replace, counted: how many went through, how many a reader refused."""

    def __init__(self):
        self.done = self.refused = 0
        self.real = os.replace

    def __call__(self, src, dst):
        try:
            self.real(src, dst)
        except PermissionError:
            self.refused += 1
            raise
        self.done += 1

    def __enter__(self):
        os.replace = self
        return self

    def __exit__(self, *exc):
        os.replace = self.real


def state(p):
    return json.loads(p.read_text(encoding="utf-8"))["message"]


def poll(p, stop, hold=0.002, gap=0.008):
    """Open p and hold it, over and over until stop: a Get-Content poll, much faster."""
    while not stop.is_set():
        try:
            with open(p, "rb") as f:
                f.read()
                time.sleep(hold)
        except OSError:
            pass
        time.sleep(gap)


def brief_readers(out, p):
    stop = threading.Event()
    reader = threading.Thread(target=poll, args=(p, stop), daemon=True)
    with Replaces() as rep:
        reader.start()
        t0 = time.monotonic()
        try:
            for i in range(WRITES):
                out.status("running", f"write {i}")
        except OSError as e:
            raise Failed(f"Out.status() raised while a reader had the file open: {type(e).__name__}: {e}")
        finally:
            stop.set()
            reader.join()
        dt = time.monotonic() - t0
    print(f"  ok   {WRITES} status writes while a thread kept reading the file: none raised ({dt:.1f} s; "
          f"{rep.refused} replaces refused by the reader, {WRITES - rep.done} writes left to the next one)", flush=True)
    if WIN:
        expect(rep.refused > 0, "on Windows the reader did refuse replaces (the check met the race)")
    out.status("running", "after the reader")
    expect(state(p) == "after the reader", "with the reader gone, the next status is in the file")


def held_open(out, p):
    with open(p, "rb"):
        t0 = time.monotonic()
        try:
            out.status("running", "while held")
        except OSError as e:
            raise Failed(f"Out.status() raised with the file held open: {type(e).__name__}: {e}")
        dt = time.monotonic() - t0
        expect(dt < 2, f"with the file held open, Out.status() returned after {dt:.2f} s without raising")
    out.status("running", "after closing")
    expect(state(p) == "after closing", "once the file is closed, the next status is in it")


def mcp_reads(out, p):
    stop, errors = threading.Event(), []

    def writer():
        i = 0
        try:
            while not stop.is_set():
                out.status("running", f"write {i}")
                i += 1
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=writer, daemon=True)
    plain, bad = [], 0
    t.start()
    try:
        for __ in range(500):
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                plain.append(type(e).__name__)
            st = airemove_mcp.read_json(p)
            if not (isinstance(st, dict) and st.get("state") == "running"):
                bad += 1
            time.sleep(0.002)
    finally:
        stop.set()
        t.join()
    expect(not errors, "the writer thread raised nothing" + (f" ({errors[0]!r})" if errors else ""))
    why = f": {', '.join(sorted(set(plain)))}" if plain else ""
    expect(bad == 0, f"read_json read the status 500 times while it was being written: {bad} misses "
                     f"(a single plain read failed {len(plain)} times{why})")


def main():
    print(f"status writes and reads ({sys.platform}, Python {sys.version.split()[0]})", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        out = install.Out()
        out.attach(Path(tmp))
        p = out.status_file
        out.status("running", "first")
        try:
            brief_readers(out, p)
            held_open(out, p)
            mcp_reads(out, p)
        except Failed as e:
            print("  FAIL " + str(e), flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
