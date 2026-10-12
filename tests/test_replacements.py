"""The Replace list (dictado-b7u): heard -> written, applied to dictations and meeting transcripts."""


def test_app_applies_replacements(tmp_path):
    from ecoscribe.app import App
    from ecoscribe.config import Config
    from ecoscribe.deliver import DeliveryResult
    from ecoscribe.engine import Result
    from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait
    cfg = Config()
    cfg.text.replacements = {"poll request": "pull request"}
    out = []

    class Eng:
        def transcribe(self, audio):
            return Result(text="Open a poll request. ", lang="en", speech_s=1.0, ms=5)
    app = App(cfg, FakeRecorder(), Eng(), lambda t: out.append(t) or DeliveryResult(True, "x.exe", "ok"), FakeUi(),
              gate=FakeGate(), history_path=tmp_path / "h.jsonl")
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: out == ["Open a pull request. "])


def test_setting_round_trips_and_survives_a_reload(tmp_path):
    from ecoscribe import config
    from ecoscribe.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.get_settings()["values"]["replacements"] == []
    rows = [{"heard": "  Poll   Request ", "write": "pull request"}, {"heard": "eco scribe", "write": "Ecoscribe"},
            {"heard": "", "write": "dropped"}, {"heard": "x", "write": ""}, {"heard": "poll request", "write": "dup dropped"}]
    assert api.save_settings({"replacements": rows})["ok"]
    want = [{"heard": "poll request", "write": "pull request"}, {"heard": "eco scribe", "write": "Ecoscribe"}]
    assert api.get_settings()["values"]["replacements"] == want
    assert config.load(tmp_path / "config.toml").text.replacements == {"poll request": "pull request", "eco scribe": "Ecoscribe"}
