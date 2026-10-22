"""Is a newer Ecoscribe out? (dictado-cjk) Asks GitHub's public API for the latest release at most
once a day, from a background thread of the app; the window's Home shows a quiet notice with a
Download link to the release page (the .exe and the .dmg are both there).

State lives in <data dir>/update.json: when we last asked, what the latest release was, and the
version the user dismissed (hidden until a newer one appears). The app writes the first two, the
window the last; each write reloads the file and changes only its own keys.
Pure apart from the file and the one fetch, which tests replace."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

REPO = "ErikBros/ecoscribe"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
STATE = "update.json"
EVERY_S = 24 * 3600  # once a day at most
FIRST_DELAY_S = 60   # after start: never in the way of loading the model
TICK_S = 3600        # how often the thread looks whether a day has passed
TIMEOUT_S = 5.0
_TAG = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def parse(tag) -> tuple[int, int, int] | None:
    """"v1.18.0" / "1.18.0" / "1.18" -> (1, 18, 0); anything else (pre-releases, junk) -> None."""
    m = _TAG.match(str(tag or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def is_newer(latest, current) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def release_url(tag: str) -> str:
    """The release page, built from the checked tag (never a link taken from the answer)."""
    return f"https://github.com/{REPO}/releases/tag/{tag}"


def due(state: dict, now: float, every: float = EVERY_S) -> bool:
    last = state.get("checked_at")
    if not isinstance(last, (int, float)):
        return True
    return now - last >= every or last > now + 60  # the clock went back: ask again


def fetch_latest(timeout: float = TIMEOUT_S, opener=urllib.request.urlopen) -> str | None:
    """The latest release's tag, or None (offline, rate limited, no release, a bad answer). Never raises."""
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "Ecoscribe-update-check"})
    try:
        with opener(req, timeout=timeout) as r:
            data = json.loads(r.read(200_000).decode("utf-8"))
    except Exception as e:  # noqa: BLE001  offline, DNS, TLS, 403/404, junk: all mean "don't know"
        log.info("update check: no answer (%s)", type(e).__name__)
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    return tag if parse(tag) else None


def load(data_dir: Path) -> dict:
    try:
        data = json.loads((Path(data_dir) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update(data_dir: Path, **keys) -> dict:
    state = load(data_dir)
    state.update(keys)
    p = Path(data_dir) / STATE
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        log.warning("update check: couldn't save %s", p, exc_info=True)
    return state


def check(data_dir: Path, now: float | None = None, fetch=fetch_latest, every: float = EVERY_S) -> dict:
    """Ask GitHub if a day has passed since the last time (a failed ask counts too: once a day at
    most, whatever happens). Keeps the last known release when the ask fails."""
    now = time.time() if now is None else now
    state = load(data_dir)
    if not due(state, now, every):
        return state
    tag = fetch()
    keys = {"checked_at": now}
    if tag:
        keys["latest"] = tag
    return _update(data_dir, **keys)


def notice(state: dict, current: str) -> dict | None:
    """What Home shows: {"version", "url"} when the latest release is newer than this one and newer
    than the version the user dismissed; else None."""
    latest = state.get("latest")
    if not is_newer(latest, current):
        return None
    dismissed = state.get("dismissed")
    if dismissed and not is_newer(latest, dismissed):
        return None
    return {"version": str(latest).lstrip("v"), "url": release_url(latest)}


def dismiss(data_dir: Path, version: str) -> None:
    """Not now: hidden until a newer version than this one is out."""
    if parse(version):
        _update(data_dir, dismissed=str(version).lstrip("v"))


def start(data_dir: Path, enabled: bool, fetch=fetch_latest, delay_s: float = FIRST_DELAY_S) -> threading.Thread | None:
    """The app's background thread: first look a minute after start, then hourly; asks only when due."""
    if not enabled:
        log.info("update check off")
        return None

    def loop():
        time.sleep(delay_s)
        while True:
            try:
                check(data_dir, fetch=fetch)
            except Exception:  # noqa: BLE001  never take the app down over this
                log.exception("update check failed")
            time.sleep(TICK_S)
    t = threading.Thread(target=loop, name="ecoscribe-update-check", daemon=True)
    t.start()
    return t
