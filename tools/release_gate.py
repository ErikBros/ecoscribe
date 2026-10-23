"""One PASS/FAIL check before an Ecoscribe install reaches the PC (dictado-n5r). Run with Windows Python.

    python release_gate.py <Ecoscribe-Setup-X.Y.Z.exe>             check only
    python release_gate.py <Ecoscribe-Setup-X.Y.Z.exe> --install   check, then install and wait for "ready"

The build folder is the installer's folder (dist\\Ecoscribe and the GPU runtime pack are next to it).
Nothing is installed unless every line says PASS. The last lines always say plainly whether it was
installed and whether it runs now. Old installers are listed for a delete OK, never deleted here.

GPU runtime pack (dictado-7e1): the app has no CUDA DLLs; the gate checks the pack matches the manifest,
is published where the app downloads it, and that the built app runs on the GPU with only the pack.
After the install it waits for the app to have the runtime and runs the installed app's GPU selftest.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from ecoscribe import gpu_runtime  # noqa: E402
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


def check_disk(setup: Path, free=None, runtime: int = 0) -> tuple[bool, str]:
    """runtime: bytes the GPU runtime still needs on this PC (zip + unpacked), 0 when it is there."""
    size = setup.stat().st_size
    free = shutil.disk_usage(LOCAL).free if free is None else free
    need = ROOM * size + runtime
    ok = free >= need
    extra = f" + {runtime / 1e9:.1f} GB GPU runtime" if runtime else ""
    return ok, f"{free / 1e9:.1f} GB free, needs {need / 1e9:.1f} GB ({ROOM}x the {size / 1e9:.2f} GB installer{extra})"


def runtime_need(m: dict | None, data: Path | None = None) -> int:
    if not m or gpu_runtime.installed(data or DATA, m):
        return 0
    return int(m["size"]) + gpu_runtime.unpacked_bytes(m)


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


def selftest(exe: Path, out: Path, runtime: Path | None = None, run=subprocess.run) -> dict:
    """Run `exe --selftest` with a clean PATH (nothing CUDA from this PC's tools), its JSON result or {}.
    runtime: the GPU runtime folder to hand it (ECOSCRIBE_GPU_RUNTIME); None: the one it finds itself."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", gpu_runtime.ENV_DIR)}
    env["PATH"] = r"C:\Windows\System32;C:\Windows"
    if runtime is not None:
        env[gpu_runtime.ENV_DIR] = str(runtime)
    Path(out).unlink(missing_ok=True)
    run([str(exe), "--selftest", str(FIX), "--out", str(out)], env=env, timeout=240)
    try:
        return json.loads(Path(out).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def judge_selftest(d: dict, runtime: Path | None) -> tuple[bool, str]:
    """On the GPU, heard the fixture, and cuBLAS came from the runtime pack (not from anywhere else)."""
    if not d:
        return False, "selftest wrote no result"
    ok = bool(d.get("ok")) and d.get("device") == "cuda" and "climbing session" in d.get("text", "")
    where = d.get("gpu_runtime")
    if runtime is not None and (not where or Path(where).resolve() != Path(runtime).resolve()):
        ok = False
    if "cublas64_12.dll" not in (d.get("nvidia_dlls") or []):
        ok = False
    detail = f"device {d.get('device')}, {d.get('ms')} ms, CUDA from {where or 'nowhere'}"
    return ok, detail + ("" if ok else f", {d.get('error') or d.get('text')}")


def check_split(dist: Path | None = None, m: dict | None = None) -> tuple[bool, str]:
    """The built app carries no CUDA DLL of the pack: that is what keeps the installer small."""
    import runtime_pack
    dist = dist or OUT / "dist" / "Ecoscribe"
    m = m or gpu_runtime.manifest()
    if not m:
        return False, "no ecoscribe/gpu_runtime.json"
    if not dist.is_dir():
        return False, f"no build at {dist}"
    stray = runtime_pack.bundled(dist, m)
    return not stray, "no CUDA DLLs in the app" if not stray else f"in the app: {', '.join(stray)}"


def runtime_zip(m: dict) -> Path:
    return OUT / m["asset"]


def check_runtime_pack(m: dict | None = None) -> tuple[bool, str]:
    """The pack next to the installer is byte for byte the one the app's manifest names."""
    import runtime_pack
    m = m or gpu_runtime.manifest()
    if not m:
        return False, "no ecoscribe/gpu_runtime.json"
    zp = runtime_zip(m)
    if not zp.exists():
        return False, f"no {zp.name} in {OUT} (tools/build.py --runtime)"
    if zp.stat().st_size != m["size"] or runtime_pack.sha256(zp) != m["sha256"]:
        return False, f"{zp.name} differs from the manifest (size or sha256)"
    return True, f"{zp.name}, {m['size'] / 1e6:.0f} MB, matches version {m['version']}"


def published_size(url: str, opener=urllib.request.urlopen) -> int | None:
    """The size of the file at `url` (one byte asked for, the total read from Content-Range), None if it isn't there."""
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0", "User-Agent": "Ecoscribe-gate"})
    try:
        with opener(req, timeout=30) as r:
            rng = r.headers.get("Content-Range") or ""
            if "/" in rng:
                return int(rng.rsplit("/", 1)[1])
            n = r.headers.get("Content-Length")
            return int(n) if n is not None else None
    except Exception:
        return None


def check_runtime_published(m: dict | None = None, opener=urllib.request.urlopen) -> tuple[bool, str]:
    """Every PC without the runtime downloads it from the manifest's URL: it must be there before an
    installer that needs it goes out."""
    import runtime_pack
    m = m or gpu_runtime.manifest()
    if not m:
        return False, "no ecoscribe/gpu_runtime.json"
    size = published_size(m["url"], opener)
    if size == m["size"]:
        return True, f"release {runtime_pack.tag(m['version'])} has {m['asset']}"
    what = "missing" if size is None else f"{size} bytes, not {m['size']}"
    return False, (f"{m['asset']} {what} at {m['url']}: upload it once, see 'GPU runtime release' in "
                   "tools/build.py")


def check_selftest(dist: Path | None = None, m: dict | None = None) -> tuple[bool, str]:
    """The built app (before it's installed), with a clean PATH and only the GPU runtime pack unpacked
    next to the build, loads CUDA from the pack and transcribes on the GPU."""
    dist = dist or OUT / "dist" / "Ecoscribe"
    exe = dist / "Ecoscribe.exe"
    if not exe.exists():
        return False, f"no build at {exe}"
    m = m or gpu_runtime.manifest()
    if not m:
        return False, "no ecoscribe/gpu_runtime.json"
    data = OUT / "gate-runtime"
    rt = gpu_runtime.folder(data, m)
    if gpu_runtime.check(rt, m, full=True) is not None:
        zp = runtime_zip(m)
        if not zp.exists():
            return False, f"no {zp.name} to run the selftest with"
        rt = gpu_runtime.unpack(zp, data, m)
    return judge_selftest(selftest(exe, OUT / "selftest-gate.json", runtime=rt), rt)


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


def wait_runtime(m: dict, minutes: float = 20, data: Path | None = None, clock=time.monotonic,
                 sleep=time.sleep) -> tuple[bool, str]:
    """After the install: the app fetches the GPU runtime (or takes it from the old install folder).
    Waits for it, then checks every file's sha256."""
    data = data or DATA
    end, st = clock() + minutes * 60, {}
    while clock() < end:
        if gpu_runtime.installed(data, m):
            why = gpu_runtime.check(gpu_runtime.folder(data, m), m, full=True)
            return why is None, f"runtime {m['version']} in {gpu_runtime.folder(data, m)}" + (f": {why}" if why else "")
        st = status().get("gpu_runtime") or {}
        if st.get("state") in ("no_gpu", "old_driver"):
            return False, f"the app fetches no runtime here: {st['state']}"
        sleep(5)
    return False, f"no runtime after {minutes:.0f} min (status: {st or 'none'})"


def after_install(m: dict | None) -> list[tuple[str, bool, str]]:
    """The installed app has the GPU runtime and its own selftest runs on the GPU from it."""
    if not m:
        return [("GPU runtime present", False, "no ecoscribe/gpu_runtime.json")]
    ok, detail = wait_runtime(m)
    out = [("GPU runtime present", ok, detail)]
    if ok:
        rt = gpu_runtime.folder(DATA, m)
        ok, detail = judge_selftest(selftest(APPDIR / "Ecoscribe.exe", OUT / "selftest-installed.json"), rt)
        out.append(("installed app GPU selftest", ok, detail))
    return out


def run(setup: Path, do_install: bool) -> int:
    global OUT
    OUT = Path(setup).resolve().parent  # the build folder: dist, the pack and the selftest results live here
    m = gpu_runtime.manifest()
    checks = [("disk room", lambda: check_disk(setup, runtime=runtime_need(m))),
              ("no meeting live", check_no_meeting),
              ("version", lambda: check_version(setup)),
              ("unit tests", check_tests),
              ("app without CUDA DLLs", check_split),
              ("GPU runtime pack", check_runtime_pack),
              ("GPU runtime published", check_runtime_published),
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
        print(f"\nOld installers ({sum(p.stat().st_size for p in old) / 1e9:.1f} GB), delete them (the owner's standing yes):")
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
    post = after_install(m) if ok else []
    for name, good, detail in post:
        print(f"{'PASS' if good else 'FAIL'}  {name}: {detail}", flush=True)
    gpu_ok = all(good for _, good, _ in post)
    print(f"Installed: {'yes' if ok else 'no'}, {version}, {when}")
    print(f"Running now: {'yes' if s.get('state') == 'ready' else 'no'}")
    print(f"Checked by: status.json says {s.get('state')} on {s.get('device')}, version {s.get('version')}"
          + (f"; {post[-1][2]}" if post else ""))
    if ok and not gpu_ok:
        print("Left: the GPU check after the install failed (see FAIL above); the app runs, on the CPU until fixed")
    return 0 if ok and gpu_ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.exit(run(Path(args[0]).resolve(), "--install" in sys.argv))
