"""macOS call detection readers: Core Audio's process list -> MicUse (fake process lists, no Core Audio),
plus, on macOS only, a check that the real Core Audio / libproc / responsibility calls answer at all."""
import os
import sys

import pytest

from ecoscribe.platform.macos import detect


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(detect, "_first_seen", {})
    monkeypatch.setattr(detect, "_app_cache", {})
    monkeypatch.setattr(detect, "_status", {"mic_api": "unknown", "accessibility": "unknown"})


def fake_procs(monkeypatch, procs, responsible=None, bundles=None, paths=None, exes=None):
    """procs: (pid, bundle, captures, plays). responsible: pid -> pid; bundles / paths / exes: pid -> value."""
    monkeypatch.setattr(detect, "audio_processes", lambda: procs)
    monkeypatch.setattr(detect, "_responsible_pid", lambda pid: (responsible or {}).get(pid, pid))
    monkeypatch.setattr(detect, "_bundle_of_pid", lambda pid: (bundles or {}).get(pid, ""))
    monkeypatch.setattr(detect, "_path_of_pid", lambda pid: (paths or {}).get(pid, ""))
    monkeypatch.setattr(detect, "_exe", lambda pid: (exes or {}).get(pid, ""))


def test_bundle_ids_map_to_the_shared_app_names():
    assert detect.app_of_bundle("com.google.Chrome.helper") == "chrome"
    assert detect.app_of_bundle("com.apple.WebKit.GPU") == "safari"
    assert detect.app_of_bundle("com.microsoft.teams2") == "msteams"
    assert detect.app_of_bundle("company.thebrowser.Browser.helper") == "arc"
    assert detect.app_of_bundle("com.apple.avconferenced") == "facetime"
    assert detect.app_of_bundle("org.mozilla.plugincontainer") == "firefox"
    assert detect.known_app("com.example.helper") == ""


def test_app_of_path_names_the_outer_app_or_the_daemon():
    chrome = ("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/1/"
              "Helpers/Google Chrome Helper.app/Contents/MacOS/Google Chrome Helper")
    assert detect.app_of_path(chrome) == "chrome"
    assert detect.app_of_path("/Applications/zoom.us.app/Contents/MacOS/zoom.us") == "zoom"
    assert detect.app_of_path("/System/Applications/FaceTime.app/Contents/MacOS/FaceTime") == "facetime"
    assert detect.app_of_path("/usr/libexec/avconferenced") == "facetime"
    assert detect.app_of_path("/Applications/Notes.app/Contents/MacOS/Notes") == ""
    assert detect.app_of_path("") == ""


def test_a_webkit_process_counts_as_the_app_that_launched_it(monkeypatch):
    """A call app built on WebKit captures in com.apple.WebKit.GPU: that is the call app, not Safari."""
    fake_procs(monkeypatch, [(21, "com.apple.WebKit.GPU", True, True), (31, "com.apple.WebKit.GPU", True, False)],
               responsible={21: 20, 31: 30}, bundles={20: "com.microsoft.teams2", 30: "com.apple.Safari"})
    uses = {u.app: u for u in detect.read_consent()}
    assert set(uses) == {"msteams", "safari"}
    assert uses["msteams"].talking and not uses["safari"].talking


def test_a_helper_without_a_known_bundle_is_named_by_its_app(monkeypatch):
    """An unknown helper bundle ('...Browser.helper') or none at all: the responsible app, then the .app path."""
    fake_procs(monkeypatch, [(41, "company.example.helper", True, True), (51, "", True, False)],
               responsible={41: 40}, bundles={40: "company.thebrowser.Browser"},
               paths={51: "/Applications/Signal.app/Contents/Frameworks/Signal Helper.app/Contents/MacOS/Signal Helper"})
    assert sorted((u.app, u.talking) for u in detect.read_consent()) == [("arc", True), ("signal", False)]


def test_ecoscribes_own_helpers_count_as_ecoscribe(monkeypatch):
    """The system-audio helper inside the app bundle has no bundle id of its own: it is Ecoscribe (ignored)."""
    app = "/Applications/Ecoscribe.app/Contents/MacOS/Ecoscribe"
    fake_procs(monkeypatch, [(81, "", True, False), (80, "com.erikbros.ecoscribe", True, False)],
               responsible={81: 80}, paths={80: app, 81: "/Applications/Ecoscribe.app/Contents/MacOS/ecoscribe-systap"})
    assert [u.app for u in detect.read_consent()] == ["ecoscribe"]


def test_facetime_audio_in_its_daemon_is_facetime(monkeypatch):
    fake_procs(monkeypatch, [(61, "", True, True)], paths={61: "/usr/libexec/avconferenced"})
    assert [u.app for u in detect.read_consent()] == ["facetime"]


def test_a_generic_helper_name_falls_back_to_the_exe(monkeypatch):
    fake_procs(monkeypatch, [(71, "com.example.tool.helper", True, False)], exes={71: "sometool"})
    assert [u.app for u in detect.read_consent()] == ["sometool"]


def test_a_browser_that_captures_and_plays_is_talking(monkeypatch):
    fake_procs(monkeypatch, [(11, "com.google.Chrome.helper", True, True), (12, "com.tinyspeck.slackmacgap", True, False)])
    uses = {u.app: u for u in detect.read_consent()}
    assert uses["chrome"].in_use and uses["chrome"].talking
    assert uses["slack"].in_use and not uses["slack"].talking


def test_capture_and_playback_in_different_processes_of_one_browser_is_talking(monkeypatch):
    """Before dictado-nhn only a process doing both counted: a browser whose sound plays from another helper
    than the one holding the mic was never a call."""
    fake_procs(monkeypatch, [(11, "com.google.Chrome.helper", True, False), (12, "com.google.Chrome.helper", False, True)])
    assert [(u.app, u.talking) for u in detect.read_consent()] == [("chrome", True)]


def test_an_app_only_playing_sound_is_not_on_the_mic(monkeypatch):
    fake_procs(monkeypatch, [(11, "com.spotify.client", False, True)])
    assert detect.read_consent() == []


def test_a_tab_only_holding_the_mic_is_not_talking(monkeypatch):
    fake_procs(monkeypatch, [(11, "com.google.Chrome.helper", True, False)])
    assert [(u.app, u.talking) for u in detect.read_consent()] == [("chrome", False)]


def test_an_unreadable_process_list_is_reported_not_silent(monkeypatch):
    fake_procs(monkeypatch, None)
    assert detect.read_consent() == []
    assert detect.health()["mic_api"] == "unavailable"
    fake_procs(monkeypatch, [])
    detect.read_consent()
    assert detect.health()["mic_api"] == "ok"


def test_no_accessibility_means_no_titles_and_says_so(monkeypatch):
    monkeypatch.setattr(detect, "_ax_trusted", lambda: False)
    assert detect.window_titles() == []
    assert detect.health()["accessibility"] == "not granted"


def test_the_detector_on_the_mac_knows_the_mac_browsers():
    if sys.platform != "darwin":
        pytest.skip("the Mac's browser list is added on macOS only")
    from ecoscribe import detect as shared
    assert {"safari", "arc", "vivaldi"} <= shared.BROWSERS and "facetime" in shared.CALL_APPS


# ---------- the real OS calls (macOS CI): the selectors and symbols answer ----------
mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="real Core Audio, libproc and libSystem")


@mac_only
def test_core_audio_process_list_is_readable():
    """kAudioHardwarePropertyProcessObjectList answers (a wrong selector or an old macOS gives None:
    then no call could ever be detected)."""
    objs = detect._get(detect.SYSTEM, "prs#", detect.ctypes.c_uint32)
    assert objs is not None
    procs = detect.audio_processes()
    assert isinstance(procs, list)
    for pid, bundle, cap, play in procs:
        assert pid > 0 and isinstance(bundle, str) and (cap or play)
    if objs:  # the objects answer the per-process selectors the reader uses (one may vanish meanwhile: any)
        assert any(all(detect._get(o, sel, detect.ctypes.c_uint32, 1) is not None for sel in ("ppid", "piri", "piro"))
                   for o in objs)


@mac_only
def test_process_lookups_answer_for_this_process():
    me = os.getpid()
    assert detect._responsible_pid(me) > 0
    assert detect._path_of_pid(me).lower().rsplit("/", 1)[-1].startswith("python")
    assert detect.app_of_process(me, "") == "python"
    assert isinstance(detect.window_titles(), list)  # no Accessibility on CI: an empty list, not an error
    assert detect.health()["accessibility"] != "unknown" or detect._ax_trusted() is None
