"""PyTorch's CUDA build for the NVIDIA card (#58), and an AMD card PyTorch has no code for, without either card:
tools/ci_smoke.py check runs this.

Since 2.8, PyTorch's build for CUDA 12.8 has no code for NVIDIA cards before Turing (GTX 10 series and older): they
failed at their first use with "no kernel image is available for execution on the device". Checked here:
- system.cuda_has_code, from a card's compute capability and a build's architecture list: the 12.8 build has no
  code for a GTX 1060 or a TITAN V and has some for RTX 20 to 50 cards; the 12.6 build has some for a GTX 970 or a
  GTX 1060 and none for an RTX 50 card; PTX (compute_XY) serves later cards; an empty list cannot tell.
- system.rocm_has_code: AMD's build for Windows (its list, as an RX 7800 XT install has it) runs on RX 7000 / 9000
  and Ryzen AI graphics, not on an RX 6600; a card with features in its name; HSA_OVERRIDE_GFX_VERSION trusted.
- install.nvidia_capability reads nvidia-smi; install.cuda_build: the 12.6 build below 7.5, else 12.8, and by name
  when the driver cannot give the capability (laptop names too, and no Turing card taken for an older one).
- install.make_venv, with uv and Python stood in for: a new install takes the build's index; an update with the
  12.8 build on an older card replaces it (--reinstall-package) from the 12.6 index; one with the right build keeps
  it; a build that still has no code for the card is swapped for the other, once, then the processor; an AMD card
  on Linux PyTorch has no code for: the processor at once, nothing reinstalled.
Exit status 1 at the first check that fails.
"""
import shutil
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
CU128 = ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]  # torch 2.9.1+cu128 (Windows)
CU126 = ["sm_50", "sm_60", "sm_61", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]  # torch 2.9.1+cu126
ROCM_WIN = ["gfx1100", "gfx1201", "gfx1151", "gfx1150", "gfx1200", "gfx1101", "gfx1102"]  # torch 2.9.1+rocm7.2.1


class Failed(Exception):
    pass


def expect(ok, what):
    if not ok:
        raise Failed(what)
    print("  ok  " + what)


def has_code():
    cases = [((6, 1), CU128, False, "GTX 1060 on the 12.8 build"), ((7, 0), CU128, False, "TITAN V on the 12.8 build"),
             ((7, 5), CU128, True, "RTX 2060 on the 12.8 build"), ((8, 9), CU128, True, "RTX 4090 on the 12.8 build"),
             ((12, 0), CU128, True, "RTX 5070 on the 12.8 build"), ((6, 1), CU126, True, "GTX 1060 on the 12.6 build"),
             ((5, 2), CU126, True, "GTX 970 on the 12.6 build"), ((12, 0), CU126, False, "RTX 5070 on the 12.6 build"),
             ((12, 0), ["sm_80", "compute_90"], True, "a later card through PTX"),
             ((3, 5), CU126, False, "a Kepler card on the 12.6 build"), ((8, 6), [], True, "no list: cannot tell")]
    for cap, archs, want, what in cases:
        expect(system.cuda_has_code(cap, archs) is want, f"cuda_has_code: {what}: {want}")
    cases = [("gfx1101", ROCM_WIN, None, True, "RX 7800 XT on AMD's Windows build"),
             ("gfx1201", ROCM_WIN, None, True, "RX 9070 on AMD's Windows build"),
             ("gfx1151", ROCM_WIN, None, True, "Ryzen AI Max graphics on AMD's Windows build"),
             ("gfx1032", ROCM_WIN, None, False, "RX 6600 on AMD's Windows build"),
             ("gfx1032", ROCM_WIN, "10.3.0", True, "RX 6600 with HSA_OVERRIDE_GFX_VERSION: trusted"),
             ("gfx90a:sramecc+:xnack-", ["gfx90a", "gfx942"], None, True, "a card with features in its name"),
             ("", ROCM_WIN, None, True, "no name: cannot tell"), ("gfx1103", [], None, True, "no list: cannot tell")]
    for gfx, archs, override, want, what in cases:
        expect(system.rocm_has_code(gfx, archs, override) is want, f"rocm_has_code: {what}: {want}")


def builds():
    which, output, cap = shutil.which, install.output, install.nvidia_capability
    try:
        shutil.which = lambda name: "nvidia-smi" if name == "nvidia-smi" else which(name)
        install.output = lambda cmd, timeout=30: "6.1\n8.6\n" if "--query-gpu=compute_cap" in cmd else ""
        expect(install.nvidia_capability() == 6.1, "nvidia_capability: the first card's, from nvidia-smi")
        install.output = lambda cmd, timeout=30: "Field \"compute_cap\" is not a valid field to query.\n"
        expect(install.nvidia_capability() is None, "nvidia_capability: None from an older driver")
        shutil.which = lambda name: None
        expect(install.nvidia_capability() is None, "nvidia_capability: None without nvidia-smi")
        for c, want in ((6.1, "cu126"), (7.0, "cu126"), (5.2, "cu126"), (7.5, "cu128"), (8.6, "cu128"),
                        (12.0, "cu128")):
            install.nvidia_capability = lambda c=c: c
            expect(install.cuda_build(("nvidia", "any", 8)) == want, f"cuda_build: capability {c} -> {want}")
        install.nvidia_capability = lambda: None
        old = ["NVIDIA GeForce GTX 1060 6GB", "NVIDIA GeForce GTX 1050 Ti with Max-Q Design", "NVIDIA GeForce GTX 980M",
               "NVIDIA GeForce GTX 750 Ti", "NVIDIA GeForce 940MX", "NVIDIA GeForce MX150", "NVIDIA TITAN Xp",
               "NVIDIA TITAN V", "NVIDIA GeForce GTX TITAN X", "Quadro P2000", "Tesla V100-PCIE-16GB"]
        new = ["NVIDIA GeForce GTX 1660 SUPER", "NVIDIA GeForce GTX 1650", "NVIDIA GeForce RTX 2060",
               "NVIDIA GeForce RTX 3060 Laptop GPU", "NVIDIA GeForce RTX 5070", "NVIDIA TITAN RTX",
               "NVIDIA GeForce MX450", "Quadro RTX 4000", "Tesla T4", "NVIDIA RTX A2000"]
        bad = [n for n in old if install.cuda_build(("nvidia", n, 6)) != "cu126"]
        expect(not bad, f"cuda_build by name: the 12.6 build for {len(old)} cards before Turing"
                        + (f": not {bad}" if bad else ""))
        bad = [n for n in new if install.cuda_build(("nvidia", n, 8)) != "cu128"]
        expect(not bad, f"cuda_build by name: the 12.8 build for {len(new)} Turing and later cards"
                        + (f": not {bad}" if bad else ""))
        expect(install.cuda_build(None) == "cu128", "cuda_build without a card's name: the 12.8 build")
    finally:
        shutil.which, install.output, install.nvidia_capability = which, output, cap


class Venv:
    """uv and the venv's Python, stood in for: what make_venv asked, and the PyTorch it leaves."""

    def __init__(self, d, cuda=None, archs_ok=("12.6",)):
        self.d, self.cuda, self.archs_ok, self.cmds = d, cuda, archs_ok, []
        py = install.venv_python(d)
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("")

    def run(self, cmd, env=None, check=True, quiet=False, cwd=None):
        cmd = [str(c) for c in cmd]
        if "-c" in cmd:
            code = cmd[cmd.index("-c") + 1]
            if "gpu_summary" in code:
                if self.cuda in self.archs_ok:
                    return 0, "DEVICE cuda NVIDIA GeForce GTX 1060 (CUDA, 6 GB)\n"
                return 0, (f"DEVICE cpu processor (8 cores): this PyTorch (CUDA {self.cuda}) {system.NO_GPU_CODE} "
                           f"NVIDIA GeForce GTX 1060, run the installer again\n")
            if "torch.version.cuda" in code:
                return 0, f"{self.cuda or ''}\n"
            if "import torch" in code:
                return (0 if self.cuda else 1), ""
            return 0, ""
        self.cmds.append(cmd)
        if any(c.startswith("torch") for c in cmd) and "--extra-index-url" in cmd:
            self.cuda = {"cu126": "12.6", "cu128": "12.8"}[cmd[cmd.index("--extra-index-url") + 1].rsplit("/", 1)[1]]
        return 0, ""

    def torch_cmds(self):
        return [c for c in self.cmds if any(a.startswith("torch==") for a in c)]


def venv():
    run, uv, launcher, os_ = install.run, install.uv_exe, install.make_launcher_pkg, system.system
    try:
        install.uv_exe = lambda: "uv"
        install.make_launcher_pkg = lambda d: d / "launcher"
        system.system = lambda: "windows"
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            v = Venv(d / "new")
            install.run = v.run
            dev = install.make_venv(v.d, "cuda", build="cu126")
            tc = v.torch_cmds()
            expect(len(tc) == 1 and "https://download.pytorch.org/whl/cu126" in tc[0]
                   and "--reinstall-package" not in tc[0] and dev == "cuda",
                   "a new install on an older card: PyTorch from the CUDA 12.6 index, the card used")

            v = Venv(d / "update", cuda="12.8")
            install.run = v.run
            dev = install.make_venv(v.d, "cuda", build="cu126")
            tc = v.torch_cmds()
            expect(len(tc) == 1 and "https://download.pytorch.org/whl/cu126" in tc[0]
                   and tc[0].count("--reinstall-package") == 2 and dev == "cuda",
                   "an update with the 12.8 build on an older card: replaced from the 12.6 index (#58)")

            v = Venv(d / "kept", cuda="12.6")
            install.run = v.run
            dev = install.make_venv(v.d, "cuda", build="cu126")
            expect(not v.torch_cmds() and dev == "cuda", "an update with the right build: PyTorch kept")

            v = Venv(d / "new-card", cuda="12.6", archs_ok=("12.8",))
            install.run = v.run
            dev = install.make_venv(v.d, "cuda", build="cu128")
            tc = v.torch_cmds()
            expect(len(tc) == 1 and "https://download.pytorch.org/whl/cu128" in tc[0]
                   and "--reinstall-package" in tc[0] and dev == "cuda",
                   "an RTX 50 card where the 12.6 build was: replaced by the 12.8 one")

            v = Venv(d / "misread")
            install.run = v.run
            dev = install.make_venv(v.d, "cuda", build="cu128")
            tc = v.torch_cmds()
            expect(len(tc) == 2 and "whl/cu128" in tc[0][tc[0].index("--extra-index-url") + 1]
                   and "whl/cu126" in tc[1][tc[1].index("--extra-index-url") + 1] and dev == "cuda",
                   "a card taken for a newer one: its build has no code for it, the other one is installed")

            v = Venv(d / "none", archs_ok=())
            install.run = v.run
            dev = install.make_venv(v.d, "cuda", build="cu128")
            expect(len(v.torch_cmds()) == 2 and dev == "cpu",
                   "no build has code for the card: both tried once, then the processor")

            v = Venv(d / "amd", cuda="ROCm", archs_ok=())
            install.run = v.run
            dev = install.make_venv(v.d, "rocm")
            expect(not v.torch_cmds() and dev == "cpu",
                   "an AMD card on Linux PyTorch has no code for: the processor, nothing reinstalled")
    finally:
        install.run, install.uv_exe, install.make_launcher_pkg, system.system = run, uv, launcher, os_


def main():
    try:
        has_code()
        builds()
        venv()
    except Failed as e:
        print("  FAIL " + str(e))
        return 1
    print("cuda build: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
