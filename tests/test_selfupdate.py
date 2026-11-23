"""dictado-nmo, dictado-9zeo.1: self-update that installs when the user presses Install now (or quits), never by
itself and never during a call. Fakes everywhere: no network, no real installer is ever started, the installed app
is never touched, every data folder is tmp_path."""
import errno
import hashlib
import io
import json
import logging
import threading
import time
import urllib.error
from pathlib import Path

import pytest

from ecoscribe import selfupdate, updates
from ecoscribe.window import Api

BLOB = bytes(range(256)) * (4 * 4096 + 7)  # ~4 MB of invented bytes standing in for an installer
SHA = hashlib.sha256(BLOB).hexdigest()
TAG = "v1.19.0"
NAME = "Ecoscribe-Setup-1.19.0.exe"
URL = f"https://github.com/ErikBros/ecoscribe/releases/download/{TAG}/{NAME}"
CDN = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sp=r"
IDLE = {"meeting": None, "job": None, "queue": [], "next_meeting": None}


def release(**kw):
    asset = {"name": NAME, "size": len(BLOB), "state": "uploaded", "browser_download_url": URL,
             "digest": "sha256:" + SHA, "content_type": "application/x-msdownload"}
    asset.update(kw.pop("asset", {}))
    r = {"tag_name": TAG, "draft": False, "prerelease": False, "assets": [asset]}
    r.update(kw)
    return r


ASSET = selfupdate.pick_asset(release(), mac=False)


@pytest.fixture(autouse=True)
def windows_installer(monkeypatch):
    """These tests are about the Windows installer on any OS; tests/test_selfupdate_mac.py has the Mac's."""
    monkeypatch.setattr(selfupdate, "MAC", False)
    monkeypatch.setattr(updates, "NEED_INSTALLER", False)


class Resp(io.BytesIO):
    def __init__(self, body, url=CDN, status=200):
        super().__init__(body)
        self.url, self.status = url, status

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Server:
    """A fake GitHub download: honours Range unless told not to; can stop after n bytes."""

    def __init__(self, body=BLOB, url=CDN, ranges=True):
        self.body, self.url, self.ranges, self.reqs = body, url, ranges, []

    def __call__(self, req, timeout):
        self.reqs.append(req)
        rng = req.get_header("Range")
        if rng and self.ranges:
            start = int(rng.split("=")[1].rstrip("-"))
            return Resp(self.body[start:], self.url, 206)
        return Resp(self.body, self.url, 200)


def plenty(_):
    return 100 * 1024 ** 3


# ---------------- which file, from where ----------------
def test_pick_asset_takes_only_the_app_installer_of_this_release():
    assert ASSET == {"tag": TAG, "version": "1.19.0", "name": NAME, "size": len(BLOB), "sha256": SHA}


@pytest.mark.parametrize("bad", [
    {"tag_name": "gpu-runtime-1"},                                    # the GPU runtime release, not the app
    {"prerelease": True}, {"draft": True},
    {"asset": {"name": "Ecoscribe-Setup-1.18.0.exe"}},                # an installer of another version
    {"asset": {"name": "Ecoscribe-1.19.0.dmg"}},
    {"asset": {"browser_download_url": "https://github.com/someone/fork/releases/download/v1.19.0/" + NAME}},
    {"asset": {"browser_download_url": "http://github.com/ErikBros/ecoscribe/releases/download/v1.19.0/" + NAME}},
    {"asset": {"size": 1000}}, {"asset": {"size": "big"}}, {"asset": {"state": "starter"}},
])
def test_pick_asset_refuses_anything_else(bad):
    assert selfupdate.pick_asset(release(**bad)) is None


def test_pick_asset_without_a_digest_keeps_the_size_check():
    a = selfupdate.pick_asset(release(asset={"digest": None}))
    assert a and "sha256" not in a and a["size"] == len(BLOB)


def test_daily_check_saves_the_installer(tmp_path):
    def opener(req, timeout):
        return Resp(json.dumps(release()).encode(), url=updates.API_URL)
    st = updates.check(tmp_path, now=1.0, fetch=lambda: updates.fetch_release(opener=opener))
    assert st["latest"] == TAG and st["asset"] == ASSET


# ---------------- allowed? ----------------
def test_off_by_default_until_allowed(tmp_path):
    st = {"asset": ASSET}
    assert selfupdate.wanted(st, "1.18.0", auto=False) is None              # the switch is off by default
    assert selfupdate.wanted(st, "1.18.0", auto=True) == ASSET
    assert selfupdate.wanted({**st, "install": "1.19.0"}, "1.18.0", auto=False) == ASSET  # Home > Install now
    assert selfupdate.wanted({**st, "install": "1.18.5"}, "1.18.0", auto=False) is None
    assert selfupdate.wanted(st, "1.19.0", auto=True) is None               # already on it
    assert selfupdate.wanted({**st, "install_failed": "1.19.0"}, "1.18.0", auto=True) is None  # one try per version


def test_config_default_is_off():
    from ecoscribe.config import UiCfg
    assert UiCfg().auto_update is False


# ---------------- download ----------------
def test_download_checks_size_and_hash(tmp_path):
    srv = Server()
    p = selfupdate.download(tmp_path, ASSET, opener=srv, free=plenty)
    assert p == tmp_path / "updates" / NAME and p.read_bytes() == BLOB
    assert srv.reqs[0].full_url == URL  # built here, never a link from the answer
    st = updates.load(tmp_path)
    assert st["downloaded"] == {"version": "1.19.0", "name": NAME, "size": len(BLOB)} and not st.get("update_error")
    assert selfupdate.downloaded(tmp_path, st, ASSET) == p


def test_download_from_a_strange_host_is_refused(tmp_path):
    assert selfupdate.download(tmp_path, ASSET, opener=Server(url="https://evil.example/x.exe"), free=plenty) is None
    assert not (tmp_path / "updates" / NAME).exists()


def test_download_that_does_not_match_is_deleted(tmp_path):
    bad = BLOB[:-1] + b"\x00"
    assert selfupdate.download(tmp_path, ASSET, opener=Server(body=bad), free=plenty) is None
    assert list((tmp_path / "updates").iterdir()) == []
    assert "didn't match" in updates.load(tmp_path)["update_error"]


def test_download_larger_than_said_is_deleted(tmp_path):
    assert selfupdate.download(tmp_path, ASSET, opener=Server(body=BLOB + b"x" * 5), free=plenty) is None
    assert list((tmp_path / "updates").iterdir()) == []


def test_download_pauses_for_a_meeting_and_goes_on_later(tmp_path):
    looks = iter([False, False, True])  # a call starts during the 3rd chunk
    assert selfupdate.download(tmp_path, ASSET, opener=Server(), pause=lambda: next(looks, True), free=plenty) is None
    part = tmp_path / "updates" / (NAME + ".part")
    have = part.stat().st_size
    assert 0 < have < len(BLOB)
    srv = Server()
    p = selfupdate.download(tmp_path, ASSET, opener=srv, free=plenty)
    assert srv.reqs[0].get_header("Range") == f"bytes={have}-"
    assert p.read_bytes() == BLOB and not part.exists()


def test_download_restarts_when_the_server_ignores_the_range(tmp_path):
    part = tmp_path / "updates" / (NAME + ".part")
    part.parent.mkdir()
    part.write_bytes(BLOB[:1000])
    p = selfupdate.download(tmp_path, ASSET, opener=Server(ranges=False), free=plenty)
    assert p.read_bytes() == BLOB


def test_download_waits_for_disk_space(tmp_path):
    srv = Server()
    assert selfupdate.download(tmp_path, ASSET, opener=srv, free=lambda _: len(BLOB)) is None
    assert srv.reqs == [] and "disk space" in updates.load(tmp_path)["update_error"]


def test_download_offline_is_quiet(tmp_path):
    def opener(req, timeout):
        raise OSError("offline")
    assert selfupdate.download(tmp_path, ASSET, opener=opener, free=plenty) is None


def _raises(e):
    def opener(req, timeout):
        raise e
    return opener


class _FullDisk(Server):
    def __call__(self, req, timeout):
        r = super().__call__(req, timeout)
        r.read = lambda n=-1: (_ for _ in ()).throw(OSError(errno.ENOSPC, "No space left on device", "C:\\x"))
        return r


@pytest.mark.parametrize("opener,free,says", [
    (_raises(urllib.error.URLError(OSError(11001, "getaddrinfo failed"))), plenty, "no connection"),
    (_raises(ConnectionResetError(10054, "[WinError 10054] An existing connection was forcibly closed")), plenty,
     "no connection"),
    (_raises(OSError(errno.EACCES, "[Errno 13] Permission denied: 'C:\\\\x'")), plenty, "failed"),
    (_raises(TimeoutError("timed out")), plenty, "too long"),
    (_raises(urllib.error.HTTPError(URL, 404, "Not Found", {}, None)), plenty, "error 404"),
    (_FullDisk(), plenty, "disk is full"),
    (Server(), lambda _: len(BLOB), "free disk space"),               # short of disk before it starts
    (Server(body=BLOB[:-1] + b"\x00"), plenty, "didn't match"),        # a bad checksum
])
def test_a_failed_download_says_why_in_plain_words(tmp_path, opener, free, says):
    """dictado-9zeo.1 (D5): Home says why the download stopped, never the exception's own text."""
    assert selfupdate.download(tmp_path, ASSET, opener=opener, free=free) is None
    err = updates.load(tmp_path)["update_error"]
    assert err.startswith("The download stopped: ") and err.endswith(".") and says in err
    for raw in ("Errno", "urlopen", "Traceback", "<", "WinError", "getaddrinfo", "No space left"):
        assert raw not in err


# ---------------- never during a call ----------------
@pytest.mark.parametrize("meetings,busy,why", [
    ({"meeting": {"status": "recording"}}, False, "recording or saving"),
    ({"meeting": {"status": "finalizing"}}, False, "recording or saving"),
    ({"next_meeting": {"status": "waiting"}}, False, "waiting"),
    ({"job": {"kind": "transcribe"}}, False, "job"),
    ({"job": {"kind": "speakers"}}, False, "job"),
    ({"queue": ["x"]}, False, "queued"),
    (IDLE, True, "dictation"),
])
def test_blockers(meetings, busy, why):
    out = selfupdate.blockers(meetings, busy)
    assert out and why in " ".join(out)


def test_nothing_busy_is_safe():
    assert selfupdate.blockers(IDLE, False) == [] and selfupdate.blockers({}, False) == []


class Box:
    """The background app as the updater sees it."""

    def __init__(self, tmp_path, auto=True):
        self.data = tmp_path
        self.meetings, self.busy, self.now, self.wall = dict(IDLE), False, 10_000.0, 1_800_000_000.0
        self.installs, self.opened, self.srv = [], [], Server()
        self.up = selfupdate.SelfUpdater(
            tmp_path, "1.18.0", auto=lambda: auto, meetings=lambda: self.meetings, app_busy=lambda: self.busy,
            install=lambda p, a, r: self.installs.append((p, a, r)), on_ready=self.opened.append,
            opener=self.srv, clock=lambda: self.now, wall=lambda: self.wall, free=plenty, supported=True)
        updates._update(tmp_path, latest=TAG, asset=ASSET, checked_at=1.0)

    def state(self):
        return selfupdate.home_state(updates.load(self.data), "1.18.0", auto=True, supported=True)


CALL = {**IDLE, "meeting": {"status": "recording"}}


def test_tick_never_installs_without_request(tmp_path):
    """dictado-9zeo.1 (point 5): no install by itself while the app is in use, however long nobody touches it."""
    b = Box(tmp_path)
    b.meetings = dict(CALL)
    assert b.up.tick() == "waiting: a meeting" and b.srv.reqs == []  # no download during a call
    b.meetings = dict(IDLE)
    assert b.up.tick() == "downloaded"
    for _ in range(30):  # half an hour of quiet minutes: still only the offer
        b.now += 60
        assert b.up.tick() in ("ready", "ask") and b.installs == []
    assert not [n for n in dir(selfupdate) if "idle" in n.lower()]  # no idle install, no keyboard watch


def test_installs_within_the_tick_after_a_request(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    assert selfupdate.request_install(tmp_path, "1.19.0")
    assert b.state()["install"] == "installing"  # the window shows the Installing screen at once
    assert b.up.tick() == "installing"
    [(p, a, relaunch)] = b.installs
    assert p.name == NAME and a == ASSET and relaunch is True
    assert b.up.tick() == "installing" and len(b.installs) == 1  # handed over once


def test_a_request_during_a_call_waits_and_installs_when_the_call_ends(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    selfupdate.request_install(tmp_path, "1.19.0")
    b.meetings = dict(CALL)  # a call started between the press and the look
    assert b.up.tick() == "waiting: busy" and b.installs == []
    st = b.state()
    assert st["blocked"] == "call" and st["install"] == "ready" and not st.get("ask")  # "Finish the call first"
    b.now += 60
    assert b.up.tick() == "waiting: busy" and b.installs == []
    b.meetings = dict(IDLE)  # the call ended
    assert b.up.tick() == "installing" and len(b.installs) == 1
    assert "blocked" not in b.state()


@pytest.mark.parametrize("meetings,busy", [
    ({**IDLE, "meeting": {"status": "finalizing"}}, False),   # a meeting saving
    ({**IDLE, "job": {"kind": "transcribe"}}, False),         # a file job
    ({**IDLE, "job": {"kind": "speakers"}}, False),           # telling the speakers apart
    ({**IDLE, "queue": ["x"]}, False),                       # jobs queued
    (dict(IDLE), True),                                      # a dictation recording or being transcribed
])
def test_other_blockers_hold_a_request_only_until_they_clear(tmp_path, meetings, busy):
    """dictado-9zeo.1 (criterion 19): behind the Installing screen, installed on the first look after they end."""
    b = Box(tmp_path)
    b.up.tick()
    selfupdate.request_install(tmp_path, "1.19.0")
    b.meetings, b.busy = meetings, busy
    assert b.up.tick() == "waiting: busy" and b.installs == []
    st = b.state()
    assert st["install"] == "installing" and "blocked" not in st  # not a call: the Installing screen stays up
    assert st["waiting"] == "busy"  # and says it waits for the work in progress
    b.meetings, b.busy = dict(IDLE), False
    assert b.up.tick() == "installing" and len(b.installs) == 1


def test_install_now_in_the_offer_state_downloads_then_installs_without_asking(tmp_path):
    """D2: Home's Install now with nothing downloaded: the download runs, no pop-up, the install starts on the
    tick the download completes."""
    b = Box(tmp_path, auto=False)
    assert b.up.tick() == "nothing"
    assert selfupdate.home_state(updates.load(tmp_path), "1.18.0", auto=False, supported=True) == {"install": "offer"}
    selfupdate.request_install(tmp_path, "1.19.0")
    st = selfupdate.home_state(updates.load(tmp_path), "1.18.0", auto=False, supported=True)
    assert st["install"] == "downloading" and st["pressed"] and not st.get("ask")
    assert b.up.tick() == "installing" and len(b.installs) == 1 and len(b.srv.reqs) == 1
    assert b.opened == []  # no pop-up: the user already said now


def test_download_done_opens_the_window_for_the_popup_once(tmp_path):
    """D1: the window opens on Home when the download is done; never twice for one version."""
    b = Box(tmp_path)
    assert b.up.tick() == "downloaded" and b.opened == ["1.19.0"]
    st = b.state()
    assert st["install"] == "ready" and st["ask"] is True
    for _ in range(3):
        assert b.up.tick() == "ready"
    assert b.opened == ["1.19.0"] and b.installs == []


@pytest.mark.parametrize("meetings,busy", [(CALL, False), ({**IDLE, "next_meeting": {"status": "waiting"}}, False),
                                           (dict(IDLE), True)])
def test_the_popup_waits_for_a_dictation_or_a_call(tmp_path, meetings, busy):
    b = Box(tmp_path)
    b.up.tick()  # downloaded, but the pop-up comes now; make a fresh version wait instead
    updates._update(tmp_path, popup_shown=None)
    b.meetings, b.busy = meetings, busy
    b.opened.clear()
    assert b.up.tick() == "ready: the pop-up waits" and b.opened == []
    b.meetings, b.busy = dict(IDLE), False
    assert b.up.tick() == "ask" and b.opened == ["1.19.0"]
    assert b.up.tick() == "ready" and b.opened == ["1.19.0"]


def test_later_closes_the_popup_for_that_version_for_good(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    assert selfupdate.later(tmp_path, "1.19.0") and not selfupdate.later(tmp_path, "<junk>")
    st = b.state()
    assert st["install"] == "ready" and "ask" not in st  # Home keeps Install now
    newer = {**updates.load(tmp_path), "asset": {**ASSET, "version": "1.20.0", "name": "Ecoscribe-Setup-1.20.0.exe"},
             "downloaded": {"version": "1.20.0", "name": "Ecoscribe-Setup-1.20.0.exe", "size": len(BLOB)}}
    assert selfupdate.home_state(newer, "1.18.0", auto=True, supported=True)["ask"] is True  # a newer one asks again


def test_a_failed_download_sets_error_and_retry_at_and_a_press_retries_at_once(tmp_path):
    b = Box(tmp_path)
    b.srv.body = BLOB[:-1] + b"\x00"  # a file that doesn't match
    assert b.up.tick() == "downloading"
    st = updates.load(tmp_path)
    assert st["retry_at"] == b.wall + selfupdate.RETRY_S and "didn't match" in st["update_error"]
    home = b.state()
    assert home["install"] == "downloading" and home["retry_at"] == st["retry_at"] and "didn't match" in home["error"]
    b.now += 60
    assert b.up.tick() == "waiting: try the download again later" and len(b.srv.reqs) == 1
    b.srv.body = BLOB
    selfupdate.request_install(tmp_path, "1.19.0")  # Install now: no 30-minute wait
    assert "error" not in b.state()
    assert b.up.tick() == "installing" and len(b.srv.reqs) == 2
    assert not updates.load(tmp_path).get("retry_at")


def test_a_press_and_the_minute_loop_never_run_two_downloads(tmp_path):
    """Criterion 18: the minute loop is mid-download when the press comes; the guard is SelfUpdater._lock."""
    b = Box(tmp_path)
    gate, inside = threading.Event(), threading.Event()

    class Slow(Server):
        def __call__(self, req, timeout):
            r = super().__call__(req, timeout)
            first = r.read

            def read(n=-1):
                inside.set()
                gate.wait(5)
                return first(n)
            r.read = read
            return r
    b.up.opener = srv = Slow()
    t = threading.Thread(target=lambda: b.up.tick())
    t.start()
    assert inside.wait(5)
    selfupdate.request_install(tmp_path, "1.19.0")
    w = selfupdate.PressWatcher(tmp_path, b.up)
    assert w.look() == "busy: another look is running"
    gate.set()
    t.join(5)
    assert w.look() == "installing"
    assert len(srv.reqs) == 1 and len(b.installs) == 1
    assert [p.name for p in (tmp_path / "updates").iterdir()] == [NAME]


def test_start_install_not_now_keeps_the_request(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    selfupdate.request_install(tmp_path, "1.19.0")
    assert b.up.tick() == "installing"
    (p, a, r), = b.installs
    pending, quits = [], []
    b.busy = True  # a dictation started between the look and the main thread
    assert not b.up.start_install(p, a, r, pending, lambda: quits.append(1))
    assert pending == [] and quits == [] and updates.load(tmp_path)["install_now"] == "1.19.0"
    b.busy = False
    assert b.up.tick() == "installing" and len(b.installs) == 2  # the next look tries again
    assert b.up.start_install(p, a, r, pending, lambda: quits.append(1)) and pending == [(p, a, r)] and quits == [1]
    assert not b.up.start_install(p, a, r, pending, lambda: quits.append(1)) and quits == [1]  # once


def test_a_failed_installer_start_clears_the_installing_state(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    selfupdate.request_install(tmp_path, "1.19.0")
    p = tmp_path / "updates" / NAME

    def broken(args):
        raise OSError("can't start")
    assert not selfupdate.run_installer(tmp_path, p, ASSET, relaunch=True, popen=broken)
    st = updates.load(tmp_path)
    assert not st.get("install_now") and b.state()["install"] == "ready"  # the overlay leaves; used once
    b2 = Box(tmp_path)  # the app started again: the press is not acted on again
    assert b2.up.tick() == "ready" and b2.installs == []


def test_a_bad_file_at_install_time_clears_the_installing_state(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    selfupdate.request_install(tmp_path, "1.19.0")
    (tmp_path / "updates" / NAME).write_bytes(BLOB[:-1] + b"\x02")
    assert b.up.tick() == "bad file" and b.installs == []
    st = b.state()
    assert st["install"] == "downloading" and not st.get("pressed")


def test_after_install_failed_the_request_is_not_acted_on(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    updates._update(tmp_path, install_failed="1.19.0", install_now="1.19.0")
    assert b.up.tick() == "nothing" and b.installs == [] and b.state() == {"install": "failed"}


def test_a_new_start_forgets_a_press(tmp_path):
    selfupdate.request_install(tmp_path, "1.19.0")
    updates._update(tmp_path, install_wait="call")
    selfupdate.after_start(tmp_path, "1.18.0")
    st = updates.load(tmp_path)
    assert not st.get("install_now") and not st.get("install_wait") and st["install"] == "1.19.0"


def test_a_failed_download_waits_before_the_next_try(tmp_path):
    b = Box(tmp_path)
    b.srv.body = BLOB[:-1] + b"\x00"  # a file that doesn't match
    assert b.up.tick() == "downloading" and len(b.srv.reqs) == 1
    b.now += 60
    assert b.up.tick() == "waiting: try the download again later" and len(b.srv.reqs) == 1  # not every minute
    b.now += selfupdate.RETRY_S
    b.srv.body = BLOB
    assert b.up.tick() == "downloaded" and len(b.srv.reqs) == 2


def test_a_changed_file_is_never_handed_to_the_installer(tmp_path):
    b = Box(tmp_path)
    b.up.tick()
    (tmp_path / "updates" / NAME).write_bytes(BLOB[:-1] + b"\x02")  # same size, other bytes
    selfupdate.request_install(tmp_path, "1.19.0")  # installs only after a press (dictado-9zeo.1)
    assert b.up.tick() == "bad file" and b.installs == [] and not (tmp_path / "updates" / NAME).exists()


def test_updater_does_nothing_when_not_allowed(tmp_path):
    b = Box(tmp_path, auto=False)
    assert b.up.tick() == "nothing" and b.srv.reqs == []
    selfupdate.request_install(tmp_path, "1.19.0")  # Home > Install now
    assert b.up.tick() == "installing"


def test_updater_off_on_other_platforms(tmp_path):
    b = Box(tmp_path)
    b.up.supported = False
    assert b.up.tick() == "unsupported" and b.up.at_quit() is None and b.srv.reqs == []


def test_at_quit_only_when_ready_and_nothing_busy(tmp_path):
    b = Box(tmp_path)
    assert b.up.at_quit() is None  # not downloaded yet
    b.up.tick()
    b.meetings = {**IDLE, "meeting": {"status": "recording"}}
    assert b.up.at_quit() is None  # quitting during a call: the call saves, no install
    b.meetings = dict(IDLE)
    p, a = b.up.at_quit()
    assert p.name == NAME and a == ASSET


def test_at_quit_while_downloading_says_so(tmp_path, caplog):
    """Point 7 / D4: a Quit before the download is done is never a silent skip."""
    b = Box(tmp_path)
    with caplog.at_level(logging.WARNING, logger="ecoscribe.selfupdate"):
        assert b.up.at_quit() is None
    assert any("quit before 1.19.0 finished downloading" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records)
    assert updates.load(tmp_path)["quit_skipped"] == {"version": "1.19.0", "why": "downloading"}
    assert b.state()["quit"] == "downloading"


def test_at_quit_ready_but_busy_says_so(tmp_path, caplog):
    b = Box(tmp_path)
    b.up.tick()
    b.meetings = {**IDLE, "meeting": {"status": "finalizing"}}
    with caplog.at_level(logging.WARNING, logger="ecoscribe.selfupdate"):
        assert b.up.at_quit() is None
    assert any("ready but wasn't installed at quit" in r.getMessage() for r in caplog.records)
    st = b.state()
    assert st["quit"] == "busy" and st["install"] == "ready"


# ---------------- running the installer (a fake process start) ----------------
def test_run_installer_checks_the_file_and_starts_it(tmp_path):
    p = selfupdate.download(tmp_path, ASSET, opener=Server(), free=plenty)
    started = []
    assert selfupdate.run_installer(tmp_path, p, ASSET, relaunch=True, popen=started.append, now=5.0)
    [args] = started
    # Install now (dictado-9zeo.1): Setup's own progress window, then the new version opens on Home
    assert args[0] == str(p) and {"/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/OPENHOME=1"} <= set(args)
    assert "/VERYSILENT" not in args and "/LAUNCH=0" not in args and any(a.startswith("/LOG=") for a in args)
    assert updates.load(tmp_path)["install_started"] == {"version": "1.19.0", "at": 5.0}
    started.clear()
    selfupdate.run_installer(tmp_path, p, ASSET, relaunch=False, popen=started.append)
    assert {"/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LAUNCH=0"} <= set(started[0])  # at Quit: unseen, closed
    assert "/SILENT" not in started[0] and "/OPENHOME=1" not in started[0]


def test_run_installer_refuses_a_changed_file(tmp_path):
    p = selfupdate.download(tmp_path, ASSET, opener=Server(), free=plenty)
    p.write_bytes(BLOB[:-1] + b"\x01")
    started = []
    assert not selfupdate.run_installer(tmp_path, p, ASSET, relaunch=True, popen=started.append)
    assert started == [] and not p.exists() and updates.load(tmp_path)["downloaded"] is None


def test_after_start_tidies_up_a_good_install(tmp_path):
    p = selfupdate.download(tmp_path, ASSET, opener=Server(), free=plenty)
    selfupdate.run_installer(tmp_path, p, ASSET, relaunch=True, popen=lambda a: None)
    selfupdate.after_start(tmp_path, "1.19.0")  # the new version started
    st = updates.load(tmp_path)
    assert not p.exists() and not st.get("install_started") and not st.get("downloaded")


def test_after_start_one_try_per_version(tmp_path):
    updates._update(tmp_path, latest=TAG, asset=ASSET)
    p = selfupdate.download(tmp_path, ASSET, opener=Server(), free=plenty)
    selfupdate.run_installer(tmp_path, p, ASSET, relaunch=True, popen=lambda a: None)
    selfupdate.after_start(tmp_path, "1.18.0")  # the old version again: the install didn't happen
    st = updates.load(tmp_path)
    assert not p.exists()  # the installer isn't left on the disk
    assert st["install_failed"] == "1.19.0" and selfupdate.wanted(st, "1.18.0", auto=True) is None
    assert selfupdate.home_state(st, "1.18.0", auto=True, supported=True) == {"install": "failed"}


def test_installer_script_honours_launch_0():
    iss = (Path(__file__).resolve().parent.parent / "packaging" / "windows" / "ecoscribe.iss").read_text(encoding="utf-8")
    assert "Check: ShouldLaunch" in iss and "{param:LAUNCH|1}" in iss
    assert "MeetingDone" in iss  # the installer's own refusal while a meeting worker is alive stays


def test_installer_script_shows_progress_without_cancel_and_opens_home_after_install_now():
    """dictado-9zeo.1: /SILENT shows Setup's progress (Cancel off); /OPENHOME=1 starts the new version on Home."""
    iss = (Path(__file__).resolve().parent.parent / "packaging" / "windows" / "ecoscribe.iss").read_text(encoding="utf-8")
    assert "AllowCancelDuringInstall=no" in iss
    run = [ln for ln in iss.split("[Run]", 1)[1].split("\n[", 1)[0].splitlines() if "Ecoscribe.exe" in ln]
    assert len(run) == 1 and "skipifsilent" not in run[0] and "{code:LaunchParams}" in run[0]
    assert "{param:OPENHOME|0}" in iss and "'--after-update'" in iss and selfupdate.AFTER_UPDATE == "--after-update"


# ---------------- Home row and Settings ----------------
def test_home_state_steps():
    st = {"asset": ASSET, "latest": TAG}
    assert selfupdate.home_state(st, "1.18.0", auto=False, supported=False) == {}
    assert selfupdate.home_state(st, "1.18.0", auto=False, supported=True) == {"install": "offer"}
    assert selfupdate.home_state({**st, "install": "1.19.0", "update_progress": 42}, "1.18.0", False, True) == {
        "install": "downloading", "pct": 42}
    st["downloaded"] = {"version": "1.19.0", "name": NAME, "size": len(BLOB)}
    assert selfupdate.home_state(st, "1.18.0", auto=True, supported=True) == {"install": "ready", "ask": True}
    assert selfupdate.home_state({**st, "asked": "1.19.0"}, "1.18.0", True, True) == {"install": "ready"}
    assert selfupdate.home_state({**st, "install_now": "1.19.0"}, "1.18.0", True, True) == {"install": "installing"}
    assert selfupdate.home_state({**st, "install_now": "1.19.0", "install_wait": "call"}, "1.18.0", True, True) == {
        "install": "ready", "blocked": "call"}
    assert selfupdate.home_state({**st, "install_started": {"version": "1.19.0", "at": 1}}, "1.18.0", True, True) == {
        "install": "installing"}


class _NoStartup:
    def app_command(self):
        return None

    def is_enabled(self):
        return False


@pytest.fixture
def api(tmp_path, monkeypatch):
    a = Api(data_dir=tmp_path / "data", config_path=tmp_path / "cfg" / "config.toml",
            startup_mod=_NoStartup(), signal_reload=lambda: True, list_mic_names=lambda: [], open_url=lambda u: None)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("ecoscribe.window.__version__", "1.18.0")
    monkeypatch.setattr(selfupdate, "SUPPORTED", True)
    updates._update(a._data_dir, latest=TAG, asset=ASSET, checked_at=1.0)
    return a


def test_window_offers_install_now(api):
    n = api.update_notice()
    assert n["version"] == "1.19.0" and n["install"] == "offer"
    assert api.install_update_now("1.19.0") == {"ok": True}
    n = api.update_notice()
    assert n["install"] == "downloading" and n["pressed"] is True
    assert api.install_update_now("<junk>") == {"ok": False}
    assert not hasattr(api, "install_update_when_idle")


def test_window_install_now_during_a_call_says_finish_the_call_first(api):
    (api._data_dir / "meetings.json").write_text(json.dumps({**IDLE, "meeting": {"status": "recording"}}))
    assert api.update_notice()["in_call"] is True
    assert api.install_update_now("1.19.0") == {"ok": False, "blocked": "call"}
    assert not updates.load(api._data_dir).get("install_now")  # offered again when the call ends
    (api._data_dir / "meetings.json").write_text(json.dumps(IDLE))
    assert api.update_notice()["in_call"] is False
    assert api.install_update_now("1.19.0") == {"ok": True}


def test_window_later_and_the_quit_note_once(api):
    updates._update(api._data_dir, downloaded={"version": "1.19.0", "name": NAME, "size": len(BLOB)},
                    install="1.19.0", quit_skipped={"version": "1.19.0", "why": "busy"})
    n = api.update_notice()
    assert n["install"] == "ready" and n["ask"] is True and n["quit"] == "busy"
    assert "quit" not in api.update_notice()  # said once
    assert api.update_later("1.19.0") == {"ok": True}
    assert "ask" not in api.update_notice()


def test_settings_switch_off_by_default_and_saved(api):
    s = api.get_settings()
    assert s["values"]["auto_update"] is False and "auto_update_supported" in s
    assert api.save_settings({"auto_update": True})["ok"]
    assert api.get_settings()["values"]["auto_update"] is True
    assert api.update_notice()["install"] == "downloading"  # on: no need to ask on Home


# ---------------- the press reaches the background app (dictado-9zeo.1) ----------------
def test_the_press_reaches_the_watcher_main_wires_within_two_seconds(tmp_path, api):
    """Criterion 4: the window writes the press; PressWatcher (started in __main__) hands it to the installer,
    with the minute loop not running. Same object on Windows and the Mac (a file, no named event)."""
    b = Box(api._data_dir)
    b.up.tick()  # downloaded, checked
    calls = []
    b.up.install = lambda p, a, r: calls.append(time.monotonic())
    w = selfupdate.PressWatcher(api._data_dir, b.up, every=0.2)
    w.start()
    try:
        t0 = time.monotonic()
        assert api.install_update_now("1.19.0")["ok"] is True
        while not calls and time.monotonic() - t0 < 3:
            time.sleep(0.05)
    finally:
        w.stop()
    assert calls and calls[0] - t0 < 2.0
    main = (Path(__file__).resolve().parent.parent / "ecoscribe" / "__main__.py").read_text(encoding="utf-8")
    assert "selfupdate.PressWatcher(" in main


def test_after_update_flag_opens_home_and_nothing_else_does():
    """Criterion 16: only the start right after an Install now opens the window (on Home)."""
    from ecoscribe import __main__ as entry
    opened = []
    assert entry.open_after_update(entry.parse(["--after-update"]), opened.append) and opened == ["inicio"]
    for argv in ([], ["--restarted"], ["--restarted", "--after-crash", "x.txt"]):  # Run key / login item, watchdog
        assert not entry.open_after_update(entry.parse(argv), opened.append)
    assert opened == ["inicio"]
    assert entry.again_args(["--config", "c.toml", "--after-update", "--restarted"]) == ["--config", "c.toml"]


def test_the_flag_is_only_in_the_install_now_paths():
    root = Path(__file__).resolve().parent.parent
    main = (root / "ecoscribe" / "__main__.py").read_text(encoding="utf-8")
    assert "open_after_update(args, ipc.open_ui)" in main
    sup = (root / "ecoscribe" / "supervise.py").read_text(encoding="utf-8")
    assert "after-update" not in sup and "after_update" not in sup  # a watchdog restart opens nothing


def test_show_ui_keeps_an_open_window_on_its_page(monkeypatch):
    """Criterion 2: the pop-up shows over the page the user is on; a closed window opens on Home."""
    from ecoscribe import ipc
    spawned, asked = [], []
    monkeypatch.setattr(ipc, "spawn", spawned.append)
    monkeypatch.setattr(ipc, "ask_page", asked.append)
    monkeypatch.setattr(ipc, "focus_ui", lambda: True)
    ipc.show_ui("inicio")
    assert spawned == [] and asked == []  # focused only: the page (and unsaved Settings) stay
    monkeypatch.setattr(ipc, "focus_ui", lambda: False)
    ipc.show_ui("inicio")
    assert spawned == [["--ui", "--page", "inicio"]]


def test_no_update_text_tells_people_to_step_away_or_quit():
    """dictado-9zeo.1 (points 5, 6): the texts say what happens and what to press; no idle install, no call rule
    unless a call actually blocks the button, no "quit to update"."""
    root = Path(__file__).resolve().parent.parent
    bad = ("step away", "never during a call", "install when idle", "when idle", "or quit", "quit ecoscribe",
           "install by itself")
    for f in ("ecoscribe/web/app.js", "ecoscribe/web/index.html"):
        text = (root / f).read_text(encoding="utf-8").lower()
        assert not [b for b in bad if b in text], f
