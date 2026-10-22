"""One PASS/FAIL check before an Ecoscribe install reaches the PC (dictado-n5r). Run with Windows Python.

    python release_gate.py <Ecoscribe-Setup-X.Y.Z.exe>             check only
    python release_gate.py <Ecoscribe-Setup-X.Y.Z.exe> --install   check, then install and wait for "ready"

Nothing is installed unless every line says PASS. The last lines always say plainly whether it was
installed and whether it runs now. Old installers are listed for a delete OK, never deleted here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home()))
DATA = LOCAL / "ecoscribe"
APPDIR = LOCAL / "Programs" / "Ecoscribe"
OUT = Path(os.environ.get("USERPROFILE", Path.home())) / "ecoscribe-build"
DOWNLOADS = Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"
FIX = APP / "tests" / "fixtures" / "en_long.wav"
ROOM = 3  # free disk must be this many times the installer


def app_version() -> str:
    ns = {}
    exec((APP / "ecoscribe" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def setup_version(setup: Path) -> str | None:
    m = re.fullmatch(r"Ecoscribe-Setup-(\d+(?:\.\d+)+)\.exe", setup.name)
    return m.group(1) if m else None


def pid_alive(pid) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True).stdout
        return str(int(pid)) in out
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def check_disk(setup: Path, free=None) -> tuple[bool, str]:
    size = setup.stat().st_size
    free = shutil.disk_usage(LOCAL).free if free is None else free
    ok = free >= ROOM * size
    return ok, f"{free / 1e9:.1f} GB free, needs {ROOM * size / 1e9:.1f} GB ({ROOM}x the {size / 1e9:.2f} GB installer)"


def check_no_meeting(path: Path = DATA / "meetings.json", alive=pid_alive) -> tuple[bool, str]:
    """No call recording, no transcript or speakers pass running, nothing queued.
    A meetings.json left by a crash (its process gone) doesn't block."""
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, "no meetings.json"
    m, j, q = st.get("meeting"), st.get("job"), st.get("queue") or []
    if m and alive(m.get("pid")):
        return False, "a call is being recorded"
    if j and alive(j.get("pid")):
        return False, f"a meeting is being processed ({j.get('kind') or 'transcript'})"
    if q:
        return False, f"{len(q)} meeting(s) wait to be processed"
    return True, "no call recording or processing"


def check_version(setup: Path) -> tuple[bool, str]:
    v, want = setup_version(setup), app_version()
    return v == want, f"installer {v or '?'}, this tree {want}"


def check_tests() -> tuple[bool, str]:
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not gpu and not win",
                        str(APP / "tests")], cwd=str(APP), capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or ["no output"])[-1]
    return r.returncode == 0, f"{tail} ({time.monotonic() - t0:.0f} s)"


def check_selftest(dist: Path = OUT / "dist" / "Ecoscribe") -> tuple[bool, str]:
    """The built app (before it's installed) loads CUDA from its own folder, with a clean PATH, and transcribes."""
    exe, out = dist / "Ecoscribe.exe", OUT / "selftest-gate.json"
    if not exe.exists():
        return False, f"no build at {exe}"
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = r"C:\Windows\System32;C:\Windows"
    out.unlink(missing_ok=True)
    subprocess.run([str(exe), "--selftest", str(FIX), "--out", str(out)], env=env, timeout=240)
    try:
        d = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "selftest wrote no result"
    ok = d.get("ok") and d.get("device") == "cuda" and "climbing session" in d.get("text", "")
    return bool(ok), f"device {d.get('device')}, {d.get('ms')} ms" + ("" if ok else f", {d.get('error') or d.get('text')}")


def old_installers(keep: Path) -> list[Path]:
    found = {p.resolve() for d in (OUT, DOWNLOADS) if d.is_dir() for p in d.glob("Ecoscribe-Setup-*.exe")}
    return sorted((p for p in found if p.name != keep.name),
                  key=lambda p: tuple(int(x) for x in (setup_version(p) or "0").split(".")))


def status() -> dict:
    try:
        return json.loads((DATA / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def install(setup: Path, version: str) -> tuple[bool, dict]:
    t0 = time.time()
    log = Path(os.environ.get("TEMP", OUT)) / f"ecoscribe-install-{version}.log"
    r = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=startup", f"/LOG={log}"],
                       timeout=900)
    end = time.time() + 180
    s = {}
    while r.returncode == 0 and time.time() < end:
        s = status()
        if s.get("state") == "ready" and s.get("version") == version and s.get("ts", 0) > t0:
            return True, s
        time.sleep(1)
    return False, s or {"installer exit code": r.returncode}


def run(setup: Path, do_install: bool) -> int:
    checks = [("disk room", lambda: check_disk(setup)),
              ("no meeting live", check_no_meeting),
              ("version", lambda: check_version(setup)),
              ("unit tests", check_tests),
              ("built app selftest", check_selftest)]
    failed = []
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as e:  # a check that crashes is a FAIL, never a silent pass
            ok, detail = False, f"{type(e).__name__}: {e}"
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)
        if not ok:
            failed.append(name)
    old = old_installers(setup)
    if old:
        print(f"\nOld installers ({sum(p.stat().st_size for p in old) / 1e9:.1f} GB), delete with Erik's OK:")
        for p in old:
            print(f"  {p}")
    version = setup_version(setup) or "?"
    when = time.strftime("%H:%M")
    if failed:
        print(f"\nGATE FAIL: {', '.join(failed)}")
        print(f"Installed: no, {version} not installed because of {', '.join(failed)}")
        s = status()
        print(f"Running now: {'yes, ' + str(s.get('version')) if s.get('state') == 'ready' else 'no'}")
        return 1
    print("\nGATE PASS")
    if not do_install:
        return 0
    ok, s = install(setup, version)
    print(f"Installed: {'yes' if ok else 'no'}, {version}, {when}")
    print(f"Running now: {'yes' if s.get('state') == 'ready' else 'no'}")
    print(f"Checked by: status.json says {s.get('state')} on {s.get('device')}, version {s.get('version')}")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.exit(run(Path(args[0]).resolve(), "--install" in sys.argv))
