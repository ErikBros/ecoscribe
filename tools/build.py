"""Build Ecoscribe.exe (and optionally the installer). Run with Windows Python.

    python build.py              -> %USERPROFILE%\\ecoscribe-build\\dist\\Ecoscribe\\Ecoscribe.exe
    python build.py --installer  -> also Ecoscribe-Setup-<ver>.exe, in the build folder only (the GitHub
                                    release carries it; no 0.5 GB copy in Downloads, dictado-38z)
    python build.py --installer --install  -> then the release gate (tools/release_gate.py) and, only
                                               when every check passes, the install on this PC
"""
from __future__ import annotations

import argparse
import os
import site
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
PKG = APP / "packaging" / "windows"
OUT = Path(os.environ["USERPROFILE"]) / "ecoscribe-build"
ISCC = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"


def version() -> str:
    ns = {}
    exec((APP / "ecoscribe" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def freeze() -> Path:
    env = dict(os.environ, ECOSCRIBE_SITE=site.getsitepackages()[-1])
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--distpath", str(OUT / "dist"), "--workpath", str(OUT / "work"), str(PKG / "ecoscribe.spec")]
    subprocess.run(cmd, check=True, env=env, cwd=str(OUT))
    exe = OUT / "dist" / "Ecoscribe" / "Ecoscribe.exe"
    size = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    print(f"built {exe}  ({size / 1e9:.2f} GB)")
    return exe


def installer() -> Path:
    v = version()
    subprocess.run([str(ISCC), f"/DAppVersion={v}", f"/DDistDir={OUT / 'dist' / 'Ecoscribe'}",
                    f"/O{OUT}", str(PKG / "ecoscribe.iss")], check=True)
    setup = OUT / f"Ecoscribe-Setup-{v}.exe"
    print(f"installer {setup}  ({setup.stat().st_size / 1e9:.2f} GB)")
    return setup


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true")
    ap.add_argument("--skip-freeze", action="store_true")
    ap.add_argument("--install", action="store_true", help="release gate, then install (needs --installer)")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if not a.skip_freeze:
        freeze()
    setup = installer() if a.installer else None
    if a.install:
        if setup is None:
            raise SystemExit("--install needs --installer")
        import release_gate
        raise SystemExit(release_gate.run(setup, do_install=True))
