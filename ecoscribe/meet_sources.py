"""What a meeting records, kept right while it records (dictado-s1a, dictado-297, dictado-c7v).

Each second the worker notes, per source (the mic and the computer's audio), its level and how long
it has heard nothing, which devices it records and which ones the call app uses, into levels.json:
the meeting page shows it live and warns. A source silent for FOLLOW_S while the call app uses another
device switches to that device by itself (once per device), so a call on a virtual mic or on the
headset's communications output isn't recorded as silence. The page's button asks for a device in
source.json; the switch keeps the same meeting going.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)
LOUD = 0.002  # RMS at or above this is sound; a quiet room reads about 0.0005
FOLLOW_S = 20.0  # silent this long while the call app uses another device: record that one
CALL_EVERY_S = 5.0  # how often the call app's devices are looked up
STALE_S = 10.0  # an older levels.json is a stuck worker, not silence


class Sources:
    def __init__(self, d: Path, rec, app: str | None = None,
                 call_devices: Callable[[str], dict] | None = None, clock=time.monotonic, wall=time.time):
        self.d, self.rec, self.app = Path(d), rec, app or ""
        self.call_devices, self.clock, self.wall = call_devices, clock, wall
        now = clock()
        self.loud = {"mic": now, "system": now}
        self.call: dict = {"mic": None, "out": None}
        self._call_at = None
        self._asked = None  # the last request read from source.json
        self.followed: set = set()  # (kind, device) switched to by itself, once each

    def _names(self) -> tuple[str, str]:
        names = getattr(self.rec, "names", None)
        return names() if names else ("", "")

    def _switch(self, kind: str, name: str, why: str) -> None:
        switch = getattr(self.rec, "switch", None)
        if switch and switch(kind, name):
            log.info("meeting %s now records %s (%s)", kind, name, why)
            self.loud[kind] = self.clock()  # the new device gets its own time before it counts as silent

    def _requests(self) -> None:
        try:
            req = json.loads((self.d / "source.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if req == self._asked or not isinstance(req, dict):
            return
        self._asked = req
        for kind in ("mic", "system"):
            if req.get(kind):
                self._switch(kind, str(req[kind]), "asked from the meeting page")

    def tick(self) -> dict:
        """Once a second. Never raises: a recording never stops over what it reports."""
        try:
            return self._tick()
        except Exception:
            log.debug("meeting sources tick failed", exc_info=True)
            return {}

    def _tick(self) -> dict:
        now = self.clock()
        levels = getattr(self.rec, "levels", None)
        mic, system = levels() if levels else (0.0, 0.0)
        for kind, level in (("mic", mic), ("system", system)):
            if level >= LOUD:
                self.loud[kind] = now
        if self.call_devices and self.app and (self._call_at is None or now - self._call_at >= CALL_EVERY_S):
            self._call_at = now
            self.call = self.call_devices(self.app) or self.call
        self._requests()
        names = self._names()
        for kind, i, key in (("mic", 0, "mic"), ("system", 1, "out")):
            want = self.call.get(key)
            if (want and want != names[i] and now - self.loud[kind] >= FOLLOW_S
                    and (kind, want) not in self.followed):
                self.followed.add((kind, want))
                self._switch(kind, want, f"{names[i] or 'the default'} heard nothing and the call uses it")
        names = self._names()
        out = {"mic": round(float(mic), 5), "system": round(float(system), 5),
               "mic_name": names[0], "system_name": names[1],
               "mic_quiet_s": round(now - self.loud["mic"], 1), "system_quiet_s": round(now - self.loud["system"], 1),
               "call_mic": self.call.get("mic"), "call_out": self.call.get("out"), "t": round(self.wall(), 1)}
        try:
            from .transcribe import _write_json
            _write_json(self.d / "levels.json", out)
        except Exception as e:  # best effort: never stop a recording over a level file
            log.debug("levels not written (%s)", e)
        return out


def ask(d: Path, kind: str, name: str) -> None:
    """The meeting page's button: record `name` for `kind` from now on (the worker reads it within a second)."""
    p = Path(d) / "source.json"
    try:
        req = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        req = {}
    req[kind] = name
    req["n"] = int(req.get("n", 0)) + 1  # the same device asked again is still a new request
    p.write_text(json.dumps(req), encoding="utf-8")


def view(d: Path, app: str = "", now: float | None = None) -> dict:
    """What the meeting page shows: each source's device, level and silence, and the call's devices."""
    try:
        lv = json.loads((Path(d) / "levels.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False}
    if (now if now is not None else time.time()) - float(lv.get("t", 0)) > STALE_S:
        return {"ok": False}
    return {"ok": True,
            "call": {"app": app, "mic": lv.get("call_mic"), "out": lv.get("call_out")},
            "mic": {"name": lv.get("mic_name", ""), "level": lv.get("mic", 0.0), "quiet_s": lv.get("mic_quiet_s", 0)},
            "system": {"name": lv.get("system_name", ""), "level": lv.get("system", 0.0),
                       "quiet_s": lv.get("system_quiet_s", 0)}}
