"""Which mic and which output a call app uses right now (dictado-s1a, 297, c7v).

Windows keeps an audio session per app on each device it plays to or records from. A call app with
a session on a capture device is listening to that mic; one on a render device plays the call there.
The meeting records those, so a call on a virtual mic or on the headset's communications output
isn't recorded as silence. Only the kind of app is used (its exe), nothing else is kept.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
ACTIVE = 1  # AudioSessionStateActive


def _exe(pid: int) -> str:
    from ...detect import _exe_of_pid  # the shared module first: it imports the windows one
    return (_exe_of_pid(pid) or "").lower().removesuffix(".exe")


def sessions(flow: int) -> list[tuple[str, str, int]]:
    """[(device name, app exe, state)] for every app session on the active devices of `flow`
    (0 render, 1 capture)."""
    from ctypes import POINTER, cast

    import comtypes
    from comtypes import CLSCTX_ALL, CoCreateInstance
    from pycaw.constants import CLSID_MMDeviceEnumerator
    from pycaw.pycaw import AudioUtilities, IAudioSessionControl2, IAudioSessionManager2, IMMDeviceEnumerator

    comtypes.CoInitialize()
    en = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
    col = en.EnumAudioEndpoints(flow, 1)  # DEVICE_STATE_ACTIVE
    out = []
    for i in range(col.GetCount()):
        dev = col.Item(i)
        try:
            name = AudioUtilities.CreateDevice(dev).FriendlyName
            mgr = cast(dev.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None), POINTER(IAudioSessionManager2))
            it = mgr.GetSessionEnumerator()
            for j in range(it.GetCount()):
                ctl = it.GetSession(j).QueryInterface(IAudioSessionControl2)
                pid = ctl.GetProcessId()
                if pid:
                    out.append((name, _exe(pid), ctl.GetState()))
        except Exception:
            log.debug("audio sessions of a device not read", exc_info=True)
    return out


def pick(rows: list[tuple[str, str, int]], app: str) -> str | None:
    """The device `app` uses: its active session first, else any session it has; None when it has none."""
    app = (app or "").lower().removesuffix(".exe")
    if not app:
        return None
    mine = [(name, state) for name, exe, state in rows if exe == app]
    for name, state in mine:
        if state == ACTIVE:
            return name
    return mine[0][0] if mine else None


def call_devices(app: str) -> dict:
    """{"mic": the capture device `app` records from, "out": the render device it plays to}; None
    where unknown. Never raises: a meeting goes on without it."""
    out = {"mic": None, "out": None}
    try:
        out["mic"] = pick(sessions(1), app)
        out["out"] = pick(sessions(0), app)
    except Exception:
        log.debug("call devices not read", exc_info=True)
    return out
