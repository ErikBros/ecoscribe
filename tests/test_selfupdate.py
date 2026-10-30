"""dictado-nmo: self-update that never runs during a call. Fakes everywhere: no network, no real
installer is ever started, the installed app is never touched."""
import hashlib
import io
import json
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
    assert selfupdate.wanted({**st, "install": "1.19.0"}, "1.18.0", auto=False) == ASSET  # Home > Install when idle
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
        self.meetings, self.busy, self.last, self.away, self.now = dict(IDLE), False, None, 3600.0, 10_000.0
        self.installs, self.srv = [], Server()
        self.up = selfupdate.SelfUpdater(
            tmp_path, "1.18.0", auto=lambda: auto, meetings=lambda: self.meetings, app_busy=lambda: self.busy,
            last_dictation=lambda: self.last, install=lambda p, a, r: self.installs.append((p, a, r)),
            input_idle=lambda: self.away, opener=self.srv, clock=lambda: self.now, free=plenty, supported=True)
        updates._update(tmp_path, latest=TAG, asset=ASSET, checked_at=1.0)


def test_updater_gets_it_then_installs_only_when_idle_and_safe(tmp_path):
    b = Box(tmp_path)
    b.meetings = {**IDLE, "meeting": {"status": "recording"}}
    assert b.up.tick() == "waiting: a meeting" and b.srv.reqs == []  # no download during a call
    b.meetings = dict(IDLE)
    assert b.up.tick() == "downloaded"
    b.meetings = {**IDLE, "meeting": {"status": "recording"}}
    assert b.up.tick() == "waiting: busy" and b.installs == []        # never during a call
    b.meetings = {**IDLE, "job": {"kind": "transcribe"}}
    assert b.up.tick() == "waiting: busy" and b.installs == []        # nor while a meeting is processed
    b.meetings, b.busy = dict(IDLE), True
    assert b.up.tick() == "waiting: busy" and b.installs == []        # nor while dictating
    b.busy, b.last = False, b.now - 60
    assert b.up.tick() == "waiting: not idle"                         # dictated a minute ago
    b.last, b.away = b.now - 3600, 30.0
    assert b.up.tick() == "waiting: not idle"                         # someone is at the keyboard
    b.away = None
    assert b.up.tick() == "waiting: not idle"                         # can't tell: not idle
    b.away = selfupdate.IDLE_S
    assert b.up.tick() == "installing"
    [(p, a, relaunch)] = b.installs
    assert p.name == NAME and a == ASSET and relaunch is True


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
    assert b.up.tick() == "bad file" and b.installs == [] and not (tmp_path / "updates" / NAME).exists()


def test_updater_does_nothing_when_not_allowed(tmp_path):
    b = Box(tmp_path, auto=False)
    assert b.up.tick() == "nothing" and b.srv.reqs == []
    selfupdate.allow_once(tmp_path, "1.19.0")  # Home > Install when idle
    assert b.up.tick() == "downloaded"


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


# ---------------- running the installer (a fake process start) ----------------
def test_run_installer_checks_the_file_and_starts_it_silently(tmp_path):
    p = selfupdate.download(tmp_path, ASSET, opener=Server(), free=plenty)
    started = []
    assert selfupdate.run_installer(tmp_path, p, ASSET, relaunch=True, popen=started.append, now=5.0)
    [args] = started
    assert args[0] == str(p) and {"/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"} <= set(args)
    assert "/LAUNCH=0" not in args and any(a.startswith("/LOG=") for a in args)
    assert updates.load(tmp_path)["install_started"] == {"version": "1.19.0", "at": 5.0}
    started.clear()
    selfupdate.run_installer(tmp_path, p, ASSET, relaunch=False, popen=started.append)
    assert "/LAUNCH=0" in started[0]  # at Quit: stays closed


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


# ---------------- Home row and Settings ----------------
def test_home_state_steps():
    st = {"asset": ASSET, "latest": TAG}
    assert selfupdate.home_state(st, "1.18.0", auto=False, supported=False) == {}
    assert selfupdate.home_state(st, "1.18.0", auto=False, supported=True) == {"install": "offer"}
    assert selfupdate.home_state({**st, "install": "1.19.0", "update_progress": 42}, "1.18.0", False, True) == {
        "install": "downloading", "pct": 42}
    st["downloaded"] = {"version": "1.19.0", "name": NAME, "size": len(BLOB)}
    assert selfupdate.home_state(st, "1.18.0", auto=True, supported=True) == {"install": "ready"}


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


def test_window_offers_install_when_idle(api):
    n = api.update_notice()
    assert n["version"] == "1.19.0" and n["install"] == "offer"
    assert api.install_update_when_idle("1.19.0") == {"ok": True}
    assert api.update_notice()["install"] == "downloading"
    assert api.install_update_when_idle("<junk>") == {"ok": False}


def test_settings_switch_off_by_default_and_saved(api):
    s = api.get_settings()
    assert s["values"]["auto_update"] is False and "auto_update_supported" in s
    assert api.save_settings({"auto_update": True})["ok"]
    assert api.get_settings()["values"]["auto_update"] is True
    assert api.update_notice()["install"] == "downloading"  # on: no need to ask on Home
