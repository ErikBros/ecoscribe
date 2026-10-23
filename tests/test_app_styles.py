"""Style per app (dictado-h0m): the app the text goes into picks how it is written.

Four kinds (terminal, chat, email, everything else), each with capital at the start, full stop at the end and
voice commands on or off. Off by default; with it off nothing is read and every app gets the text as before.
All text here is invented.
"""
from ecoscribe import app_styles
from ecoscribe.app import App
from ecoscribe.app_styles import apply, clean_table, kind, table
from ecoscribe.config import Config
from ecoscribe.deliver import DeliveryResult
from ecoscribe.engine import Result
from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait


def test_the_app_picks_the_kind():
    assert kind("WindowsTerminal.exe") == kind("pwsh.exe") == kind("iTerm2") == kind("terminal") == "terminal"
    assert kind("slack.exe") == kind("WhatsApp") == kind("claude.exe") == kind("messages") == "chat"
    assert kind("OUTLOOK.EXE") == kind("olk.exe") == kind("Mail") == kind("thunderbird.exe") == "email"
    assert kind("notepad.exe") == kind("WINWORD.EXE") == kind("") == kind(None) == "other"


def test_in_a_browser_the_site_picks_the_kind():
    assert kind("chrome.exe", "Invented subject - Inbox - Gmail - Google Chrome") == "email"
    assert kind("msedge.exe", "Mail - Invented Person - Outlook - Microsoft Edge") == "email"
    assert kind("firefox.exe", "general - Invented Team - Slack - Mozilla Firefox") == "chat"
    assert kind("chrome.exe", "Invented chat - Claude - Google Chrome") == "chat"
    assert kind("chrome.exe", "Recipes for bread - Google Chrome") == "other"
    assert kind("chrome.exe", "") == "other"


def test_capital_and_full_stop():
    off = {"capital": False, "full_stop": False, "commands": True}
    assert apply("Run the tests and push. ", off) == "run the tests and push "
    assert apply("Git status.", off) == "git status"
    assert apply("Are you coming? ", off) == "are you coming? "  # a question mark stays
    assert apply("Wait for it... ", off) == "wait for it... "  # so does an ellipsis
    assert apply("I think so. ", off) == "I think so "  # "I" keeps its capital
    assert apply("AWS is down. ", off) == "AWS is down "  # an acronym too
    assert apply("McAllister said yes.", off) == "McAllister said yes"  # a name with a capital inside
    assert apply("Line one.\nLine two. ", off) == "line one.\nLine two "  # only the start and the very end
    assert apply("Same as today. ", table(None)["other"]) == "Same as today. "
    assert apply("", off) == ""


def test_the_table_fills_in_defaults_and_cleans_what_settings_sends():
    assert table(None) == app_styles.DEFAULTS
    assert table({"chat": {"full_stop": True}, "junk": {}})["chat"] == {"capital": True, "full_stop": True, "commands": True}
    assert table({"chat": {"full_stop": "yes"}})["chat"]["full_stop"] is False  # unreadable: the default
    rows = [{"kind": "terminal", "capital": True, "full_stop": True, "commands": False}, {"kind": "nope", "capital": 1}]
    t = clean_table(rows)
    assert t["terminal"] == {"capital": True, "full_stop": True, "commands": False} and set(t) == {k for k, _ in app_styles.KINDS}


def _run(tmp_path, text, target, on=True, title="", voice=False, styles=None, replacements=None):
    cfg = Config()
    cfg.text.replacements = replacements or {}
    cfg.text.per_app_styles, cfg.text.voice_commands = on, voice
    if styles:
        cfg.text.app_styles = styles
    out, read = [], []

    class Eng:
        def transcribe(self, audio):
            return Result(text=text, lang="en", speech_s=1.0, ms=5)

    def target_app():
        read.append(1)
        return target
    app = App(cfg, FakeRecorder(), Eng(), lambda t: out.append(t) or DeliveryResult(True, target, "ok"), FakeUi(),
              gate=FakeGate(), history_path=tmp_path / "h.jsonl", window_title=lambda: title, target_app=target_app)
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: out)
    app.shutdown()
    return out[0], bool(read)


def test_the_paste_takes_the_style_of_the_app_in_front(tmp_path):
    assert _run(tmp_path, "Git status. ", "WindowsTerminal.exe")[0] == "git status "
    assert _run(tmp_path, "See you at six. ", "slack.exe")[0] == "See you at six "
    assert _run(tmp_path, "See you at six. ", "OUTLOOK.EXE")[0] == "See you at six. "
    assert _run(tmp_path, "See you at six. ", "chrome.exe", title="Invented - Slack - Google Chrome")[0] == "See you at six "


def test_off_by_default_nothing_is_read_and_nothing_changes(tmp_path):
    assert Config().text.per_app_styles is False
    text, read = _run(tmp_path, "Git status. ", "WindowsTerminal.exe", on=False)
    assert text == "Git status. " and not read


def test_voice_commands_can_be_off_in_one_kind_of_app(tmp_path):
    styles = {"email": {"commands": False}}
    assert _run(tmp_path, "Hello, new line, bye. ", "slack.exe", voice=True, styles=styles)[0] == "Hello.\nBye "
    assert _run(tmp_path, "Hello, new line, bye. ", "OUTLOOK.EXE", voice=True, styles=styles)[0] == "Hello, new line, bye. "


def test_a_replacement_keeps_its_capital(tmp_path):
    """Style runs before Replace and Snippets: what the user wrote there is pasted as written."""
    text = _run(tmp_path, "Eco scribe is open. ", "pwsh.exe", replacements={"eco scribe": "Ecoscribe"})[0]
    assert text == "Ecoscribe is open "


def test_settings_round_trip(tmp_path):
    from ecoscribe.window import Api

    class Startup:
        def is_enabled(self): return False
        def app_command(self): return None
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", startup_mod=Startup(),
              signal_reload=lambda: False, list_mic_names=lambda: [])
    rows = api.get_settings()["values"]["app_styles"]
    assert [r["kind"] for r in rows] == ["terminal", "chat", "email", "other"] and all(r["apps"] for r in rows)
    rows = [{"kind": "chat", "capital": False, "full_stop": True, "commands": False}]
    assert api.save_settings({"per_app_styles": True, "app_styles": rows})["ok"]
    v = api._load().text
    assert v.per_app_styles is True and v.app_styles["chat"] == {"capital": False, "full_stop": True, "commands": False}
    assert v.app_styles["terminal"] == app_styles.DEFAULTS["terminal"]
