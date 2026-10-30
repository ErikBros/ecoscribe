"""dictado-cjk: the daily "is a newer version out?" check. No network: a fake fetch everywhere."""
import io
import json
import urllib.error

import pytest

from ecoscribe import updates
from ecoscribe.window import Api

DAY = updates.EVERY_S


@pytest.fixture(autouse=True)
def any_release(monkeypatch):
    """Announced whatever its files (the Mac's "only with a .dmg": tests/test_selfupdate_mac.py)."""
    monkeypatch.setattr(updates, "NEED_INSTALLER", False)


class Fetch:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.answers.pop(0) if self.answers else None


@pytest.mark.parametrize("tag,want", [("v1.18.0", (1, 18, 0)), ("1.18.2", (1, 18, 2)), ("v2.0", (2, 0, 0)),
                                      (" v1.9.10 ", (1, 9, 10)), ("v1.18.0-beta", None), ("latest", None),
                                      ("", None), (None, None), ("v1", None)])
def test_parse(tag, want):
    assert updates.parse(tag) == want


@pytest.mark.parametrize("latest,current,want", [
    ("v1.18.0", "1.17.0", True), ("v1.17.10", "1.17.9", True),   # numbers, not text: 10 > 9
    ("v1.17.0", "1.17.0", False), ("v1.16.5", "1.17.0", False),  # same or older: nothing to say
    ("v2.0", "1.99.99", True), ("junk", "1.17.0", False), ("v1.18.0", "dev", False)])
def test_is_newer(latest, current, want):
    assert updates.is_newer(latest, current) is want


def test_first_check_asks_and_saves(tmp_path):
    f = Fetch("v1.18.0")
    st = updates.check(tmp_path, now=1000.0, fetch=f)
    assert f.calls == 1 and st["latest"] == "v1.18.0" and st["checked_at"] == 1000.0
    assert updates.load(tmp_path) == st


def test_once_a_day_at_most(tmp_path):
    f = Fetch("v1.18.0", "v1.19.0")
    updates.check(tmp_path, now=1000.0, fetch=f)
    updates.check(tmp_path, now=1000.0 + DAY - 1, fetch=f)  # same day: no second ask
    assert f.calls == 1
    st = updates.check(tmp_path, now=1000.0 + DAY, fetch=f)
    assert f.calls == 2 and st["latest"] == "v1.19.0"


def test_clock_set_back_asks_again(tmp_path):
    f = Fetch("v1.18.0", "v1.18.0")
    updates.check(tmp_path, now=10 * DAY, fetch=f)
    updates.check(tmp_path, now=DAY, fetch=f)
    assert f.calls == 2


def test_network_failure_keeps_last_known_and_waits_a_day(tmp_path):
    f = Fetch("v1.18.0", None)
    updates.check(tmp_path, now=1000.0, fetch=f)
    st = updates.check(tmp_path, now=1000.0 + DAY, fetch=f)  # offline: None
    assert st["latest"] == "v1.18.0" and st["checked_at"] == 1000.0 + DAY
    updates.check(tmp_path, now=1000.0 + DAY + 60, fetch=f)  # a failed ask counts: not again today
    assert f.calls == 2


def test_notice_shows_newer_hides_same_or_older():
    assert updates.notice({"latest": "v1.18.0"}, "1.17.0") == {
        "version": "1.18.0", "url": "https://github.com/ErikBros/ecoscribe/releases/tag/v1.18.0"}
    assert updates.notice({"latest": "v1.17.0"}, "1.17.0") is None
    assert updates.notice({}, "1.17.0") is None


def test_dismissed_hides_until_a_newer_one(tmp_path):
    updates.check(tmp_path, now=1.0, fetch=Fetch("v1.18.0"))
    assert updates.notice(updates.load(tmp_path), "1.17.0")
    updates.dismiss(tmp_path, "1.18.0")
    st = updates.load(tmp_path)
    assert st["dismissed"] == "1.18.0" and st["latest"] == "v1.18.0"  # the check's keys kept
    assert updates.notice(st, "1.17.0") is None
    updates.check(tmp_path, now=1.0 + DAY, fetch=Fetch("v1.18.1"))
    assert updates.notice(updates.load(tmp_path), "1.17.0")["version"] == "1.18.1"
    assert updates.load(tmp_path)["dismissed"] == "1.18.0"  # the check doesn't undo a dismiss


def test_dismiss_ignores_junk(tmp_path):
    updates.dismiss(tmp_path, "<script>")
    assert updates.load(tmp_path) == {}


def test_broken_state_file_is_a_fresh_start(tmp_path):
    (tmp_path / updates.STATE).write_text("{not json", encoding="utf-8")
    assert updates.load(tmp_path) == {}
    assert updates.check(tmp_path, now=5.0, fetch=Fetch("v1.18.0"))["latest"] == "v1.18.0"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_latest_reads_the_tag_and_sends_a_user_agent():
    seen = {}

    def opener(req, timeout):
        seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        return _Resp(json.dumps({"tag_name": "v1.18.0", "html_url": "https://example.invalid/x"}).encode())
    assert updates.fetch_latest(opener=opener) == "v1.18.0"
    assert seen["url"] == updates.API_URL and seen["ua"] and seen["timeout"] <= 10


@pytest.mark.parametrize("fail", [urllib.error.URLError("offline"), TimeoutError(), OSError("reset"),
                                  urllib.error.HTTPError(updates.API_URL, 403, "rate limited", {}, None)])
def test_fetch_latest_is_silent_on_errors(fail):
    def opener(req, timeout):
        raise fail
    assert updates.fetch_latest(opener=opener) is None


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"message": "Not Found"}', b'{"tag_name": "nightly"}'])
def test_fetch_latest_rejects_odd_answers(body):
    assert updates.fetch_latest(opener=lambda req, timeout: _Resp(body)) is None


def test_start_off_starts_nothing(tmp_path):
    assert updates.start(tmp_path, False, fetch=Fetch("v9.0.0")) is None


# ---------------- the window (Home notice, Settings switch) ----------------
class _NoStartup:
    def app_command(self):
        return None

    def is_enabled(self):
        return False


@pytest.fixture
def api(tmp_path, monkeypatch):
    opened = []
    a = Api(data_dir=tmp_path / "data", config_path=tmp_path / "cfg" / "config.toml",
            startup_mod=_NoStartup(), signal_reload=lambda: True, list_mic_names=lambda: [], open_url=opened.append)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("ecoscribe.window.__version__", "1.17.0")
    a._opened = opened
    return a


def test_window_notice_open_and_dismiss(api):
    assert api.update_notice() == {}
    updates.check(api._data_dir, now=1.0, fetch=Fetch("v1.18.0"))
    n = api.update_notice()
    assert n["version"] == "1.18.0"
    assert api.open_update() == {"ok": True} and api._opened == [n["url"]]
    api.dismiss_update("1.18.0")
    assert api.update_notice() == {}
    assert api.open_update() == {"ok": False}


def test_window_switch_off_hides_the_notice(api):
    updates.check(api._data_dir, now=1.0, fetch=Fetch("v1.18.0"))
    assert api.get_settings()["values"]["update_check"] is True  # on by default
    assert api.save_settings({"update_check": False})["ok"]
    assert api.get_settings()["values"]["update_check"] is False
    assert api.update_notice() == {}
