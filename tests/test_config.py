import pytest

from ecoscribe import config

MAC = config.MAC
DEF_KEY, DEF_VK = ("rcmd", 54) if MAC else ("rctrl", 0xA3)
DEF_MIC, DEF_HOST = "", ("Core Audio" if MAC else "MME")


def test_defaults():
    c = config.load(None)
    assert c.hotkey.key == DEF_KEY
    assert c.hotkey.vk == DEF_VK
    assert c.audio.device == DEF_MIC
    assert c.audio.host == DEF_HOST
    assert c.whisper.model == "large-v3-turbo"
    assert c.whisper.languages == ["en"]
    assert c.limits.max_record_s == 600.0


def test_toml_overrides_merge(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[audio]\ndevice = "Blue Yeti"\n[whisper]\nlanguages = ["es"]\n', encoding="utf-8")
    c = config.load(p)
    assert c.audio.device == "Blue Yeti"
    assert c.audio.host == DEF_HOST
    assert c.whisper.languages == ["es"]
    assert c.whisper.model == "large-v3-turbo"


def test_unknown_key_ignored(tmp_path, caplog):
    p = tmp_path / "config.toml"
    p.write_text('[audio]\nbogus = 1\n[nope]\nx = 2\n', encoding="utf-8")
    c = config.load(p)
    assert c.audio.device == DEF_MIC
    assert "bogus" in caplog.text


def test_ralt_forbidden(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\nkey = "ralt"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        config.load(p)


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "absent.toml").hotkey.key == DEF_KEY


def test_meetings_defaults_and_round_trip(tmp_path):
    from ecoscribe import tomlw
    c = config.load(None)
    assert (c.meetings.mode, c.meetings.grace_s, c.meetings.silence_stop_s, c.meetings.default_lang) == \
        ("prompt", 10, 180, "en")  # English by default (dictado-607)
    c.meetings.mode, c.meetings.default_lang = "auto", "sv"
    p = tmp_path / "c.toml"
    tomlw.save(c, p)
    back = config.load(p)
    assert back.meetings.mode == "auto" and back.meetings.default_lang == "sv"


def test_a_saved_old_call_end_wait_moves_to_10_s(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[meetings]\ngrace_s = 20\n", encoding="utf-8")
    assert config.load(p).meetings.grace_s == 10  # the old default, written by every Settings save
    p.write_text("[meetings]\ngrace_s = 30\n", encoding="utf-8")
    assert config.load(p).meetings.grace_s == 30  # a value the user chose stays
