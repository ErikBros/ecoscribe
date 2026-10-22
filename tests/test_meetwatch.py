"""Detector thread logic with fake reads, a fake clock and a fake controller."""
import json
from pathlib import Path

from ecoscribe import meetings, meetwatch, sessions
from ecoscribe.config import Config
from ecoscribe.detect import MicUse


class FakeController:
    def __init__(self):
        self.meeting, self.started, self.stopped, self.lv = None, [], 0, None

    def start_meeting(self, lang, title="Reunión", app=None):
        self.started.append((lang, app))
        self.meeting = {"dir": "D", "app": app, "lang": lang, "status": "recording"}
        return Path("D")

    def set_app(self, app):
        if not self.meeting or self.meeting.get("app"):
            return False
        self.meeting["app"] = app
        return True

    def stop_meeting(self):
        self.stopped += 1
        if self.meeting:
            self.meeting["status"] = "stopping"

    def state(self):
        return {"meeting": self.meeting, "job": None, "queue": []}

    def levels(self):
        return self.lv


class World:
    """What Windows would report: who holds the mic, window titles, running exes."""

    def __init__(self):
        self.mic, self.titles, self.running = set(), [], {"msteams", "chrome", "slack"}
        self.talking = set()  # mic in + sound out in the same process (macOS)

    def read(self):
        uses = [MicUse(app=a, in_use=True, start=1, stop=0, talking=a in self.talking) for a in self.mic]
        return uses, list(self.titles), set(self.running)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, mode="prompt", langs=None):
    cfg = Config()
    cfg.meetings.mode = mode
    if langs:
        (tmp_path / "meeting_langs.json").write_text(json.dumps(langs), encoding="utf-8")
    ctl, world, clock, prompts = FakeController(), World(), Clock(), []
    w = meetwatch.MeetWatch(ctl, cfg, lambda kind, app=None, lang=None: prompts.append((kind, app, lang)),
                            read=world.read, clock=clock, data_dir=tmp_path)
    return w, ctl, world, clock, prompts


def run(w, clock, seconds, step=2.0):
    end = clock.t + seconds
    while clock.t < end:
        clock.t += step
        w.tick()


def test_teams_start_prompts_with_remembered_lang(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, langs={"msteams": "en"})
    world.mic = {"msteams"}
    run(w, clock, 6)
    assert prompts == [("start", "msteams", "en")]
    assert ctl.started == []
    w.answer("transcribir", lang="en")
    assert ctl.started == [("en", "msteams")]


def test_prompt_default_lang_when_unknown_app(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic = {"slack"}
    run(w, clock, 6)
    assert prompts == [("start", "slack", "sv")]


def test_answer_with_other_lang_is_remembered(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic = {"msteams"}
    run(w, clock, 6)
    w.answer("transcribir", lang="el")
    assert json.loads((tmp_path / "meeting_langs.json").read_text(encoding="utf-8")) == {"msteams": "el"}
    assert w.lang_for("msteams") == "el"


def test_auto_mode_starts_meeting(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, mode="auto")
    world.mic = {"msteams"}
    run(w, clock, 6)
    assert ctl.started == [("sv", "msteams")] and prompts == []


def test_chrome_mic_without_title_never_prompts(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, mode="auto")
    world.mic = {"chrome"}
    world.titles = [("YouTube - Google Chrome", "chrome")]
    run(w, clock, 30 * 60)
    assert prompts == [] and ctl.started == []


def test_end_after_grace_stops_detector_meeting(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, mode="auto")
    world.mic = {"msteams"}
    run(w, clock, 6)
    world.mic = set()
    run(w, clock, 6)
    assert ctl.stopped == 0  # mute toggle / quick rejoin: still the same meeting
    run(w, clock, 8)
    assert ctl.stopped == 1


def test_end_stops_a_manual_meeting_of_that_call(tmp_path):
    """Not now, then Transcribe meeting now during the call: the meeting has the call's app, so the
    call's end stops it too, not the 4-minute silence backup (dictado-2s7)."""
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic = {"chrome"}
    world.titles = [("Meet - Weekly sync - Google Chrome", "chrome")]
    run(w, clock, 6)
    w.answer("ahora_no")
    ctl.start_meeting("sv", app="chrome")  # by hand, the call app recorded (t0u.33)
    run(w, clock, 60)
    world.mic, world.titles = set(), []
    run(w, clock, 30)
    assert ctl.stopped == 1


def test_end_of_another_call_does_not_stop_a_manual_meeting(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, mode="auto")
    ctl.start_meeting("sv", app="slack")
    world.mic = {"msteams"}
    run(w, clock, 6)
    world.mic = set()
    run(w, clock, 30)
    assert ctl.stopped == 0


def test_end_does_not_stop_a_manual_meeting(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, mode="auto")
    ctl.start_meeting("sv")  # the user pressed Transcribe meeting now
    world.mic = {"msteams"}
    run(w, clock, 6)
    assert len(ctl.started) == 1  # no second start
    world.mic = set()
    run(w, clock, 30)
    assert ctl.stopped == 0


def test_a_meeting_started_by_hand_just_before_the_call_joins_it(tmp_path):
    """Transcribe meeting now in the Meet waiting room, then the call starts: its end stops the meeting."""
    from datetime import datetime
    w, ctl, world, clock, prompts = make(tmp_path)
    ctl.start_meeting("sv")
    ctl.meeting["started"] = datetime.now().isoformat(timespec="seconds")
    world.mic, world.talking = {"chrome"}, {"chrome"}
    run(w, clock, 6)
    assert ctl.meeting["app"] == "chrome" and prompts == []
    world.mic = world.talking = set()
    run(w, clock, 30)
    assert ctl.stopped == 1


def test_an_older_meeting_started_by_hand_does_not_join_a_call(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    ctl.start_meeting("sv")
    ctl.meeting["started"] = "2020-01-01T09:00:00"  # an in-person meeting, recording for a while
    world.mic = {"msteams"}
    run(w, clock, 6)
    assert ctl.meeting["app"] is None
    world.mic = set()
    run(w, clock, 30)
    assert ctl.stopped == 0


def test_browser_call_without_a_meet_title_prompts_when_it_talks(tmp_path):
    """macOS: the Meet tab isn't in front, but Chrome's audio process captures and plays: a call."""
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic, world.talking = {"chrome"}, {"chrome"}
    world.titles = [("Docs - Google Chrome", "chrome")]
    run(w, clock, 6)
    assert prompts == [("start", "chrome", "sv")]
    w.answer("transcribir")
    world.talking = set()  # left the call; the tab keeps the mic
    run(w, clock, 30)
    assert ctl.stopped == 1


def test_ahora_no_suppresses_until_end(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic = {"msteams"}
    run(w, clock, 6)
    w.answer("ahora_no")
    run(w, clock, 600)
    assert prompts == [("start", "msteams", "sv")] and ctl.started == []
    world.mic = set()
    run(w, clock, 30)
    assert ctl.stopped == 0
    world.mic = {"msteams"}  # the next call asks again
    run(w, clock, 6)
    assert prompts[-1] == ("start", "msteams", "sv")


def test_end_dismisses_unanswered_prompt(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic = {"msteams"}
    run(w, clock, 6)
    world.mic = set()
    run(w, clock, 30)
    assert prompts[-1] == ("dismiss", "msteams", None)
    w.answer("transcribir", lang="sv")  # a late click after the call ended: nothing
    assert ctl.started == []


def test_silence_backup_prompts_then_stops(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    ctl.start_meeting("sv")
    ctl.lv = (0.0, 0.0)
    run(w, clock, 178)
    assert prompts == []
    run(w, clock, 4)
    assert prompts == [("end?", None, None)]
    run(w, clock, 56)
    assert ctl.stopped == 0
    run(w, clock, 6)
    assert ctl.stopped == 1


def test_silence_seguir_keeps_recording(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    ctl.start_meeting("sv")
    ctl.lv = (0.0, 0.0)
    run(w, clock, 182)
    w.answer("seguir")
    run(w, clock, 100)
    assert ctl.stopped == 0
    run(w, clock, 90)  # another 180 s of silence: asks again
    assert [p[0] for p in prompts] == ["end?", "end?"]


def test_sound_resets_silence(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    ctl.start_meeting("sv")
    ctl.lv = (0.0, 0.0)
    run(w, clock, 170)
    ctl.lv = (0.0, 0.05)
    w.tick()
    ctl.lv = (0.0, 0.0)
    run(w, clock, 170)
    assert prompts == []


def test_mode_off_does_nothing(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path, mode="off")
    world.mic = {"msteams"}
    run(w, clock, 60)
    assert prompts == [] and ctl.started == []


def test_audit_log(tmp_path):
    w, ctl, world, clock, prompts = make(tmp_path)
    world.mic = {"msteams"}
    run(w, clock, 6)
    w.answer("ahora_no")
    text = (tmp_path / "detect.log").read_text(encoding="utf-8")
    assert "start msteams" in text and "prompt" in text and "answer ahora_no" in text


def test_controller_levels_from_worker_file(tmp_path):
    cfg = Config()
    cfg.transcribe.root = str(tmp_path / "tr")

    class P:
        pid, rc = 1, None

        def poll(self):
            return self.rc

    class Ev:
        def set(self):
            pass

        def reset(self):
            pass
    t = [5000.0]
    c = meetings.Controller(tmp_path / "data", cfg, spawn=lambda a: P(), stop_event=Ev(), attach=lambda p: None,
                            clock=lambda: t[0])
    assert c.levels() is None
    d = c.start_meeting("sv")
    assert c.levels() is None  # no file yet: unknown, not silent
    (d / "levels.json").write_text(json.dumps({"mic": 0.01, "system": 0.2, "t": 4999.0}), encoding="utf-8")
    assert c.levels() == (0.01, 0.2)
    t[0] = 5020.0  # stale: the worker stopped writing
    assert c.levels() is None



def test_back_to_back_calls_with_the_real_controller(tmp_path):
    """Integration: Teams ends, Slack starts while Teams is still saving: both get recorded."""
    from tests import test_meetings as tm
    ctl, sp, _, _ = tm.make(tmp_path / "c")
    cfg = Config()
    cfg.meetings.mode = "auto"
    world, clock = World(), Clock()
    w = meetwatch.MeetWatch(ctl, cfg, lambda *a: None, read=world.read, clock=clock, data_dir=tmp_path)
    world.mic = {"msteams"}
    for _ in range(3):
        w.tick(); clock.t += 2
    assert ctl.state()["meeting"]["app"] == "msteams"
    world.mic = set()
    for _ in range(12):  # past the 10 s grace: Teams stops, its worker saves
        w.tick(); clock.t += 2
    assert ctl.state()["meeting"]["status"] == "stopping"
    world.mic = {"slack"}
    for _ in range(3):
        w.tick(); clock.t += 2
    assert ctl.state()["next_meeting"]["app"] == "slack"  # offered and queued, not dropped
    tm.finish(sp.procs[0], Path(ctl.state()["meeting"]["dir"]))
    ctl.poll()
    assert ctl.state()["meeting"]["app"] == "slack" and ctl.state()["meeting"]["status"] == "recording"
