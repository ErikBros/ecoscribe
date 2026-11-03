"""Which mic and output a call app uses on macOS (dictado-7bw): platform/macos/audio_route.py."""
import sys

import pytest

from ecoscribe.platform.macos import audio_route
from ecoscribe.platform.macos.audio_route import ACTIVE, pick


def test_pick_prefers_the_device_the_app_runs_on():
    rows = [("Built-in Mic", "zoom", 0), ("USB Headset", "zoom", ACTIVE), ("Built-in Mic", "chrome", ACTIVE)]
    assert pick(rows, "zoom") == "USB Headset"
    assert pick(rows, "Chrome") == "Built-in Mic"
    assert pick([("Built-in Mic", "zoom", 0)], "zoom") == "Built-in Mic"  # idle, but its only device
    assert pick(rows, "slack") is None and pick(rows, "") is None


def test_sessions_name_each_process_like_the_detector(monkeypatch):
    devs = {(10, "inpt"): [100], (10, "outp"): [200, 201], (11, "inpt"): [], (11, "outp"): [200]}
    props = {(1, "prs#"): [10, 11], (10, "ppid"): [501], (11, "ppid"): [502], (10, "pbid"): [0], (11, "pbid"): [0],
             (10, "piri"): [1], (10, "piro"): [0], (11, "piro"): [1],
             (100, "lnam"): ["USB Headset"], (200, "lnam"): ["Speakers"], (201, "lnam"): [""]}
    monkeypatch.setattr(audio_route, "_devices", lambda obj, scope: devs[(obj, scope)])
    monkeypatch.setattr(audio_route.detect, "_get", lambda obj, sel, ctype, n=None: props.get((obj, sel)))
    monkeypatch.setattr(audio_route.detect, "_cfstring", lambda p: p if isinstance(p, str) else "")
    monkeypatch.setattr(audio_route.detect, "app_of_process", lambda pid, bundle: {501: "zoom", 502: "music"}[pid])
    assert audio_route.sessions(1) == [("USB Headset", "zoom", ACTIVE)]
    assert audio_route.sessions(0) == [("Speakers", "zoom", 0), ("Speakers", "music", ACTIVE)]  # unnamed 201 left out


def test_call_devices_never_raises(monkeypatch):
    def boom(flow):
        raise OSError("Core Audio gone")
    monkeypatch.setattr(audio_route, "sessions", boom)
    assert audio_route.call_devices("zoom") == {"mic": None, "out": None}


def test_the_system_track_is_never_switched(tmp_path):
    """The tap hears every output, so the meeting's system source refuses a switch (the mic still switches)."""
    from ecoscribe.platform.macos.systap import Loopback
    from ecoscribe.session_rec import SessionRecorder

    class Mic:
        def __init__(self):
            self.asked = []

        def switch(self, name):
            self.asked.append(name)

    rec = SessionRecorder(tmp_path, mic_factory=Mic, loop_factory=Loopback)
    rec.mic, rec.loop = Mic(), Loopback(command=["true"])
    assert rec.switch("system", "Headphones") is False
    assert rec.switch("mic", "USB Headset") is True and rec.mic.asked == ["USB Headset"]


@pytest.mark.skipif(sys.platform != "darwin", reason="Core Audio")
def test_reads_the_real_process_list():
    assert isinstance(audio_route.sessions(0), list) and isinstance(audio_route.sessions(1), list)
    assert set(audio_route.call_devices("no-such-app")) == {"mic", "out"}


def test_call_devices_name_the_mic_and_never_an_output(monkeypatch):
    rows = {1: [("USB Headset", "zoom", ACTIVE)], 0: [("Headphones", "zoom", ACTIVE)]}
    monkeypatch.setattr(audio_route, "sessions", lambda flow: rows[flow])
    assert audio_route.call_devices("zoom") == {"mic": "USB Headset", "out": None}
