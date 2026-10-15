from pathlib import Path

from ecoscribe import after_hook, config, tomlw


def test_nothing_runs_without_a_command(tmp_path):
    assert after_hook.launch([], tmp_path, popen=lambda *a, **k: 1 / 0) is None


def test_the_session_folder_is_the_last_argument(tmp_path):
    seen = {}

    def popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return "proc"

    assert after_hook.launch(["py", "after.py"], tmp_path, popen=popen) == "proc"
    assert seen["args"] == ["py", "after.py", str(tmp_path)]
    assert (tmp_path / after_hook.LOG).exists()


def test_a_command_that_cannot_start_is_logged_not_raised(tmp_path):
    def popen(args, **kw):
        raise FileNotFoundError(args[0])

    assert after_hook.launch(["nope.exe"], tmp_path, popen=popen) is None


def test_the_setting_survives_a_save(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[transcribe]\nafter_transcribe = ["C:/py.exe", "C:/after.py"]\n', encoding="utf-8")
    c = config.load(p)
    assert c.transcribe.after_transcribe == ["C:/py.exe", "C:/after.py"]
    tomlw.save(c, p)
    assert config.load(Path(p)).transcribe.after_transcribe == ["C:/py.exe", "C:/after.py"]
