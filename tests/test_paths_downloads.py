"""Exports in tests never reach the user's Downloads folder."""
import os
import tempfile
from pathlib import Path

from ecoscribe import paths
from ecoscribe.window import Api


def test_the_tests_downloads_folder_is_a_temporary_one(tmp_path):
    d = paths.downloads_dir()
    assert str(d).startswith(tempfile.gettempdir()) and "ecoscribe-test-downloads-" in str(d)
    api = Api(data_dir=tmp_path / "data", config_path=tmp_path / "config.toml")
    assert api._downloads == d


def test_without_the_override_it_is_the_users_downloads(monkeypatch):
    monkeypatch.delenv("ECOSCRIBE_DOWNLOADS")
    monkeypatch.setenv("USERPROFILE", str(Path("/u")))
    assert paths.downloads_dir() == Path("/u") / "Downloads"
