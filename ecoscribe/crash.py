"""Crash reports (t0u.37): so a crash is never silent and always debuggable.

The background app turns on faulthandler at start, writing to crashes/live/fault-<pid>.log:
a native crash (an access violation in a Windows call, like 2026-10-06 14:03) then leaves the
Python stack of every thread there, which a normal log can't. Python errors on any thread go
to ecoscribe.log through the except hooks. When the app dies, the supervisor (supervise.py)
turns that into a report folder crashes/<time>/ and restarts it:

    report.md     what happened, in one screen: time, version, exit code, the crashing line
    fault.log     faulthandler's native trace
    log-tail.txt  the last 300 lines of ecoscribe.log
    status.json   what the app said it was doing
    config.toml   the settings (the calendar link removed: it's a secret)

Two markers: `seen-user` (dismissed on Home), `seen-claude` (Claude read it; a Claude Code
SessionStart hook can announce reports without it).

Before the watchdog kills a frozen app it asks for a last snapshot (dictado-dhr): it drops
crashes/live/dump-<pid>, the app's FreezeWatch thread answers with freeze-<pid>-final.log (every
thread's stack right before the restart; on macOS SIGUSR1 also adds the native-level dump to the fault
file). Reports are kept bounded (the newest KEEP_REPORTS, at most MAX_BYTES together).

crashes/health.json + health.md: counts only, by version (starts, crashes, freezes, freezes the watchdog
had to restart, give-ups, first and last day). No log text, no transcripts, nothing personal: a quick
health check Claude or the user can read locally.
"""
from __future__ import annotations

import faulthandler
import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
TAIL = 300
EXIT_NAMES = {0xC0000005: "access violation", 0xC0000409: "stack buffer overrun", 0xC00000FD: "stack overflow",
              0xC0000374: "heap corruption", 0xC0000135: "DLL not found", 0x40010004: "killed by Windows",
              0xC000013A: "Ctrl+C / console closed", 1: "exit code 1"}
_fault_file = None  # kept open for the life of the process: faulthandler writes to its fd
KEEP_REPORTS = 20  # report folders kept (newest first)
MAX_BYTES = 50 * 1024 * 1024  # all report folders together
KEEP_FREEZES = 20  # freeze-*.log dumps left in live/ by freezes the app came back from
HEALTH_KINDS = ("starts", "crashes", "freezes", "freezes_restarted", "gave_up")


def crashes_dir(data: Path) -> Path:
    return Path(data) / "crashes"


def fault_path(data: Path, pid: int) -> Path:
    return crashes_dir(data) / "live" / f"fault-{pid}.log"


def enable(data: Path, pid: int) -> None:
    """Native crash trace to a file + Python errors on every thread to the log."""
    global _fault_file
    p = fault_path(data, pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    _fault_file = open(p, "w", encoding="utf-8")  # noqa: SIM115 (must stay open)
    faulthandler.enable(_fault_file, all_threads=True)
    if sys.platform == "darwin":
        import os
        import signal
        # `kill -USR1 <pid>` adds every thread's stack to the fault file (the supervisor does, on a hang)
        faulthandler.register(signal.SIGUSR1, file=_fault_file, all_threads=True, chain=False)
        try:  # a LaunchAgent/Finder start sends fd 2 nowhere: native libraries (MLX, PyObjC) print there
            err = open(Path(data) / "stderr.log", "a", encoding="utf-8")  # noqa: SIM115 (must stay open)
            os.dup2(err.fileno(), 2)
            sys.stderr = err
        except OSError:
            log.exception("stderr not redirected")

    def hook(exc_type, exc, tb):
        log.critical("unhandled error", exc_info=(exc_type, exc, tb))
    sys.excepthook = hook
    threading.excepthook = lambda a: log.critical("unhandled error in thread %s", a.thread and a.thread.name,
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def exit_name(code: int | None) -> str:
    if code is None:
        return "unknown"
    code &= 0xFFFFFFFF
    return f"0x{code:08X} ({EXIT_NAMES.get(code, 'crash')})" if code > 255 else f"{code} ({EXIT_NAMES.get(code, 'exit')})"


def is_crash(code: int | None, fault_text: str, log_tail: str) -> bool:
    """Native crash codes always; exit code 1 only with a trace (else it was killed: Task
    Manager, the installer's taskkill); 0 never (the supervisor checks clean state first).
    No exit code (macOS: the supervisor isn't the app's parent): a trace or an unhandled error."""
    if code is None:
        return bool(fault_text.strip()) or "unhandled error" in log_tail[-4000:]
    code &= 0xFFFFFFFF
    if code in (0, 0x40010004, 0xC000013A):
        return False
    if code >= 0xC0000000:
        return True
    return bool(fault_text.strip()) or "unhandled error" in log_tail[-4000:]


def _tail(path: Path, n: int = TAIL) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:]) + "\n"


def _where(fault_text: str) -> str:
    """The crashing thread's innermost frame from faulthandler's output, if there is one."""
    block = fault_text.split("Current thread", 1)
    if len(block) < 2:
        return ""
    m = re.search(r'File "([^"]+)", line (\d+) in (\S+)', block[1])
    return f"{Path(m.group(1)).name}:{m.group(2)} in {m.group(3)}" if m else ""


def make_report(data: Path, pid: int, code: int | None, log_path: Path, config_path: Path | None = None,
                version: str = "", now: float | None = None, gave_up: bool = False) -> Path:
    data = Path(data)
    now = time.time() if now is None else now
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now))
    d = crashes_dir(data) / stamp
    n = 2
    while d.exists():
        d = crashes_dir(data) / f"{stamp}-{n}"
        n += 1
    d.mkdir(parents=True)
    fp = fault_path(data, pid)
    fault = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    if fp.exists():
        shutil.move(str(fp), d / "fault.log")
    for fz in sorted(fp.parent.glob(f"freeze-{pid}-*.log")) if fp.parent.exists() else []:  # FreezeWatch dumps
        shutil.move(str(fz), d / fz.name)
    tail = _tail(log_path)
    (d / "log-tail.txt").write_text(tail, encoding="utf-8")
    for name in ("status.json",):
        if (data / name).exists():
            shutil.copy2(data / name, d / name)
    if config_path and Path(config_path).exists():  # the calendar link is a secret: never in a report
        cfg = Path(config_path).read_text(encoding="utf-8", errors="replace")
        (d / "config.toml").write_text(re.sub(r'(?m)^(calendar_url\s*=\s*).*$', r'\1"<removed>"', cfg), encoding="utf-8")
    last = [l for l in tail.splitlines() if l.strip()][-1:] or ["(empty log)"]
    where = _where(fault)
    lines = [f"# Ecoscribe crash {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}", "",
             f"- Version: {version or '?'}", f"- System: {_system()}", f"- Process: {pid}",
             f"- Exit: {exit_name(code)}",
             f"- Crashed in: {where or 'no Python frame (see fault.log)'}",
             f"- Last log line: `{last[0][:300]}`",
             f"- Restarted: {'no, 3 crashes in 10 minutes: Ecoscribe stopped restarting itself' if gave_up else 'yes'}",
             "", "Files here: fault.log (native trace, every thread), log-tail.txt (last 300 log lines), "
             "status.json, config.toml (calendar link removed).", ""]
    if fault.strip():
        lines += ["## fault.log", "", "```", fault.strip()[:6000], "```", ""]
    (d / "report.md").write_text("\n".join(lines), encoding="utf-8")
    try:
        prune(data, keep=d)
    except OSError:
        log.exception("old crash reports not pruned")
    return d


def _system() -> str:
    """Versions that matter for a crash: the OS and Python (no machine or user name)."""
    return f"{platform.system()} {platform.release()} ({platform.version()}), Python {platform.python_version()}"


def _size(d: Path) -> int:
    return sum(f.stat().st_size for f in Path(d).rglob("*") if f.is_file())


def prune(data: Path, keep: Path | None = None, max_reports: int = KEEP_REPORTS, max_bytes: int = MAX_BYTES) -> list[Path]:
    """Keeps crashes/ bounded: the newest max_reports report folders, at most max_bytes together (the
    report just made, `keep`, always stays), and the newest KEEP_FREEZES freeze dumps in live/."""
    gone = []
    reps = reports(data)  # newest first
    total = 0
    for i, r in enumerate(reps):
        size = _size(r)
        if r != keep and (i >= max_reports or total + size > max_bytes):
            shutil.rmtree(r, ignore_errors=True)
            gone.append(r)
            continue
        total += size
    live = crashes_dir(data) / "live"
    if live.exists():
        dumps = sorted(live.glob("freeze-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in dumps[KEEP_FREEZES:]:
            p.unlink(missing_ok=True)
            gone.append(p)
    return gone


def health_path(data: Path) -> Path:
    return crashes_dir(data) / "health.json"


def health(data: Path) -> dict:
    """{version: {starts, crashes, freezes, freezes_restarted, gave_up, first, last}}."""
    try:
        h = json.loads(health_path(data).read_text(encoding="utf-8"))
        return h if isinstance(h, dict) else {}
    except (OSError, ValueError):
        return {}


def record(data: Path, version: str, kind: str, now: float | None = None) -> dict:
    """Counts one event for this version in health.json and rewrites health.md. Counts and days only."""
    if kind not in HEALTH_KINDS:
        raise ValueError(kind)
    day = time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))
    h = health(data)
    v = h.setdefault(version or "?", {})
    for k in HEALTH_KINDS:
        v.setdefault(k, 0)
    v[kind] += 1
    v.setdefault("first", day)
    v["last"] = day
    p = health_path(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"health.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(h, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    try:
        (p.parent / "health.md").write_text(health_text(h), encoding="utf-8")
    except OSError:
        pass
    return h


def _vkey(v: str):
    return tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.\-]", v))


def health_text(h: dict) -> str:
    """The counts as a small table, newest version first."""
    lines = ["# Ecoscribe health, by version", "",
             "Counts only. starts: the background app started (restarts too). crashes: it died and the "
             "watchdog restarted it. freezes: the window's thread stopped answering for 3 s or more. "
             "restarted: frozen 60 s, so the watchdog restarted it. gave up: 3 crashes in 10 minutes.", "",
             "| Version | Starts | Crashes | Freezes | Restarted frozen | Gave up | First | Last |",
             "|---|---|---|---|---|---|---|---|"]
    for ver in sorted(h, key=_vkey, reverse=True):
        v = h[ver]
        lines.append(f"| {ver} | {v.get('starts', 0)} | {v.get('crashes', 0)} | {v.get('freezes', 0)} | "
                     f"{v.get('freezes_restarted', 0)} | {v.get('gave_up', 0)} | {v.get('first', '')} | "
                     f"{v.get('last', '')} |")
    return "\n".join(lines) + "\n"


def reports(data: Path) -> list[Path]:
    root = crashes_dir(data)
    if not root.exists():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and p.name != "live" and (p / "report.md").exists()),
                  key=lambda p: p.name, reverse=True)


_LEGACY = {"user": "seen-erik"}  # 1.4.1 wrote seen-erik before the marker became seen-user


def unseen(data: Path, by: str) -> list[Path]:
    old = _LEGACY.get(by)
    return [p for p in reports(data) if not (p / f"seen-{by}").exists() and not (old and (p / old).exists())]


def mark_seen(d: Path, by: str) -> None:
    (Path(d) / f"seen-{by}").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def for_claude(d: Path) -> str:
    """Copy crash report for Claude: the summary plus the log tail."""
    d = Path(d)
    text = (d / "report.md").read_text(encoding="utf-8", errors="replace")
    tail = (d / "log-tail.txt").read_text(encoding="utf-8", errors="replace") if (d / "log-tail.txt").exists() else ""
    return (f"Ecoscribe crashed. Please find the cause. Report folder: {d}\n\n{text}\n"
            f"## Last log lines\n\n```\n{tail[-8000:]}\n```\n")


def clean_live(data: Path, alive_pids: set[int]) -> None:
    """Remove empty fault files of processes that ended cleanly."""
    live = crashes_dir(data) / "live"
    if not live.exists():
        return
    for p in live.glob("fault-*.log"):
        try:
            pid = int(p.stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        if pid not in alive_pids and p.stat().st_size == 0:
            p.unlink(missing_ok=True)


def awake_clock():
    """Seconds the PC has been awake. Windows' time.monotonic keeps counting while the PC sleeps, so a
    night asleep read as a 3-hour freeze (dictado-kux); QueryUnbiasedInterruptTime stops. The macOS and
    Linux monotonic clocks already stop."""
    if sys.platform != "win32":
        return time.monotonic
    import ctypes
    f = ctypes.windll.kernel32.QueryUnbiasedInterruptTime

    def clock() -> float:
        t = ctypes.c_ulonglong(0)  # one per call: beat() and check() run on different threads
        f(ctypes.byref(t))
        return t.value / 1e7  # 100 ns units
    return clock


class FreezeWatch:
    """Notices the app's main (tk) thread not answering: today's crashes froze first and
    Windows offered to force-close Ecoscribe, while every key on the PC lagged behind the hook.
    The main loop calls beat() every 0.5 s; if no beat comes for `limit_s`, every thread's
    stack goes to crashes/live/freeze-<pid>-<n>.log and the log says so. Once per freeze."""

    def __init__(self, data: Path, pid: int, limit_s: float = 3.0, clock=None, version: str | None = None):
        self.dir, self.pid, self.limit, self.clock = crashes_dir(data) / "live", pid, limit_s, clock or awake_clock()
        self.data, self.version = Path(data), version  # version: count freezes in health.json (None: don't)
        self.last = self.clock()
        self.frozen = False
        self.count = 0
        self._stop = threading.Event()

    def marker(self) -> Path:
        """Exists while frozen; holds when the main thread last answered (the supervisor's hang check)."""
        return self.dir / f"frozen-{self.pid}"

    def beat(self) -> None:
        if self.frozen:
            log.warning("main thread answering again after %.1f s", self.clock() - self.last)
            self.frozen = False
            self.marker().unlink(missing_ok=True)
        self.last = self.clock()

    def request(self) -> Path:
        """The watchdog drops this file to ask for a last snapshot before it restarts the app."""
        return self.dir / f"dump-{self.pid}"

    def final(self) -> Path:
        return self.dir / f"freeze-{self.pid}-final.log"

    def _dump(self, p: Path, head: str) -> None:
        with open(p, "w", encoding="utf-8") as f:
            f.write(head + "\n\n")
            f.flush()
            faulthandler.dump_traceback(f, all_threads=True)

    def check(self) -> Path | None:
        """One look; returns the dump file when it just wrote one."""
        stale = self.clock() - self.last
        if self.frozen and self.request().exists():  # the watchdog is about to restart us
            p = self.final()
            self._dump(p, f"Snapshot before the watchdog's restart: main thread not answering for {stale:.1f} s "
                          f"at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.request().unlink(missing_ok=True)
            log.error("FREEZE: last snapshot before the restart in %s", p)
            return p
        if stale < self.limit or self.frozen:
            return None
        self.frozen = True
        self.count += 1
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.dir / f"freeze-{self.pid}-{self.count}.log"
        self._dump(p, f"Main thread not answering for {stale:.1f} s at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        log.error("FREEZE: main thread not answering for %.1f s; every thread's stack in %s", stale, p)
        self.marker().write_text(str(time.time() - stale), encoding="utf-8")
        if self.version is not None:
            try:
                record(self.data, self.version, "freezes")
                prune(self.data)
            except (OSError, ValueError):
                log.exception("freeze not counted")
        return p

    def start(self) -> "FreezeWatch":
        def loop():
            while not self._stop.wait(1.0):
                try:
                    self.check()
                except Exception:
                    log.exception("freeze check failed")
        threading.Thread(target=loop, name="ecoscribe-freezewatch", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
