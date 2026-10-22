"""The watchdog (t0u.37): `Ecoscribe.exe --supervise`.

A small second process the background app starts (and re-starts if it's missing). It
follows the app's pid in status.json through a process handle, so when the app ends it
gets the real exit code:

- state "stopped" (Quit from the tray)            -> the watchdog ends too
- state "restarting" (Settings saved)             -> waits for the new copy, follows it
- killed (Task Manager, the installer's taskkill) -> ends, no restart
- a crash                                          -> crash report, restart within ~2 s
  with --after-crash <report> so the app says so on the pill and recovers the audio;
  the 3rd crash in 10 minutes stops the restarts (state "crashed": Home says so).
- with hang_s (both platforms, 60 s): frozen longer than that (FreezeWatch's marker) -> a last snapshot
  (dictado-dhr: up to SNAPSHOT_S for the app's every-thread dump), report, kill, restart.
Every crash, frozen restart and give-up is counted by version in crashes/health.json (counts only).

On macOS the "handle" is the pid (MacProc): the watchdog isn't the app's parent, so there is
no exit code; crash.is_crash then goes by the fault trace and the log.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from . import crash

log = logging.getLogger(__name__)
MUTEX = "Local\\EcoscribeSupervisor"
MAX_CRASHES, WINDOW_S = 3, 600
RESTART_WAIT_S = 30
HANG_S = 60.0  # a main thread frozen this long (as watched by the watchdog) is killed and restarted
SNAPSHOT_S = 3.0  # how long a frozen app gets to write its last every-thread snapshot before the kill


def _read(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Supervisor:
    def __init__(self, data: Path, spawn, proc, log_path: Path, config_path: Path | None = None, version: str = "",
                 clock=time.time, hang_s: float | None = None):
        """proc: object with open(pid) -> handle | None, alive(handle) -> bool, exit_code(handle) -> int | None,
        and kill(handle) when hang_s is set."""
        self.data, self.spawn, self.proc, self.clock = Path(data), spawn, proc, clock
        self.log_path, self.config_path, self.version = log_path, config_path, version
        self.pid: int | None = None
        self.handle = None
        self.crashes: list[float] = []
        self.waiting_since: float | None = None
        self.hang_s = hang_s
        self._frozen_seen: tuple | None = None  # (pid, when this watchdog first saw its frozen marker)
        self._snapshot_asked: float | None = None  # when the last snapshot was asked for (the kill waits for it)

    def _status(self) -> dict:
        return _read(self.data / "status.json")

    def step(self) -> str:
        """One look. 'ok' to keep going; 'quit', 'killed' or 'gave_up' to end."""
        st = self._status()
        pid = st.get("pid")
        if self.handle is None:
            if pid and pid != self.pid:
                h = self.proc.open(pid)
                if h is not None and self.proc.alive(h):
                    self.pid, self.handle, self.waiting_since = pid, h, None
                    log.info("watching Ecoscribe pid=%s", pid)
                    return "ok"
            if self.waiting_since is not None and st.get("state") == "stopped" and pid != self.pid:
                log.info("Ecoscribe pid=%s quit before the watchdog picked it up: watchdog ends", pid)
                return "quit"  # the restarted copy was quit within a second of starting
            if self.waiting_since is not None and self.clock() - self.waiting_since > RESTART_WAIT_S:
                log.warning("no new Ecoscribe after %d s; starting it", RESTART_WAIT_S)
                self.waiting_since = None
                self.spawn(["--restarted"])
            return "ok"
        if self.proc.alive(self.handle):
            return self._check_hang()
        code = self.proc.exit_code(self.handle)
        old, self.handle = self.pid, None
        state = st.get("state") if st.get("pid") == old else "replaced"
        if state == "stopped":
            log.info("Ecoscribe quit (pid=%s): watchdog ends", old)
            return "quit"
        if state in ("restarting", "replaced"):
            log.info("Ecoscribe restarting (pid=%s): waiting for the new copy", old)
            self.waiting_since = self.clock()
            return "ok"
        fp = crash.fault_path(self.data, old)
        fault = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
        tail = crash._tail(self.log_path, 60)
        if not crash.is_crash(code, fault, tail):
            log.info("Ecoscribe ended pid=%s exit=%s (killed, not a crash): watchdog ends", old, crash.exit_name(code))
            return "killed"
        return self._crashed(old, code)

    def _check_hang(self) -> str:
        if not self.hang_s:
            return "ok"
        live = crash.crashes_dir(self.data) / "live"
        m, req, final = live / f"frozen-{self.pid}", live / f"dump-{self.pid}", live / f"freeze-{self.pid}-final.log"
        if not m.exists():
            if self._snapshot_asked is not None:
                log.info("Ecoscribe pid=%s answered again before the restart: not killed", self.pid)
                req.unlink(missing_ok=True)
            self._frozen_seen = self._snapshot_asked = None
            return "ok"
        # Count the freeze from when WE first saw it, not from the app's last beat: after the
        # PC sleeps the last beat is hours old, and a just-woken healthy app would be killed.
        now = self.clock()
        if self._frozen_seen is None or self._frozen_seen[0] != self.pid:
            self._frozen_seen = (self.pid, now)
            return "ok"
        if now - self._frozen_seen[1] < self.hang_s:
            return "ok"
        if self._snapshot_asked is None:  # first a last look at every thread, then the kill
            self._snapshot_asked = now
            req.write_text(str(time.time()), encoding="utf-8")
            dump = getattr(self.proc, "dump", None)
            if dump:
                try:
                    dump(self.handle)  # macOS: SIGUSR1, faulthandler's native-level dump into the fault file
                except Exception:
                    log.exception("no native snapshot")
            log.warning("Ecoscribe pid=%s frozen for %.0f s (watched): last snapshot, then a restart", self.pid,
                        self.hang_s)
            return "ok"
        if not final.exists() and now - self._snapshot_asked < SNAPSHOT_S:
            return "ok"
        if not final.exists():
            log.warning("no last snapshot from pid=%s within %.0f s (the whole app is stuck)", self.pid, SNAPSHOT_S)
        self._frozen_seen = self._snapshot_asked = None
        old = self.pid
        log.error("Ecoscribe pid=%s frozen for %.0f s (watched): killing it", old, self.hang_s)
        self.proc.kill(self.handle)
        self.handle = None
        m.unlink(missing_ok=True)
        req.unlink(missing_ok=True)
        return self._crashed(old, None, frozen=True)

    def _crashed(self, old: int, code: int | None, frozen: bool = False) -> str:
        now = self.clock()
        self.crashes = [t for t in self.crashes if now - t < WINDOW_S] + [now]
        gave_up = len(self.crashes) >= MAX_CRASHES
        report = crash.make_report(self.data, old, code, self.log_path, self.config_path, self.version, now, gave_up)
        if frozen:
            last = (report / f"freeze-{old}-final.log").exists()
            with open(report / "report.md", "a", encoding="utf-8") as f:
                f.write(f"\nFrozen (no answer from the main thread for {self.hang_s:.0f} s): killed by the watchdog. "
                        "The freeze-*.log files here hold every thread's stack"
                        + (f"; freeze-{old}-final.log is the last snapshot, right before the restart.\n" if last else
                           ". No last snapshot came before the restart (the whole app was stuck).\n"))
        try:
            crash.record(self.data, self.version, "freezes_restarted" if frozen else "crashes")
            if gave_up:
                crash.record(self.data, self.version, "gave_up")
        except (OSError, ValueError):
            log.exception("crash not counted")
        log.error("Ecoscribe %s pid=%s exit=%s report=%s", "froze" if frozen else "crashed", old,
                  crash.exit_name(code), report)
        if gave_up:
            self._mark_crashed(report)
            return "gave_up"
        self.spawn(["--restarted", "--after-crash", str(report)])
        self.waiting_since = self.clock()
        return "ok"

    def _mark_crashed(self, report: Path) -> None:
        p = self.data / "status.json"
        st = self._status()
        st.update(state="crashed", error=f"Ecoscribe crashed {MAX_CRASHES} times in 10 minutes", crash=str(report),
                  ts=time.time())
        tmp = p.with_suffix(".sup.tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def run(self, poll_s: float = 1.0, sleep=time.sleep) -> str:
        while True:
            try:
                r = self.step()
            except Exception:
                log.exception("watchdog step failed")
                r = "ok"
            if r != "ok":
                return r
            sleep(poll_s)


class WinProc:
    SYNCHRONIZE, QUERY_LIMITED = 0x00100000, 0x1000

    def open(self, pid):
        import win32api
        try:
            return win32api.OpenProcess(self.SYNCHRONIZE | self.QUERY_LIMITED, False, int(pid))
        except Exception:
            return None

    def alive(self, h) -> bool:
        import win32event
        return win32event.WaitForSingleObject(h, 0) == win32event.WAIT_TIMEOUT

    def exit_code(self, h) -> int:
        import win32process
        return win32process.GetExitCodeProcess(h) & 0xFFFFFFFF

    def kill(self, h) -> None:
        """A frozen app: end it (the watch handle can't, so open one that may terminate)."""
        import win32api
        import win32process
        try:
            pid = win32process.GetProcessId(h)
            t = win32api.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            try:
                win32api.TerminateProcess(t, 0xDEAD)
            finally:
                win32api.CloseHandle(t)
        except Exception:
            log.exception("could not end the frozen Ecoscribe")


class MacProc:
    """macOS: the handle is the pid. No exit code for a process we didn't start."""

    def open(self, pid):
        from .platform.macos.procs import alive
        return int(pid) if alive(pid) else None

    def alive(self, h) -> bool:
        from .platform.macos.procs import alive
        return alive(h)

    def exit_code(self, h):
        return None

    def kill(self, h) -> None:
        import signal
        try:
            os.kill(int(h), signal.SIGKILL)
        except ProcessLookupError:
            pass

    def dump(self, h) -> None:
        """A last snapshot of a frozen app: crash.enable registered SIGUSR1 to dump every thread's stack
        into its fault file, from native code (works even when the stuck thread holds Python's lock)."""
        import signal
        try:
            os.kill(int(h), signal.SIGUSR1)
        except ProcessLookupError:
            pass


def running() -> bool:
    """Is a watchdog already up? (its named mutex exists)"""
    if sys.platform == "darwin":
        from .platform.macos.sysutil import held
        return held(MUTEX)
    try:
        import win32api
        import win32event
        h = win32event.OpenMutex(0x00100000, False, MUTEX)
        win32api.CloseHandle(h)
        return True
    except Exception:
        return False


def ensure(log_=log) -> None:
    """Called by the background app: start the watchdog if none is running."""
    if running():
        return
    from . import ipc
    try:
        ipc.spawn(["--supervise"])
        log_.info("watchdog started")
    except Exception:
        log_.exception("watchdog not started")


def main() -> int:
    from . import __version__, ipc, paths, winutil
    data = paths.data_dir()
    winutil.setup_logging(data / "supervisor.log", logging.INFO)
    if not winutil.single_instance(MUTEX):
        return 0
    mac = sys.platform == "darwin"
    sup = Supervisor(data, spawn=ipc.spawn, proc=MacProc() if mac else WinProc(), log_path=data / "ecoscribe.log",
                     config_path=paths.config_path(), version=__version__, hang_s=HANG_S)
    log.info("watchdog %s up pid=%d", __version__, os.getpid())
    r = sup.run()
    log.info("watchdog ends: %s", r)
    return 0
