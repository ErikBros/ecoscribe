"""macOS call detection readers: Core Audio's process list -> MicUse (fake list, no Core Audio)."""
from ecoscribe.platform.macos import detect


def test_bundle_ids_map_to_the_shared_app_names():
    assert detect.app_of_bundle("com.google.Chrome.helper") == "chrome"
    assert detect.app_of_bundle("com.apple.WebKit.GPU") == "safari"
    assert detect.app_of_bundle("com.microsoft.teams2") == "msteams"


def test_a_browser_that_captures_and_plays_is_talking(monkeypatch):
    monkeypatch.setattr(detect, "_first_seen", {})
    monkeypatch.setattr(detect, "mic_users", lambda: [(11, "com.google.Chrome.helper", True),
                                                      (12, "com.tinyspeck.slackmacgap", False)])
    uses = {u.app: u for u in detect.read_consent()}
    assert uses["chrome"].in_use and uses["chrome"].talking
    assert uses["slack"].in_use and not uses["slack"].talking


def test_a_tab_only_holding_the_mic_is_not_talking(monkeypatch):
    monkeypatch.setattr(detect, "_first_seen", {})
    monkeypatch.setattr(detect, "mic_users", lambda: [(11, "com.google.Chrome.helper", False)])
    assert [(u.app, u.talking) for u in detect.read_consent()] == [("chrome", False)]
