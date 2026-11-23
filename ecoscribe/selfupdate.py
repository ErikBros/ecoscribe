"""Self-update when the user says so (dictado-nmo, dictado-9zeo.1). Windows runs the Inno Setup installer; the
Mac swaps the app in from the release's .dmg (platform/macos/selfinstall.py).

updates.py's daily check also saves the latest release's installer (`asset`). When the user allowed it,
by Settings > New versions: Download by itself (`[ui] auto_update`, off by default) or by Home > Install now
for that one version (`install` in update.json), the background app:

1. downloads it: only Ecoscribe-Setup-<version>.exe (the Mac: Ecoscribe-<version>.dmg) of the latest app release of
   ErikBros/ecoscribe (the address is built here from the checked tag and name, never taken from the answer), into
   <data>/updates/, in the background. It pauses while a meeting records or saves (and goes on later from where it
   was, with a Range request), skips when the disk is short, and keeps the file only when its size and the SHA-256
   GitHub lists for it match. A download that fails says why in plain words (`update_error`) and when it tries
   again (`retry_at`, every RETRY_S); Install now tries again at once.
2. asks: when the download is done, the window opens on Home with a pop-up, Install now or Later (`on_ready`;
   once per version, `popup_shown`, and only after a dictation or a recording call has ended). Later (`asked`)
   leaves an Install now button on Home.
3. installs only when the user pressed Install now (`install_now`, read at once by PressWatcher), or at Quit: never
   by itself while the app is in use. The press must find nothing busy: no meeting recording, saving or waiting,
   no file or speakers job, nothing queued, no dictation recording or being transcribed. A press during a call is
   refused by the window ("Finish the call first"); other blockers hold it until they clear. The file is checked
   once more, the installer starts detached and the app quits: Windows /SILENT (Setup's own progress window, then
   it starts the new version on Home: /OPENHOME=1), the Mac's script swaps the app behind the window's Installing
   screen and opens the new one on Home (--after-update). At Quit the install is silent and the app stays closed
   (/VERYSILENT /LAUNCH=0); a Quit that can't install (still downloading, something busy) says so in the log and
   on the next start's Home (`quit_skipped`). ecoscribe.iss still refuses by itself while a meeting worker is
   alive and stops what is left of Ecoscribe.
4. one try per version: if the same old version starts again after an install was started, the install failed;
   Home then offers the Download link for it instead. A press is used once and lasts one run of the app.

Pure apart from the files, the one download and the one process start, which tests replace.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import updates

log = logging.getLogger(__name__)

FOLDER = "updates"
NAME = re.compile(r"^Ecoscribe-(?:Setup-)?(\d+\.\d+\.\d+)\.(?:exe|dmg)$")
DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
SPARE = 2 * 1024 ** 3   # free space kept besides the installer: installing needs room too
MIN_SIZE = 1024 ** 2     # an "installer" smaller than this is not one
CHUNK = 1024 ** 2
TIMEOUT_S = 30.0
RETRY_S = 30 * 60        # after a download that failed (not paused): wait this long before the next try
NOW_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/OPENHOME=1"]  # Install now: Setup's progress shows,
# then the new version starts and opens on Home (ecoscribe.iss: LaunchParams -> --after-update)
QUIT_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/LAUNCH=0"]  # at Quit: unseen, stays closed
AFTER_UPDATE = "--after-update"  # the new version's first start after an Install now: open the window on Home
PRESS_S = 1.0            # how often the background app looks for an Install now press
MAC = sys.platform == "darwin"
SUPPORTED = sys.platform == "win32" or MAC


def download_url(tag: str, name: str) -> str:
    return f"https://github.com/{updates.REPO}/releases/download/{tag}/{name}"


def installer_name(version: str, mac: bool | None = None) -> str:
    return f"Ecoscribe-{version}.dmg" if (MAC if mac is None else mac) else f"Ecoscribe-Setup-{version}.exe"


def _installers(d: Path):
    """The installers (and half downloads) in d, of either platform."""
    return [p for p in d.glob("Ecoscribe-*") if NAME.match(p.name.removesuffix(".part"))]


def pick_asset(release: dict, mac: bool | None = None) -> dict | None:
    """The app installer of this release for this platform, or None: a version tag (so never gpu-runtime-1),
    not a draft or pre-release, an asset named Ecoscribe-Setup-<that version>.exe (the Mac:
    Ecoscribe-<that version>.dmg), uploaded, served from this repo's own release, with a size (and the
    SHA-256 when GitHub lists one)."""
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    tag = release.get("tag_name")
    ver = updates.parse(tag)
    if not ver:
        return None
    want = installer_name("{}.{}.{}".format(*ver), mac)
    for a in release.get("assets") or []:
        if not isinstance(a, dict) or a.get("name") != want:
            continue
        size = a.get("size")
        if a.get("state", "uploaded") != "uploaded" or not isinstance(size, int) or size < MIN_SIZE:
            return None
        if a.get("browser_download_url") != download_url(tag, want):
            return None
        out = {"tag": tag, "version": "{}.{}.{}".format(*ver), "name": want, "size": size}
        m = re.fullmatch(r"sha256:([0-9a-f]{64})", str(a.get("digest") or ""))
        if m:
            out["sha256"] = m.group(1)
        return out
    return None


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / FOLDER


def wanted(state: dict, current: str, auto: bool) -> dict | None:
    """The installer to get, if any: newer than this version, allowed (Download by itself, or this one version
    from Home's Install now), and not a version whose install already failed."""
    a = state.get("asset")
    if not isinstance(a, dict) or not updates.is_newer(a.get("version"), current):
        return None
    if a.get("version") == state.get("install_failed"):
        return None
    if not (auto or a.get("version") in (state.get("install"), state.get("install_now"))):
        return None
    return a


def downloaded(data_dir: Path, state: dict, asset: dict) -> Path | None:
    """The installer on disk for this asset (checked by size here; fully, with the hash, before running)."""
    d = state.get("downloaded")
    if not isinstance(d, dict) or d.get("name") != asset["name"] or d.get("size") != asset["size"]:
        return None
    p = folder(data_dir) / asset["name"]
    try:
        return p if p.stat().st_size == asset["size"] else None
    except OSError:
        return None


def _sha256(path: Path, h=None):
    h = h or hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(CHUNK):
            h.update(b)
    return h


def verify(path: Path, asset: dict) -> bool:
    """Size and, when GitHub listed one, SHA-256: the file is exactly the release's installer."""
    try:
        if Path(path).stat().st_size != asset["size"]:
            return False
        return "sha256" not in asset or _sha256(path).hexdigest() == asset["sha256"]
    except OSError:
        return False


def _host_ok(url: str) -> bool:
    u = urllib.parse.urlsplit(url or "")
    return u.scheme == "https" and u.hostname in DOWNLOAD_HOSTS


def why_stopped(e: BaseException) -> str:
    """A download error in plain words for Home (never the exception's own text)."""
    if isinstance(e, urllib.error.HTTPError):
        return f"GitHub answered with error {e.code}"
    if isinstance(e, TimeoutError):  # socket.timeout too
        return "GitHub took too long to answer"
    if isinstance(e, (urllib.error.URLError, ConnectionError)):
        return "no connection to GitHub"
    if isinstance(e, ValueError):
        return "the file was larger than the release says"
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:  # ENOSPC
        return "the disk is full"
    if isinstance(e, OSError):
        return "the connection or the disk failed"
    return "something unexpected went wrong"


def _stopped(data_dir: Path, reason: str) -> None:
    updates._update(data_dir, update_error=f"The download stopped: {reason}.")


def download(data_dir: Path, asset: dict, opener=urllib.request.urlopen, pause=lambda: False,
             free=lambda p: shutil.disk_usage(p).free) -> Path | None:
    """Gets the installer into <data>/updates/. None when it isn't done (paused, offline, short of disk,
    a wrong size or hash); a paused or cut download goes on from where it was next time. A failure (not a pause)
    leaves the reason in plain words in update.json's `update_error`."""
    d = folder(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    final, part = d / asset["name"], d / (asset["name"] + ".part")
    size = asset["size"]
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    if free(d) < size - have + SPARE:
        _stopped(data_dir, "not enough free disk space")
        log.warning("self-update: not enough free space for %s", asset["name"])
        return None
    h = _sha256(part) if have else hashlib.sha256()
    headers = {"User-Agent": "Ecoscribe-update", "Accept": "application/octet-stream"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(download_url(asset["tag"], asset["name"]), headers=headers)
    step = max(size // 50, CHUNK)
    try:
        with opener(req, timeout=TIMEOUT_S) as r:
            if not _host_ok(r.geturl()):
                log.warning("self-update: refused a download from %s", urllib.parse.urlsplit(r.geturl()).hostname)
                _stopped(data_dir, "it came from an address that isn't GitHub")
                return None
            if have and getattr(r, "status", 200) != 206:  # the server sent it all again
                have, h = 0, hashlib.sha256()
            with open(part, "ab" if have else "wb") as f:
                mark = have
                while True:
                    if pause():
                        log.info("self-update: download paused at %d%% (a meeting)", 100 * have // size)
                        return None
                    b = r.read(CHUNK)
                    if not b:
                        break
                    have += len(b)
                    if have > size:
                        raise ValueError("larger than the release says")
                    h.update(b)
                    f.write(b)
                    if have - mark >= step:
                        mark = have
                        updates._update(data_dir, update_progress=100 * have // size)
    except Exception as e:  # noqa: BLE001  offline, cut, a bad answer: try again on a later look
        log.warning("self-update: download stopped (%s: %s)", type(e).__name__, e)
        if isinstance(e, ValueError):
            part.unlink(missing_ok=True)
        _stopped(data_dir, why_stopped(e))
        return None
    if have != size:
        _stopped(data_dir, "the connection ended before the end of the file")
        return None
    if "sha256" in asset and h.hexdigest() != asset["sha256"]:
        part.unlink(missing_ok=True)
        _stopped(data_dir, "the file didn't match the release, so it was deleted")
        log.warning("self-update: %s didn't match its SHA-256: deleted", asset["name"])
        return None
    os.replace(part, final)
    for old in _installers(d):
        if old != final:
            old.unlink(missing_ok=True)
    updates._update(data_dir, downloaded={k: asset[k] for k in ("version", "name", "size")}, update_progress=None,
                    update_error=None, retry_at=None)
    log.info("self-update: %s downloaded and checked", asset["name"])
    return final


def blockers(meetings: dict, app_busy: bool) -> list[str]:
    """Why installing now would be wrong (empty: safe). meetings: meetings.json / Meetings.state()."""
    out = []
    m = meetings or {}
    if m.get("meeting"):
        out.append("a meeting is recording or saving")
    if m.get("next_meeting"):
        out.append("a meeting is waiting to record")
    if m.get("job"):
        out.append("a file or speakers job is running")
    if m.get("queue"):
        out.append("jobs are queued")
    if app_busy:
        out.append("a dictation is recording or being transcribed")
    return out


def installer_args(path: Path, data_dir: Path, relaunch: bool) -> list[str] | None:
    """The command that installs. relaunch: an Install now press (Windows: Setup's own progress window, then the
    new version starts and opens on Home); not: at Quit (unseen, stays closed). The Mac: a script that waits for
    Ecoscribe to end, checks the new app's signature against this one's and swaps it in (None: this copy can't be
    replaced, e.g. not an .app)."""
    if MAC:
        from .platform.macos import selfinstall
        return selfinstall.command(Path(path), folder(data_dir), relaunch)
    return [str(path), *(NOW_ARGS if relaunch else QUIT_ARGS), f"/LOG={folder(data_dir) / 'install.log'}"]


def _popen(args: list[str]):
    flags = 0
    if sys.platform == "win32":  # outlives this app, which the installer stops
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000  # BREAKAWAY_FROM_JOB
    return subprocess.Popen(args, close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=sys.platform != "win32")  # the Mac: outlives the app too


def run_installer(data_dir: Path, path: Path, asset: dict, relaunch: bool, popen=_popen, now: float | None = None) -> bool:
    """Checks the file once more and starts the installer detached. The caller quits right after. A press is used
    here once, whatever happens: a failed start never starts again on its own."""
    if not verify(path, asset):
        Path(path).unlink(missing_ok=True)
        updates._update(data_dir, downloaded=None, install_now=None, install_wait=None,
                        update_error="The downloaded file didn't check out, so it is fetched again.")
        log.warning("self-update: %s failed its check before running: deleted", Path(path).name)
        return False
    args = installer_args(path, data_dir, relaunch)
    if not args:
        log.warning("self-update: this copy of Ecoscribe can't be replaced; Home offers the download")
        updates._update(data_dir, install_failed=asset["version"], install_now=None, install_wait=None,
                        update_error="This copy can't update itself")
        return False
    try:
        popen(args)
    except OSError:
        log.exception("self-update: the installer didn't start")
        updates._update(data_dir, install_now=None, install_wait=None)
        return False
    updates._update(data_dir, install_started={"version": asset["version"], "at": time.time() if now is None else now},
                    install_now=None, install_wait=None)
    log.warning("self-update: installing %s (%s)", asset["version"], "then starting it" if relaunch else "at quit")
    return True


def after_start(data_dir: Path, current: str) -> None:
    """At app start: an install that was started either worked (this is the new version: tidy up) or
    didn't (the old version again: no second try for that version, Home offers Download). A press of Install now
    lasts one run of the app: a new start forgets it."""
    st = updates.load(data_dir)
    started = st.get("install_started")
    if isinstance(started, dict):
        v = started.get("version")
        if updates.is_newer(v, current):
            log.warning("self-update: the install of %s didn't happen; Home offers the download", v)
            updates._update(data_dir, install_started=None, install_failed=v, downloaded=None)
            for p in _installers(folder(data_dir)):  # half a GB not to leave lying around
                p.unlink(missing_ok=True)
        else:
            updates._update(data_dir, install_started=None, install=None, downloaded=None, update_progress=None,
                            update_error=None, retry_at=None, asked=None, popup_shown=None, quit_skipped=None)
    if any(st.get(k) for k in ("install_now", "install_wait", "retry_now")):
        updates._update(data_dir, install_now=None, install_wait=None, retry_now=None)
    d = folder(data_dir)
    if d.exists():  # installers of this version or older: done with
        for p in _installers(d):
            m = NAME.match(p.name.removesuffix(".part"))
            if m and not updates.is_newer(m.group(1), current):
                p.unlink(missing_ok=True)


def in_call(meetings: dict) -> bool:
    """A call is recording (or about to): Install now says "Finish the call first" instead of installing."""
    m = meetings or {}
    rec = m.get("meeting") or {}
    return bool(m.get("next_meeting")) or (isinstance(rec, dict) and rec.get("status") in ("recording", "stopping"))


class SelfUpdater:
    """The background app's side. tick() runs on the update thread every minute and on PressWatcher's thread right
    after a press (one look at a time: `_lock`); install(path, asset, relaunch) is the app's own callback (on its
    main thread: start_install re-checks, then the app quits and starts the installer); on_ready(version) opens
    the window on Home for the pop-up."""

    def __init__(self, data_dir: Path, current: str, auto, meetings, app_busy, install, on_ready=lambda v: None,
                 opener=urllib.request.urlopen, clock=time.monotonic, wall=time.time,
                 free=lambda p: shutil.disk_usage(p).free, supported: bool = SUPPORTED):
        self.supported = supported
        self.data, self.current = Path(data_dir), current
        self.auto, self.meetings, self.app_busy = auto, meetings, app_busy
        self.install, self.on_ready, self.opener, self.clock, self.wall, self.free = install, on_ready, opener, clock, wall, free
        self._retry_at = None  # monotonic: no new download try before this
        self._lock = threading.Lock()  # the minute loop and a press never run two downloads or two installs
        self._installing = None  # the version handed to install(): not again in this run

    def blockers(self) -> list[str]:
        return blockers(self.meetings() or {}, bool(self.app_busy()))

    def _in_call(self) -> bool:
        m = self.meetings() or {}
        return bool(m.get("meeting") or m.get("next_meeting"))

    def ready(self) -> tuple[Path, dict] | None:
        st = updates.load(self.data)
        a = wanted(st, self.current, bool(self.auto()))
        p = downloaded(self.data, st, a) if a else None
        return (p, a) if p else None

    def tick(self) -> str:
        """One look. Returns what it did (tests and the log)."""
        if not self.supported:
            return "unsupported"
        if not self._lock.acquire(blocking=False):
            return "busy: another look is running"  # the press watcher looks again in a second
        try:
            return self._tick()
        finally:
            self._lock.release()

    def _wait(self, st: dict, why: str | None) -> None:
        """Home learns why a press waits (`install_wait`: "call" or "busy")."""
        if st.get("install_wait") != why:
            updates._update(self.data, install_wait=why)

    def _offer(self, st: dict, v: str) -> str:
        """Downloaded, no press yet: open the window on Home for the pop-up, once per version, never while a
        dictation runs or a call records."""
        if v in (st.get("asked"), st.get("popup_shown")):
            return "ready"
        if self.app_busy() or in_call(self.meetings() or {}):
            return "ready: the pop-up waits"
        updates._update(self.data, popup_shown=v)
        try:
            self.on_ready(v)
        except Exception:  # noqa: BLE001  Home still shows Install now
            log.exception("self-update: the window didn't open for the pop-up")
        return "ask"

    def _tick(self) -> str:
        if self._installing:
            return "installing"
        st = updates.load(self.data)
        a = wanted(st, self.current, bool(self.auto()))
        if not a:
            return "nothing"
        v = a["version"]
        pressed = st.get("install_now") == v
        p = downloaded(self.data, st, a)
        if p is None:
            if self._in_call():
                if pressed:
                    self._wait(st, "call" if in_call(self.meetings() or {}) else "busy")
                return "waiting: a meeting"
            if self._retry_at is not None and self.clock() < self._retry_at and not st.get("retry_now"):
                return "waiting: try the download again later"
            if st.get("retry_now"):
                updates._update(self.data, retry_now=None)
            p = download(self.data, a, self.opener, pause=self._in_call, free=self.free)
            if p is None:
                if not self._in_call():  # offline, a bad file, no disk: not again every minute
                    self._retry_at = self.clock() + RETRY_S
                    updates._update(self.data, retry_at=self.wall() + RETRY_S)
                return "downloading"
            self._retry_at = None
            st = updates.load(self.data)  # a press during the download counts now
            if st.get("install_now") != v:
                self._offer(st, v)
                return "downloaded"
        elif not pressed:
            return self._offer(st, v)
        why = self.blockers()
        if why:
            self._wait(st, "call" if in_call(self.meetings() or {}) else "busy")
            return "waiting: busy"
        self._wait(st, None)
        if not verify(p, a):  # here, on this thread: the app quits only for a file that checks out
            p.unlink(missing_ok=True)
            updates._update(self.data, downloaded=None, install_now=None,
                            update_error="The downloaded file didn't check out, so it is fetched again.")
            log.warning("self-update: %s failed its check: fetching it again", p.name)
            return "bad file"
        self._installing = v
        self.install(p, a, True)
        return "installing"

    def start_install(self, path: Path, asset: dict, relaunch: bool, pending: list, quit) -> bool:
        """On the app's main thread, right before quitting to install: still nothing busy? Then the install is
        queued (`pending`, run as the app ends) and the app quits. Otherwise the press stays and the next look
        tries again."""
        if pending:
            return False
        why = self.blockers()
        if why:
            log.info("self-update: not now (%s)", "; ".join(why))
            self._installing = None
            return False
        pending.append((path, asset, relaunch))
        quit()
        return True

    def at_quit(self) -> tuple[Path, dict] | None:
        """Tray > Quit: the installer to run as the app closes, if it's ready and nothing is busy. Never a silent
        skip: still downloading or something busy is logged and recorded for the next start's Home."""
        if not self.supported:
            return None
        st = updates.load(self.data)
        a = wanted(st, self.current, bool(self.auto()))
        if not a:
            return None
        p = downloaded(self.data, st, a)
        if p is None:
            log.warning("self-update: quit before %s finished downloading; the download goes on at the next start",
                        a["version"])
            updates._update(self.data, quit_skipped={"version": a["version"], "why": "downloading"})
            return None
        why = self.blockers()
        if why:
            log.warning("self-update: %s is ready but wasn't installed at quit (%s)", a["version"], "; ".join(why))
            updates._update(self.data, quit_skipped={"version": a["version"], "why": "busy"})
            return None
        return p, a


class PressWatcher(threading.Thread):
    """Install now reaches the background app at once (dictado-9zeo.1): the window writes the press into
    update.json (request_install); this thread reads that file every PRESS_S and, while a press is open, runs the
    updater's look (the same tick as the minute loop, under its lock). Same on Windows and the Mac: a file, no
    named event."""

    def __init__(self, data_dir: Path, updater: SelfUpdater, every: float = PRESS_S):
        super().__init__(name="ecoscribe-install-now", daemon=True)
        self.data, self.updater, self.every = Path(data_dir), updater, every
        self._stop = threading.Event()
        self._last = None

    def look(self) -> str | None:
        st = updates.load(self.data)
        if not updates.parse(st.get("install_now")):
            self._last = None
            return None
        r = self.updater.tick()
        if r != self._last:
            log.info("self-update (Install now): %s", r)
            self._last = r
        return r

    def run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                self.look()
            except Exception:  # noqa: BLE001  never take the app down over this
                log.exception("self-update: Install now look failed")

    def stop(self) -> None:
        self._stop.set()


def home_state(state: dict, current: str, auto: bool, supported: bool | None = None) -> dict:
    """What Home's version row and the pop-up add (dictado-nmo, dictado-9zeo.1): {"install": "offer" |
    "downloading" | "ready" | "installing" | "failed", "pct", "pressed", "error", "retry_at", "ask", "blocked",
    "quit"}; {} where this platform can't update itself (the row keeps Download only).
    ask: the pop-up is due (downloaded, Later not pressed, no press). blocked "call": a press waits on a call.
    quit: the last Quit couldn't install ("downloading" or "busy")."""
    a = state.get("asset")
    supported = SUPPORTED if supported is None else supported
    if not supported or not isinstance(a, dict) or not updates.is_newer(a.get("version"), current):
        return {}
    v = a.get("version")
    if state.get("install_failed") == v:
        return {"install": "failed"}
    started = state.get("install_started")
    if isinstance(started, dict) and started.get("version") == v:
        return {"install": "installing"}
    out = {}
    q = state.get("quit_skipped")
    if isinstance(q, dict) and q.get("version") == v and q.get("why") in ("downloading", "busy"):
        out["quit"] = q["why"]
    pressed = state.get("install_now") == v
    if pressed and state.get("install_wait") == "call":
        out["blocked"] = "call"
    if not (auto or pressed or state.get("install") == v):
        return {**out, "install": "offer"}
    d = state.get("downloaded")
    if isinstance(d, dict) and d.get("name") == a.get("name") and d.get("size") == a.get("size"):
        if pressed and "blocked" not in out:
            return {**out, "install": "installing"}
        return {**out, "install": "ready", **({} if pressed or state.get("asked") == v else {"ask": True})}
    out.update(install="downloading", pct=int(state.get("update_progress") or 0))
    if pressed:
        out["pressed"] = True
    if state.get("update_error"):
        out["error"] = str(state["update_error"])
        if isinstance(state.get("retry_at"), (int, float)):
            out["retry_at"] = state["retry_at"]
    return out


def request_install(data_dir: Path, version: str) -> bool:
    """Install now (Home or the pop-up): get this version if it isn't here yet and install it at once, with the
    Installing screen; a failed download is tried again right away."""
    if not updates.parse(version):
        return False
    v = str(version).lstrip("v")
    updates._update(data_dir, install=v, install_now=v, install_failed=None, install_wait=None, retry_now=True,
                    retry_at=None, update_error=None)
    return True


def later(data_dir: Path, version: str) -> bool:
    """The pop-up's Later: it doesn't come back for this version (Home keeps Install now)."""
    if not updates.parse(version):
        return False
    updates._update(data_dir, asked=str(version).lstrip("v"))
    return True
