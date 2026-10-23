"""What a meeting records, kept right while it records (dictado-s1a, dictado-297, dictado-c7v)."""
import json

from ecoscribe import meet_sources
from ecoscribe.meet_sources import FOLLOW_S, Sources, ask, view
from ecoscribe.platform.windows.audio_route import pick
from ecoscribe.session_rec import MicSource, SessionRecorder


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeRec:
    """levels() and names() of a recorder; switch() records what was asked."""
    def __init__(self, mic="Headset Mic", out="Speakers"):
        self.mic_name, self.out_name, self.lv = mic, out, (0.0, 0.0)
        self.switched = []

    def levels(self):
        return self.lv

    def names(self):
        return self.mic_name, self.out_name

    def switch(self, kind, name):
        self.switched.append((kind, name))
        if kind == "mic":
            self.mic_name = name
        else:
            self.out_name = name
        return True


def run(tmp_path, rec, clock, call=None, ticks=1, step=1.0):
    src = Sources(tmp_path, rec, app="chrome", call_devices=(lambda app: call) if call else None, clock=clock, wall=lambda: 5000.0)
    out = None
    for _ in range(ticks):
        out = src.tick()
        clock.t += step
    return src, out


def test_levels_json_has_each_device_its_level_and_how_long_it_heard_nothing(tmp_path):
    rec, clock = FakeRec(), Clock()
    rec.lv = (0.03, 0.0)
    _, out = run(tmp_path, rec, clock, ticks=6)
    lv = json.loads((tmp_path / "levels.json").read_text(encoding="utf-8"))
    assert lv == out
    assert (lv["mic_name"], lv["system_name"]) == ("Headset Mic", "Speakers")
    assert lv["mic_quiet_s"] == 0 and lv["system_quiet_s"] == 5.0 and lv["t"] == 5000.0


def test_a_silent_mic_follows_the_call_apps_mic_once(tmp_path):
    rec, clock = FakeRec(), Clock()
    call = {"mic": "Microphone (Virtual)", "out": "Speakers"}
    src, _ = run(tmp_path, rec, clock, call, ticks=int(FOLLOW_S) + 2)
    assert rec.switched == [("mic", "Microphone (Virtual)")]  # the output already matches the call: left alone
    rec.mic_name = "Headset Mic"  # whatever happens next, it doesn't flip back and forth
    for _ in range(int(FOLLOW_S) * 2):
        src.tick(); clock.t += 1
    assert rec.switched == [("mic", "Microphone (Virtual)")]


def test_a_mic_that_hears_something_is_not_switched(tmp_path):
    rec, clock = FakeRec(), Clock()
    rec.lv = (0.05, 0.05)
    run(tmp_path, rec, clock, {"mic": "Microphone (Virtual)", "out": "Headphones"}, ticks=int(FOLLOW_S) * 2)
    assert rec.switched == []


def test_silent_computer_audio_follows_the_output_the_call_plays_to(tmp_path):
    rec, clock = FakeRec(), Clock()
    rec.lv = (0.05, 0.0)
    _, out = run(tmp_path, rec, clock, {"mic": "Headset Mic", "out": "Headphones (Headset)"}, ticks=int(FOLLOW_S) + 2)
    assert rec.switched == [("system", "Headphones (Headset)")]
    assert out["system_name"] == "Headphones (Headset)" and out["system_quiet_s"] < FOLLOW_S  # a fresh start
    assert (out["call_mic"], out["call_out"]) == ("Headset Mic", "Headphones (Headset)")


def test_the_page_button_switches_and_a_repeat_of_the_same_request_does_nothing(tmp_path):
    rec, clock = FakeRec(), Clock()
    src = Sources(tmp_path, rec, clock=clock)
    ask(tmp_path, "mic", "Microphone (Virtual)")
    src.tick(); src.tick()
    assert rec.switched == [("mic", "Microphone (Virtual)")]
    ask(tmp_path, "mic", "Microphone (Virtual)")  # asked again (n changes): applied again
    src.tick()
    assert rec.switched == [("mic", "Microphone (Virtual)")] * 2


def test_view_is_what_the_page_shows_and_old_levels_are_not_silence(tmp_path):
    rec, clock = FakeRec(), Clock()
    run(tmp_path, rec, clock, {"mic": "Microphone (Virtual)", "out": None}, ticks=3)
    v = view(tmp_path, "Chrome", now=5003.0)
    assert v["ok"] and v["call"] == {"app": "Chrome", "mic": "Microphone (Virtual)", "out": None}
    assert v["mic"] == {"name": "Headset Mic", "level": 0.0, "quiet_s": 2.0}
    assert view(tmp_path, now=5000.0 + meet_sources.STALE_S + 1) == {"ok": False}
    assert view(tmp_path / "nowhere") == {"ok": False}


def test_pick_prefers_the_apps_active_session():
    rows = [("Speakers", "chrome", 0), ("Headphones", "signal", 1), ("Headphones", "chrome", 1)]
    assert pick(rows, "chrome") == "Headphones"
    assert pick(rows, "chrome.exe") == "Headphones"
    assert pick([("Speakers", "chrome", 0)], "chrome") == "Speakers"  # no active one: any it has
    assert pick(rows, "teams") is None and pick(rows, "") is None


def test_the_recorder_names_its_devices_and_switches_the_mic(tmp_path):
    class FakeSd:
        opened = []

        def query_devices(self, idx=None, kind=None):
            devs = [{"name": "Headset Mic", "max_input_channels": 1, "hostapi": 0},
                    {"name": "Microphone (Virtual)", "max_input_channels": 1, "hostapi": 0}]
            return devs if idx is None and kind is None else devs[idx or 0]

        def query_hostapis(self):
            return [{"name": "MME"}]

        def InputStream(self, device, **kw):
            FakeSd.opened.append(device)

            class S:
                def start(self): pass
                def stop(self): pass
                def close(self): pass
            return S()

    from ecoscribe.config import AudioCfg
    mic = MicSource(AudioCfg(device="Headset Mic", host="MME"), sd_module=FakeSd())
    mic.start()
    mic.switch("Microphone (Virtual)")
    assert mic.device_name == "Microphone (Virtual)" and FakeSd.opened == [0, 1]

    class Loop:
        device_name = "Speakers [Loopback]"

    rec = SessionRecorder(tmp_path, mic_factory=None, loop_factory=None)
    rec.mic, rec.loop = mic, Loop()
    assert rec.names() == ("Microphone (Virtual)", "Speakers")
    assert rec.switch("system", "Headphones") is False  # this source can't switch: said, not raised
