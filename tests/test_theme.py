"""Dark mode (dictado-u9h): Settings > Appearance is Match the system, Light or Dark; saving it needs no restart,
and the window starts in the right colour."""
import sys

import pytest

from ecoscribe import config, window


def _api(tmp_path, signals):
    class Startup:
        def is_enabled(self): return False
        def app_command(self): return None
    return window.Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", startup_mod=Startup(),
                      signal_reload=lambda: signals.append(1) or True, list_mic_names=lambda: [])


def test_appearance_saves_without_a_restart(tmp_path):
    signals = []
    a = _api(tmp_path, signals)
    assert config.Config().ui.theme == "system" and a.get_theme() == {"theme": "system"}
    s = a.get_settings()
    assert s["values"]["theme"] == "system" and [o["value"] for o in s["options"]["themes"]] == ["system", "light", "dark"]
    assert a.save_settings({"theme": "dark"}) == {"ok": True, "restarting": False} and not signals
    assert a.get_theme() == {"theme": "dark"}
    assert not a.save_settings({"theme": "purple"})["ok"]
    assert a.save_settings({"theme": "light", "sounds": False})["ok"] and signals  # with anything else: as before


def test_which_themes_are_dark(monkeypatch):
    monkeypatch.setattr(window, "_system_dark", lambda: True)
    assert window.theme_is_dark("system") and window.theme_is_dark("dark") and not window.theme_is_dark("light")
    monkeypatch.setattr(window, "_system_dark", lambda: False)
    assert not window.theme_is_dark("system")
    monkeypatch.setattr(window, "_system_dark", lambda: 1 / 0)
    assert not window.theme_is_dark("system")  # unreadable: light


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry and DWM")
def test_windows_reads_its_app_mode_and_never_fails_on_the_title_bar(tmp_path):
    from ecoscribe.platform.windows.desktop import dark_title_bar, system_dark
    assert isinstance(system_dark(), bool)
    assert dark_title_bar("no such window here", True) is False
    assert _api(tmp_path, []).window_theme(True) == {"ok": False}  # no window open in a test
