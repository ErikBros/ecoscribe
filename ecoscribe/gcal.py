"""Meeting names and guests from Google Calendar, by signing in (dictado-k19).

For accounts whose admin turned off the secret iCal address (calendar_ics.py). Settings >
Meetings > Connect Google Calendar opens the browser once (OAuth for desktop apps: a loopback
redirect to 127.0.0.1 and PKCE), read-only scope. The background app then keeps today's events
in the data folder, like the iCal feed, and a call takes the event happening then: its title,
its guests' names (Whisper prompt) and addresses (Email participants), its Meet link.

The OAuth client (a Google Cloud "Desktop app" client) is the JSON file Google lets you
download, saved as google_client.json in the data folder. The refresh token stays on this
computer: DPAPI-encrypted for this Windows user, owner-only file on macOS. Nothing is logged
but counts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .calendar_ics import EARLY_S, Event, _name_of, pick

log = logging.getLogger(__name__)
UTC = timezone.utc
SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (an endpoint, not a secret)
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CLIENT_FILE = "google_client.json"
TOKEN_FILE = "google_token.bin"  # noqa: S105
CACHE = "google_events.json"
MAX_AGE_S = 600  # fetch at most every 10 min (a detected call forces one)


# -- the token, kept for this user only -------------------------------------------------------------
def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    return _dpapi(data, encrypt=True)


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    return _dpapi(data, encrypt=False)


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes as w

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if encrypt:
        ok = fn(ctypes.byref(src), "Ecoscribe", None, None, None, 0, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# -- http --------------------------------------------------------------------------------------------
def _http(method: str, url: str, form: dict | None = None, token: str | None = None, timeout: float = 15) -> dict:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "Ecoscribe"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https endpoints)
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        err = body.get("error")
        raise GoogleError(e.code, err.get("status") if isinstance(err, dict) else str(err or "")) from None


class GoogleError(Exception):
    def __init__(self, code: int, what: str = ""):
        super().__init__(f"HTTP {code} {what}".strip())
        self.code, self.what = code, what


# -- events ------------------------------------------------------------------------------------------
def _when(x: dict) -> datetime | None:
    s = (x or {}).get("dateTime")
    if not s:
        return None  # an all-day event: never a call
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def to_event(item: dict) -> Event | None:
    """One Calendar API event -> Event: guests without you and rooms, None when it's all-day,
    cancelled or you declined it."""
    if item.get("status") == "cancelled":
        return None
    start, end = _when(item.get("start")), _when(item.get("end"))
    if start is None or end is None:
        return None
    names, emails = [], []
    for a in item.get("attendees") or []:
        email = str(a.get("email") or "").strip().lower()
        if a.get("self"):
            if a.get("responseStatus") == "declined":
                return None
            continue
        if a.get("resource") or email.endswith("resource.calendar.google.com"):
            continue
        dn = str(a.get("displayName") or "").strip()
        name = dn if dn and "@" not in dn else _name_of(email) if email else ""
        if name and name not in names:
            names.append(name)
        if "@" in email and email not in emails:
            emails.append(email)
    links = [item.get("hangoutLink") or ""]
    links += [p.get("uri") or "" for p in (item.get("conferenceData") or {}).get("entryPoints") or []]
    return Event(str(item.get("summary") or "").strip(), start, end, names, " ".join(x for x in links if x),
                 str(item.get("id") or ""), emails)


def _dump(e: Event) -> dict:
    return {"title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat(), "attendees": e.attendees,
            "conference": e.conference, "uid": e.uid, "emails": e.emails}


def _load(d: dict) -> Event:
    return Event(d["title"], datetime.fromisoformat(d["start"]), datetime.fromisoformat(d["end"]),
                 list(d.get("attendees") or []), d.get("conference") or "", d.get("uid") or "", list(d.get("emails") or []))


# -- the calendar ------------------------------------------------------------------------------------
class GoogleCalendar:
    """The same lookup/refresh/today as calendar_ics.CalendarFeed, from the Calendar API."""

    def __init__(self, data_dir: Path, http=_http, clock=time.time, max_age_s: float = MAX_AGE_S):
        self.dir = Path(data_dir)
        self.http, self.clock, self.max_age = http, clock, max_age_s
        self.last_try: float | None = None
        self._access: tuple[str, float] | None = None  # (token, expires at)
        self._lock = threading.Lock()

    # client + token
    def client(self) -> tuple[str, str] | None:
        """(client_id, client_secret) from the Google Cloud download, or None."""
        try:
            d = json.loads((self.dir / CLIENT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        d = d.get("installed") or d.get("web") or d
        cid, sec = d.get("client_id"), d.get("client_secret") or ""
        return (cid, sec) if cid else None

    @property
    def connected(self) -> bool:
        return (self.dir / TOKEN_FILE).exists()

    def _refresh_token(self) -> str | None:
        try:
            return json.loads(_unprotect((self.dir / TOKEN_FILE).read_bytes())).get("refresh_token")
        except (OSError, ValueError):
            return None

    def _save_token(self, tok: dict) -> None:
        p = self.dir / TOKEN_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_bytes(_protect(json.dumps({"refresh_token": tok["refresh_token"]}).encode()))
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    def disconnect(self) -> None:
        for name in (TOKEN_FILE, CACHE):
            try:
                (self.dir / name).unlink()
            except FileNotFoundError:
                pass
        self._access = None

    def _token(self) -> str:
        if self._access and self._access[1] > self.clock() + 60:
            return self._access[0]
        client, rt = self.client(), self._refresh_token()
        if not client or not rt:
            raise GoogleError(401, "not connected")
        tok = self.http("POST", TOKEN_URL, {"client_id": client[0], "client_secret": client[1],
                                            "refresh_token": rt, "grant_type": "refresh_token"})
        self._access = (tok["access_token"], self.clock() + float(tok.get("expires_in", 3600)))
        return self._access[0]

    # sign in
    def auth_url(self, redirect: str, state: str, challenge: str) -> str:
        cid = self.client()[0]
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})

    def connect(self, open_url, timeout: float = 180) -> dict:
        """Open Google's sign-in in the browser, wait for its answer on 127.0.0.1, keep the token."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        if not self.client():
            return {"ok": False, "error": "no_client"}
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        got: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if "state" in q or "error" in q:
                    got.update({k: v[0] for k, v in q.items()})
                ok = "code" in q and q.get("state", [""])[0] == state
                msg = ("Ecoscribe is connected to your Google Calendar. You can close this tab."
                       if ok else "Ecoscribe didn't get access. You can close this tab and try again.")
                body = f"<!doctype html><meta charset=utf-8><title>Ecoscribe</title><p style='font:16px sans-serif;margin:3em'>{msg}</p>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        srv.timeout = 1
        redirect = f"http://127.0.0.1:{srv.server_port}"
        try:
            open_url(self.auth_url(redirect, state, challenge))
            end = time.monotonic() + timeout
            while not got and time.monotonic() < end:
                srv.handle_request()
        finally:
            srv.server_close()
        if not got:
            return {"ok": False, "error": "timeout"}
        if got.get("state") != state or "code" not in got:
            return {"ok": False, "error": "denied" if got.get("error") == "access_denied" else (got.get("error") or "denied")}
        client = self.client()
        try:
            tok = self.http("POST", TOKEN_URL, {"client_id": client[0], "client_secret": client[1], "code": got["code"],
                                                "code_verifier": verifier, "redirect_uri": redirect,
                                                "grant_type": "authorization_code"})
        except (GoogleError, OSError) as e:
            log.warning("Google sign-in: token exchange failed (%s)", e)
            return {"ok": False, "error": "exchange"}
        if not tok.get("refresh_token"):
            return {"ok": False, "error": "no_refresh_token"}
        self._save_token(tok)
        self._access = (tok["access_token"], self.clock() + float(tok.get("expires_in", 3600)))
        log.info("Google Calendar connected")
        return {"ok": True}

    # events
    def fetch(self, lo: datetime, hi: datetime) -> list[Event]:
        items, page = [], None
        while True:
            q = {"timeMin": lo.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                 "timeMax": hi.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                 "singleEvents": "true", "orderBy": "startTime", "maxResults": "250"}
            if page:
                q["pageToken"] = page
            r = self.http("GET", EVENTS_URL + "?" + urllib.parse.urlencode(q), token=self._token())
            items += r.get("items") or []
            page = r.get("nextPageToken")
            if not page:
                break
        return [e for e in (to_event(i) for i in items) if e is not None and e.title]

    def refresh(self, force: bool = False) -> bool:
        """Keep yesterday to tomorrow in the data folder, at most every max_age (or `force`)."""
        if not self.connected:
            return False
        with self._lock:
            now = self.clock()
            if not force and self.last_try is not None and now - self.last_try < self.max_age:
                return False
            self.last_try = now
            t = datetime.fromtimestamp(now, UTC)
            try:
                events = self.fetch(t - timedelta(days=1), t + timedelta(days=1))
            except (GoogleError, OSError, ValueError, KeyError) as e:
                log.warning("Google Calendar not read (%s); using the last copy", type(e).__name__)
                return False
            p = self.dir / CACHE
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps([_dump(e) for e in events]), encoding="utf-8")
            os.replace(tmp, p)
            log.info("Google Calendar read (%d events)", len(events))
            return True

    def events(self) -> list[Event]:
        try:
            return [_load(d) for d in json.loads((self.dir / CACHE).read_text(encoding="utf-8"))]
        except (OSError, ValueError, KeyError):
            return []

    def lookup(self, now: datetime | None = None, app: str | None = None) -> Event | None:
        if not self.connected:
            return None
        return pick(self.events(), now or datetime.now(UTC), app)

    def event_at(self, when: datetime, app: str | None = None) -> Event | None:
        """An older meeting (Email participants after the fact): ask Google for that time."""
        if not self.connected:
            return None
        return pick(self.fetch(when - timedelta(hours=12), when + timedelta(hours=12)), when, app, early_s=EARLY_S)

    def today(self, now: datetime | None = None) -> list[Event]:
        now = (now or datetime.now(UTC)).astimezone()
        lo = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [e for e in self.events() if lo <= e.start < lo + timedelta(days=1)]
