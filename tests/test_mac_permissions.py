"""Permissions granted while Ecoscribe runs show up without a restart (dictado-6qp). No real TCC calls."""
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")


def _seq(*states):
    it = iter(states)
    last = {}

    def check():
        nonlocal last
        last = next(it, last)
        return dict(last)
    return check


def test_mic_granted_later_is_reported_and_watch_ends():
    from ecoscribe.platform.macos import permissions
    off = {"accessibility": True, "input": True, "microphone": False, "audio": True}
    on = {**off, "microphone": True}
    seen = []
    permissions.watch(lambda st, old: seen.append((st, old)), interval=0, check=_seq(off, off, on))
    assert seen == [(off, None), (on, off)]  # first look, then only the change
    assert permissions.missing(st=off) == ["Microphone"] and permissions.missing(st=on) == []


def test_all_on_at_start_checks_once():
    from ecoscribe.platform.macos import permissions
    calls = []
    on = {"accessibility": True, "input": True, "microphone": True, "audio": True}
    permissions.watch(lambda st, old: calls.append(st), interval=0, check=_seq(on))
    assert calls == [on]


def test_stop_ends_the_watch():
    from ecoscribe.platform.macos import permissions
    stop = threading.Event()
    stop.set()
    off = {"accessibility": False, "input": False, "microphone": False, "audio": False}
    calls = []
    permissions.watch(lambda st, old: calls.append(st), interval=60, stop=stop, check=_seq(off))
    assert calls == [off]  # returned at once, no 60 s wait


def test_setup_button_asks_macos_first_then_opens_the_pane(monkeypatch):
    """Until an app has asked, macOS doesn't list it in the pane: the first click shows macOS's prompt."""
    from ecoscribe.platform.macos import permissions
    asked, opened = [], []
    monkeypatch.setattr(permissions, "_asked", set())
    monkeypatch.setattr(permissions, "open_pane", opened.append)
    monkeypatch.setattr(permissions, "ask", lambda k: (asked.append(k), permissions._asked.add(k)))
    assert permissions.can_ask("input")
    assert permissions.ask_or_open("input") == "asked" and asked == ["input"] and opened == []
    assert not permissions.can_ask("input")
    assert permissions.ask_or_open("input") == "opened" and opened == ["input"]


def test_ask_failure_falls_back_to_the_pane(monkeypatch):
    from ecoscribe.platform.macos import permissions
    opened = []
    monkeypatch.setattr(permissions, "_asked", set())
    monkeypatch.setattr(permissions, "open_pane", opened.append)

    def boom(k):
        raise RuntimeError("no prompt")
    monkeypatch.setattr(permissions, "ask", boom)
    assert permissions.ask_or_open("accessibility") == "opened" and opened == ["accessibility"]


def test_microphone_can_ask_only_while_not_determined(monkeypatch):
    from ecoscribe.platform.macos import permissions
    for st, want in ((0, True), (2, False), (3, False), (None, False)):
        monkeypatch.setattr(permissions, "_mic_status", lambda st=st: st)
        assert permissions.can_ask("microphone") is want
