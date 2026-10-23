"""Build Ecoscribe.exe, the installer and the GPU runtime pack. Run with Windows Python.

    python build.py              -> <out>\\dist\\Ecoscribe\\Ecoscribe.exe (no CUDA DLLs in it: dictado-7e1)
    python build.py --installer  -> also the GPU runtime pack and Ecoscribe-Setup-<ver>.exe, in the build folder
                                    only (the GitHub release carries it; no copy in Downloads, dictado-38z)
    python build.py --installer --install  -> then the release gate (tools/release_gate.py) and, only
                                               when every check passes, the install on this PC
    python build.py --runtime    -> only the GPU runtime pack: ecoscribe-gpu-runtime-<N>.zip, checked
                                    against ecoscribe/gpu_runtime.json (upload it once, see release steps)
    python build.py --new-runtime -> the CUDA DLLs changed: the next pack version and a new manifest

<out> is %USERPROFILE%\\ecoscribe-build unless --out names another folder (a trial build next to the
real one).

GPU runtime release (once per runtime version, before the first installer that needs it goes out; the
release gate fails "GPU runtime published" until it is done):
    python build.py --runtime                       # <out>\\ecoscribe-gpu-runtime-<N>.zip, sha256 checked
    gh release create gpu-runtime-<N> <out>\\ecoscribe-gpu-runtime-<N>.zip -R ErikBros/ecoscribe \\
        --latest=false --title "GPU runtime <N>" --notes "CUDA libraries for Ecoscribe (downloaded by the app)"
The app's releases (v1.x.y) carry only the small installer from then on.
"""
from __future__ import annotations

import argparse
import os
import site
import subprocess
import sys
from pathlib import Path

import runtime_pack

APP = Path(__file__).resolve().parent.parent
PKG = APP / "packaging" / "windows"
OUT = Path(os.environ.get("USERPROFILE", Path.home())) / "ecoscribe-build"
ISCC = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Inno Setup 6" / "ISCC.exe"


def version() -> str:
    ns = {}
    exec((APP / "ecoscribe" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def freeze() -> Path:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--distpath", str(OUT / "dist"), "--workpath", str(OUT / "work"), str(PKG / "ecoscribe.spec")]
    subprocess.run(cmd, check=True, cwd=str(OUT))
    exe = OUT / "dist" / "Ecoscribe" / "Ecoscribe.exe"
    size = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    print(f"built {exe}  ({size / 1e9:.2f} GB)")
    m = runtime_pack.load()
    stray = runtime_pack.bundled(exe.parent, m) if m else []
    if stray:  # the split is the point: an installer with cuBLAS in it is 450 MB bigger
        raise SystemExit(f"CUDA DLLs ended up in the app ({', '.join(stray)}): they belong in the GPU runtime pack")
    return exe


def runtime(new: bool = False) -> Path:
    zp, m = runtime_pack.build(Path(site.getsitepackages()[-1]), OUT, new=new)
    print(f"GPU runtime {m['version']}: {zp}  ({m['size'] / 1e6:.0f} MB) -> release {runtime_pack.tag(m['version'])}")
    return zp


def installer() -> Path:
    v = version()
    subprocess.run([str(ISCC), f"/DAppVersion={v}", f"/DDistDir={OUT / 'dist' / 'Ecoscribe'}",
                    f"/O{OUT}", str(PKG / "ecoscribe.iss")], check=True)
    setup = OUT / f"Ecoscribe-Setup-{v}.exe"
    print(f"installer {setup}  ({setup.stat().st_size / 1e6:.0f} MB)")
    return setup


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true")
    ap.add_argument("--skip-freeze", action="store_true")
    ap.add_argument("--install", action="store_true", help="release gate, then install (needs --installer)")
    ap.add_argument("--out", type=Path, help="build folder (default %%USERPROFILE%%\\ecoscribe-build)")
    ap.add_argument("--runtime", action="store_true", help="only the GPU runtime pack")
    ap.add_argument("--new-runtime", action="store_true", help="the CUDA DLLs changed: next pack version + manifest")
    a = ap.parse_args()
    if a.out:
        OUT = a.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.runtime or a.new_runtime:
        runtime(new=a.new_runtime)
        raise SystemExit(0)
    if not a.skip_freeze:
        freeze()
    if a.installer:
        runtime()  # the gate's selftest runs the app on this pack
    setup = installer() if a.installer else None
    if a.install:
        if setup is None:
            raise SystemExit("--install needs --installer")
        import release_gate
        raise SystemExit(release_gate.run(setup, do_install=True))
