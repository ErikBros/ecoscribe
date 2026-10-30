"""Self-update that never runs during a call (dictado-nmo). Windows runs the Inno Setup installer; the Mac
swaps the app in from the release's .dmg (platform/macos/selfinstall.py).

updates.py's daily check also saves the latest release's installer (`asset`). When the user allowed it,
by Settings > Install new versions by itself (`[ui] auto_update`, off by default) or by Home > Install
when idle for that one version (`install` in update.json), the background app:

1. downloads it: only Ecoscribe-Setup-<version>.exe (the Mac: Ecoscribe-<version>.dmg) of the latest app release of ErikBros/ecoscribe
   (the address is built here from the checked tag and name, never taken from the answer), into
   <data>/updates/, in the background. It pauses while a meeting records or saves (and goes on later
   from where it was, with a Range request), skips when the disk is short, and keeps the file only
   when its size and the SHA-256 GitHub lists for it match.
2. installs it only when safe(): no meeting recording, saving or waiting, no file or speakers job,
   nothing queued, no dictation recording or being transcribed. Then either when idle (no dictation
   for IDLE_S and nobody at the keyboard or mouse for IDLE_S) or at Quit. The file is checked once
   more, the installer starts detached with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART and the app
   quits. ecoscribe.iss still refuses by itself while a meeting worker is alive, stops what is left
   of Ecoscribe, and starts the new version (not after a Quit: /LAUNCH=0).
3. one try per version: if the same old version starts again after an install was started, the
   install failed; Home then offers the Download link for it instead.

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
import time
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
IDLE_S = 15 * 60         # no dictation and nobody at the computer for this long: install now
RETRY_S = 30 * 60        # after a download that failed (not paused): wait this long before the next try
INSTALL_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
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
    """The installer to get and install, if any: newer than this version, allowed (always, or this one
    version from Home), and not a version whose install already failed."""
    a = state.get("asset")
    if not isinstance(a, dict) or not updates.is_newer(a.get("version"), current):
        return None
    if a.get("version") == state.get("install_failed"):
        return None
    if not (auto or state.get("install") == a.get("version")):
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


def download(data_dir: Path, asset: dict, opener=urllib.request.urlopen, pause=lambda: False,
             free=lambda p: shutil.disk_usage(p).free) -> Path | None:
    """Gets the installer into <data>/updates/. None when it isn't done (paused, offline, short of disk,
    a wrong size or hash); a paused or cut download goes on from where it was next time."""
    d = folder(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    final, part = d / asset["name"], d / (asset["name"] + ".part")
    size = asset["size"]
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    if free(d) < size - have + SPARE:
        updates._update(data_dir, update_error="Not enough free disk space for the new version")
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
        log.info("self-update: download stopped (%s: %s)", type(e).__name__, e)
        if isinstance(e, ValueError):
            part.unlink(missing_ok=True)
        return None
    if have != size:
        return None
    if "sha256" in asset and h.hexdigest() != asset["sha256"]:
        part.unlink(missing_ok=True)
        updates._update(data_dir, update_error="The download didn't match the release; it will be fetched again")
        log.warning("self-update: %s didn't match its SHA-256: deleted", asset["name"])
        return None
    os.replace(part, final)
    for old in _installers(d):
        if old != final:
            old.unlink(missing_ok=True)
    updates._update(data_dir, downloaded={k: asset[k] for k in ("version", "name", "size")}, update_progress=None,
                    update_error=None)
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
    """The command that installs. The Mac: a script that waits for Ecoscribe to end, checks the new app's
    signature against this one's and swaps it in (None: this copy can't be replaced, e.g. not an .app)."""
    if MAC:
        from .platform.macos import selfinstall
        return selfinstall.command(Path(path), folder(data_dir), relaunch)
    args = [str(path), *INSTALL_ARGS, f"/LOG={folder(data_dir) / 'install.log'}"]
    if not relaunch:
        args.append("/LAUNCH=0")  # installed at Quit: stays closed (ecoscribe.iss reads it)
    return args


def _popen(args: list[str]):
    flags = 0
    if sys.platform == "win32":  # outlives this app, which the installer stops
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000  # BREAKAWAY_FROM_JOB
    return subprocess.Popen(args, close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=sys.platform != "win32")  # the Mac: outlives the app too


def run_installer(data_dir: Path, path: Path, asset: dict, relaunch: bool, popen=_popen, now: float | None = None) -> bool:
    """Checks the file once more and starts the installer detached. The caller quits right after."""
    if not verify(path, asset):
        Path(path).unlink(missing_ok=True)
        updates._update(data_dir, downloaded=None, update_error="The downloaded installer didn't check out; fetching it again")
        log.warning("self-update: %s failed its check before running: deleted", Path(path).name)
        return False
    args = installer_args(path, data_dir, relaunch)
    if not args:
        log.warning("self-update: this copy of Ecoscribe can't be replaced; Home offers the download")
        updates._update(data_dir, install_failed=asset["version"], update_error="This copy can't update itself")
        return False
    try:
        popen(args)
    except OSError:
        log.exception("self-update: the installer didn't start")
        return False
    updates._update(data_dir, install_started={"version": asset["version"], "at": time.time() if now is None else now})
    log.warning("self-update: installing %s (%s)", asset["version"], "then starting it" if relaunch else "at quit")
    return True


def after_start(data_dir: Path, current: str) -> None:
    """At app start: an install that was started either worked (this is the new version: tidy up) or
    didn't (the old version again: no second try for that version, Home offers Download)."""
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
                            update_error=None)
    d = folder(data_dir)
    if d.exists():  # installers of this version or older: done with
        for p in _installers(d):
            m = NAME.match(p.name.removesuffix(".part"))
            if m and not updates.is_newer(m.group(1), current):
                p.unlink(missing_ok=True)


def input_idle_s() -> float | None:
    """Seconds since the last key or mouse input anywhere on this PC (None: unknown, never idle)."""
    if MAC:
        try:
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True,
                                 timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r'"HIDIdleTime" = (\d+)', out)
        return int(m.group(1)) / 1e9 if m else None
    if sys.platform != "win32":
        return None
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return None
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


class SelfUpdater:
    """The background app's side. tick() runs on the update thread every minute; install(path, asset,
    relaunch) is the app's own callback (on its main thread: re-checks, starts the installer, quits)."""

    def __init__(self, data_dir: Path, current: str, auto, meetings, app_busy, last_dictation, install,
                 input_idle=input_idle_s, opener=urllib.request.urlopen, clock=time.monotonic,
                 free=lambda p: shutil.disk_usage(p).free, supported: bool = SUPPORTED):
        self.supported = supported
        self.data, self.current = Path(data_dir), current
        self.auto, self.meetings, self.app_busy, self.last_dictation = auto, meetings, app_busy, last_dictation
        self.install, self.input_idle, self.opener, self.clock, self.free = install, input_idle, opener, clock, free
        self._retry_at = None  # monotonic: no new download try before this

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

    def idle(self) -> bool:
        last = self.last_dictation()
        if last is not None and self.clock() - last < IDLE_S:
            return False
        away = self.input_idle()
        return away is not None and away >= IDLE_S

    def tick(self) -> str:
        """One look. Returns what it did (tests and the log)."""
        if not self.supported:
            return "unsupported"
        st = updates.load(self.data)
        a = wanted(st, self.current, bool(self.auto()))
        if not a:
            return "nothing"
        p = downloaded(self.data, st, a)
        if p is None:
            if self._in_call():
                return "waiting: a meeting"
            if self._retry_at is not None and self.clock() < self._retry_at:
                return "waiting: try the download again later"
            if download(self.data, a, self.opener, pause=self._in_call, free=self.free):
                self._retry_at = None
                return "downloaded"
            if not self._in_call():  # offline, a bad file, no disk: not again every minute
                self._retry_at = self.clock() + RETRY_S
            return "downloading"
        if self.blockers():
            return "waiting: busy"
        if not self.idle():
            return "waiting: not idle"
        if not verify(p, a):  # here, on this thread: the app quits only for a file that checks out
            p.unlink(missing_ok=True)
            updates._update(self.data, downloaded=None)
            log.warning("self-update: %s failed its check: fetching it again", p.name)
            return "bad file"
        self.install(p, a, True)
        return "installing"

    def at_quit(self) -> tuple[Path, dict] | None:
        """Tray > Quit: the installer to run as the app closes, if it's ready and nothing is busy."""
        if not self.supported:
            return None
        r = self.ready()
        if r is None or self.blockers():
            return None
        return r


def home_state(state: dict, current: str, auto: bool, supported: bool | None = None) -> dict:
    """What Home's version row adds (dictado-nmo): {"install": "offer" | "downloading" | "ready" | "failed",
    "pct", "error"}; {} where this platform can't install by itself (the row keeps Download only)."""
    a = state.get("asset")
    supported = SUPPORTED if supported is None else supported
    if not supported or not isinstance(a, dict) or not updates.is_newer(a.get("version"), current):
        return {}
    if state.get("install_failed") == a.get("version"):
        return {"install": "failed"}
    if not (auto or state.get("install") == a.get("version")):
        return {"install": "offer"}
    d = state.get("downloaded")
    if isinstance(d, dict) and d.get("name") == a.get("name") and d.get("size") == a.get("size"):
        return {"install": "ready"}
    out = {"install": "downloading", "pct": int(state.get("update_progress") or 0)}
    if state.get("update_error"):
        out["error"] = str(state["update_error"])
    return out


def allow_once(data_dir: Path, version: str) -> bool:
    """Home > Install when idle: this one version may be downloaded and installed when safe."""
    if not updates.parse(version):
        return False
    updates._update(data_dir, install=str(version).lstrip("v"), install_failed=None)
    return True
