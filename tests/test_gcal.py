"""Google Calendar sign-in (dictado-k19): a fake Google, invented events and people."""
import json
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ecoscribe import gcal, sessions
from ecoscribe.gcal import GoogleCalendar, to_event

UTC = timezone.utc
NOW = datetime(2026, 3, 4, 9, 5, tzinfo=UTC)


def _item(summary, start, mins=30, **kw):
    return {"summary": summary, "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=mins)).isoformat()}, **kw}


SYNC = _item("Weekly sync", NOW.replace(minute=0), hangoutLink="https://meet.google.com/abc-defg-hij", attendees=[
    {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
    {"email": "ana.lopez@example.com", "displayName": "Ana López"},
    {"email": "bo.berg@example.com"},
    {"email": "room-1@resource.calendar.google.com", "resource": True}])


class FakeGoogle:
    def __init__(self, items):
        self.items, self.calls = items, []

    def __call__(self, method, url, form=None, token=None, timeout=15):
        self.calls.append((method, url.split("?")[0], form))
        if url == gcal.TOKEN_URL:
            if form["grant_type"] == "authorization_code":
                assert form["code"] == "the-code" and form["code_verifier"]
                return {"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600}
            assert form["refresh_token"] == "rt1"
            return {"access_token": "at2", "expires_in": 3600}
        assert token
        return {"items": self.items}


def _with_client(tmp_path):
    (tmp_path / gcal.CLIENT_FILE).write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "csec"}}))
    return tmp_path


def _browser(answer):
    """Stands in for the user's browser: follow Google's redirect back to Ecoscribe."""
    def open_url(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert q["scope"] == [gcal.SCOPE] and q["code_challenge_method"] == ["S256"]
        back = q["redirect_uri"][0] + "/?" + urllib.parse.urlencode({"state": q["state"][0], **answer})
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=5).read(), daemon=True).start()
    return open_url


def test_an_event_keeps_guests_without_you_and_rooms():
    e = to_event(SYNC)
    assert e.title == "Weekly sync" and e.attendees == ["Ana López", "Bo Berg"]
    assert e.emails == ["ana.lopez@example.com", "bo.berg@example.com"] and "meet.google.com" in e.conference


def test_all_day_cancelled_and_declined_events_are_never_a_call():
    assert to_event({"summary": "Holiday", "start": {"date": "2026-03-04"}, "end": {"date": "2026-03-05"}}) is None
    assert to_event({**SYNC, "status": "cancelled"}) is None
    declined = {**SYNC, "attendees": [{"email": "me@example.com", "self": True, "responseStatus": "declined"}]}
    assert to_event(declined) is None


def test_connect_keeps_a_token_then_a_call_finds_its_event(tmp_path):
    g = GoogleCalendar(_with_client(tmp_path), http=FakeGoogle([SYNC]), clock=NOW.timestamp)
    assert not g.connected
    assert g.connect(_browser({"code": "the-code"}), timeout=10) == {"ok": True}
    assert g.connected
    if gcal.sys.platform == "win32":  # DPAPI: the token isn't readable as text
        assert b"rt1" not in (tmp_path / gcal.TOKEN_FILE).read_bytes()
    assert g.refresh(force=True)
    ev = g.lookup(NOW, "chrome")
    assert ev.title == "Weekly sync" and ev.emails[0] == "ana.lopez@example.com"
    assert [e.title for e in g.today(NOW)] == ["Weekly sync"]
    g2 = GoogleCalendar(tmp_path, http=FakeGoogle([SYNC]), clock=NOW.timestamp)  # a restart: the refresh token
    assert g2.refresh(force=True) and g2.lookup(NOW).title == "Weekly sync"


def test_connect_says_why_it_failed(tmp_path):
    assert GoogleCalendar(tmp_path).connect(lambda u: None) == {"ok": False, "error": "no_client"}
    g = GoogleCalendar(_with_client(tmp_path), http=FakeGoogle([]))
    assert g.connect(_browser({"error": "access_denied"}), timeout=10) == {"ok": False, "error": "denied"}
    assert g.connect(lambda u: None, timeout=1.5) == {"ok": False, "error": "timeout"}
    assert not g.connected


def test_disconnect_forgets_the_token_and_the_events(tmp_path):
    g = GoogleCalendar(_with_client(tmp_path), http=FakeGoogle([SYNC]), clock=NOW.timestamp)
    g.connect(_browser({"code": "the-code"}), timeout=10)
    g.refresh(force=True)
    g.disconnect()
    assert not g.connected and g.lookup(NOW) is None and not (tmp_path / gcal.CACHE).exists()


def test_email_participants_on_an_older_meeting_asks_google(tmp_path):
    from ecoscribe.window import Api
    data = _with_client(tmp_path)
    g = GoogleCalendar(data, http=FakeGoogle([SYNC]))
    g.connect(_browser({"code": "the-code"}), timeout=10)
    root = data / "sessions"
    d = sessions.create("Meeting", "en", "meeting", root)
    sessions.write_meta(d, created=NOW.replace(minute=2).astimezone().replace(tzinfo=None).isoformat(timespec="seconds"))
    opened = []
    api = Api(data_dir=data, config_path=tmp_path / "config.toml", copy=lambda t: None, open_url=opened.append)
    api._gcal_http = FakeGoogle([SYNC])
    api._session = lambda name: d
    api.get_session = lambda name: {"segments": [{"start": 0, "end": 1, "text": "Invented words.", "speaker": "Me"}]}
    out = api.email_participants(d.name)
    assert out["to"] == ["ana.lopez@example.com", "bo.berg@example.com"]
    assert opened[0].startswith("mailto:ana.lopez@example.com,bo.berg@example.com?subject=Transcript%3A%20Weekly%20sync")
    assert sessions.read_meta(d)["calendar"]["title"] == "Weekly sync"  # kept: the next click needs no Google
