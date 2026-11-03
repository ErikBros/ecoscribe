"""Which mic and which output a call app uses right now, on macOS (dictado-7bw; Windows: dictado-s1a).

macOS 14+ lists an audio "process object" per process (kAudioHardwarePropertyProcessObjectList, as in
detect.py). Each one says which devices it records from (kAudioProcessPropertyDevices, input scope) and
plays to (output scope), and whether it is doing so right now. Device names are Core Audio's, the same
names sounddevice gives the meeting's mic, so the meeting can switch to the call's mic by name.
Processes are named like the detector names them (app_of_process): Chrome's helper counts as chrome.

Only the mic follows the call on the Mac: the system track is a process tap on every app's output
(systap.swift), which hears the call whatever device it plays to. So call_devices() leaves "out" as None:
a call on another output is nothing to warn about or switch to (the meeting page would offer a useless
"Record <device>" otherwise). sessions(0) still reads the outputs, for the record.
"""
from __future__ import annotations

import ctypes
import logging

from . import detect

log = logging.getLogger(__name__)
ACTIVE = 1  # running now (the Windows code's AudioSessionStateActive)
SCOPES = {1: ("inpt", "piri"), 0: ("outp", "piro")}  # flow (0 output, 1 input) -> (scope, "is running" selector)


def _devices(obj: int, scope: str) -> list[int]:
    """kAudioProcessPropertyDevices ('pdv#') of a process object in one scope; [] when unread."""
    ca = detect._ca()
    addr = detect._Addr(detect._fourcc("pdv#"), detect._fourcc(scope), 0)
    size = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size)):
        return []
    n = size.value // ctypes.sizeof(ctypes.c_uint32)
    if not n:
        return []
    buf = (ctypes.c_uint32 * n)()
    size = ctypes.c_uint32(ctypes.sizeof(buf))
    if ca.AudioObjectGetPropertyData(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size), buf):
        return []
    return list(buf)[: size.value // ctypes.sizeof(ctypes.c_uint32)]


def _name(dev: int) -> str:
    p = detect._get(dev, "lnam", ctypes.c_void_p, 1)  # kAudioObjectPropertyName
    return detect._cfstring(p[0]) if p and p[0] else ""


def sessions(flow: int) -> list[tuple[str, str, int]]:
    """[(device name, app, state)] for every process that has a device of `flow` (0 output, 1 input);
    state is ACTIVE while it records or plays right now, else 0."""
    scope, running = SCOPES[flow]
    out = []
    for obj in detect._get(detect.SYSTEM, "prs#", ctypes.c_uint32) or []:
        devs = _devices(obj, scope)
        if not devs:
            continue
        pid = (detect._get(obj, "ppid", ctypes.c_int32, 1) or [0])[0]
        bundle = detect._cfstring((detect._get(obj, "pbid", ctypes.c_void_p, 1) or [0])[0] or 0)
        app = detect.app_of_process(int(pid), bundle)
        state = ACTIVE if (detect._get(obj, running, ctypes.c_uint32, 1) or [0])[0] else 0
        for dev in devs:
            name = _name(dev)
            if name:
                out.append((name, app, state))
    return out


def pick(rows: list[tuple[str, str, int]], app: str) -> str | None:
    """The device `app` uses: one it is running on first, else any it has; None when it has none."""
    app = (app or "").lower()
    if not app:
        return None
    mine = [(name, state) for name, a, state in rows if (a or "").lower() == app]
    for name, state in mine:
        if state == ACTIVE:
            return name
    return mine[0][0] if mine else None


def call_devices(app: str) -> dict:
    """{"mic": the input `app` records from, "out": None (the tap hears every output)}; None where unknown.
    Never raises: a meeting goes on without it."""
    out = {"mic": None, "out": None}
    try:
        out["mic"] = pick(sessions(1), app)
    except Exception:
        log.debug("call devices not read", exc_info=True)
    return out
