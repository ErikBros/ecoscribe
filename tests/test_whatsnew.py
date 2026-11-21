"""What's new after an update (dictado-owyk): one list feeds Home's card and the release notes."""
import json
import sys
from pathlib import Path

import pytest

from ecoscribe import __version__, updates, whatsnew

NOTES = {
    "1.4.0": [{"title": "Four", "text": "four is here."}],
    "1.5.0": [{"title": "Five", "text": "five is here."}, {"title": "Five on the Mac", "only": "mac"}],
    "1.6.0": [{"title": "Six", "text": "six is here."}, {"title": "Six on Windows", "text": "only there.", "only": "windows"}],
}


INDEX = (Path(__file__).resolve().parent.parent / "ecoscribe" / "web" / "index.html").read_text(encoding="utf-8")
WINDOW_PAGES = {"inicio", "reuniones", "historial", "insights", "ajustes"}


@pytest.fixture
def notes(monkeypatch):
    monkeypatch.setattr(whatsnew, "NOTES", NOTES)
    monkeypatch.setattr(whatsnew, "FIRST_CARD", "1.4.0")


def titles(card):
    return [i["title"] for i in card.get("items", [])]


def test_this_version_has_notes():
    """A version bump writes what's new: Home shows it and tools/release.py makes the release notes from it."""
    assert whatsnew.NOTES.get(__version__), f"add {__version__}'s lines to ecoscribe/whatsnew.py"


def test_notes_are_short_plain_lines():
    for v, rows in whatsnew.NOTES.items():
        assert updates.parse(v), v
        for n in rows:
            assert set(n) <= {"title", "text", "only", "show"} and n["title"].strip(), (v, n)
            if "show" in n:  # Show me (dictado-3zfe): a window page, a place on its map, spots with a hint each
                w = n["show"]
                assert w["page"] in WINDOW_PAGES and 0 <= w.get("y", 0) <= 1 and w["spots"], (v, n)
                assert set(w) <= {"page", "card", "y", "spots"}, (v, n)
                if "card" in w:
                    assert f'data-card="{w["card"]}"' in INDEX, f'no Settings card {w["card"]} ({v})'

                for sel, hint in w["spots"]:
                    assert sel.startswith("#") and hint.strip() and len(hint) <= 90, (v, n)
                    assert f'id="{sel[1:].split()[0]}"' in INDEX, f"{sel} isn't in the window ({v})"
            assert n.get("only") in (None, "windows", "mac"), (v, n)
            assert len(n["title"]) <= 40 and len(n.get("text", "")) <= 220, (v, n)
            assert "*" not in n["title"] and ":" not in n["title"], (v, n)  # the release notes' bold title


def test_fresh_install_shows_nothing_and_marks_seen(tmp_path, notes):
    assert whatsnew.pending(tmp_path, "1.6.0", updated=False) == {}
    assert whatsnew.load(tmp_path) == {"seen": "1.6.0"}
    assert whatsnew.pending(tmp_path, "1.6.0", updated=True) == {}


def test_update_from_before_the_card_shows_every_version_since_the_card(tmp_path, notes, monkeypatch):
    monkeypatch.setattr(whatsnew, "FIRST_CARD", "1.6.0")
    card = whatsnew.pending(tmp_path, "1.6.0", updated=True, platform="windows")
    assert card["version"] == "1.6.0" and titles(card) == ["Six", "Six on Windows"]
    assert card["items"][0] == {"title": "Six", "text": "six is here."}
    monkeypatch.setattr(whatsnew, "FIRST_CARD", "1.5.0")  # skipped the first version with the card: both
    assert titles(whatsnew.pending(tmp_path, "1.6.0", True, "mac")) == ["Six", "Five", "Five on the Mac"]


def test_skipped_versions_newest_first_per_platform(tmp_path, notes):
    whatsnew.mark_seen(tmp_path, "1.4.0")
    assert titles(whatsnew.pending(tmp_path, "1.6.0", True, "mac")) == ["Six", "Five", "Five on the Mac"]
    assert titles(whatsnew.pending(tmp_path, "1.6.0", True, "windows")) == ["Six", "Six on Windows", "Five"]


def test_closed_stays_closed_until_the_next_update(tmp_path, notes):
    whatsnew.mark_seen(tmp_path, "1.5.0")
    assert whatsnew.pending(tmp_path, "1.6.0", True)
    whatsnew.mark_seen(tmp_path, "1.6.0")
    assert whatsnew.pending(tmp_path, "1.6.0", True) == {}
    assert whatsnew.pending(tmp_path, "1.5.0", True) == {}  # a downgrade shows nothing


def test_a_version_without_notes_shows_nothing(tmp_path, notes):
    whatsnew.mark_seen(tmp_path, "1.6.0")
    assert whatsnew.pending(tmp_path, "1.7.0", True) == {}


def test_card_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(whatsnew, "NOTES", {"2.0.0": [{"title": f"T{i}"} for i in range(10)]})
    assert len(whatsnew.pending(tmp_path, "2.0.0", True)["items"]) == whatsnew.MAX_LINES


def test_broken_state_file_counts_as_unseen(tmp_path, notes):
    (tmp_path / whatsnew.STATE).write_text("{not json", encoding="utf-8")
    assert titles(whatsnew.pending(tmp_path, "1.6.0", True, "windows"))[0] == "Six"
    (tmp_path / whatsnew.STATE).write_text(json.dumps(["x"]), encoding="utf-8")
    assert whatsnew.pending(tmp_path, "1.6.0", False) == {}


def test_show_me_reaches_the_card_but_not_the_release_notes(tmp_path, monkeypatch):
    show = {"page": "reuniones", "y": 0.2, "spots": [["#r-tags", "Click a tag."]]}
    monkeypatch.setattr(whatsnew, "NOTES", {"3.0.0": [{"title": "Tags", "text": "sort.", "show": show}, {"title": "Plain"}]})
    card = whatsnew.pending(tmp_path, "3.0.0", True)
    assert card["items"][0]["show"] == show and "show" not in card["items"][1]
    assert "r-tags" not in whatsnew.release_notes("3.0.0")


def test_release_notes_sections(notes):
    text = whatsnew.release_notes("1.5.0")
    assert text.startswith("## What's new\n\n- **Five:** five is here.\n")
    assert "## Mac\n\n- **Five on the Mac**\n" in text and "## Windows" not in text
    assert whatsnew.release_notes("9.9.9") == ""


def test_release_highlights_skip_the_other_platform(notes):
    body = whatsnew.release_notes("1.6.0") + "\n## Mac\n\n- **Only Mac:** yes\n"
    assert updates.highlights(body, "windows") == ["Six", "Six on Windows"]
    assert updates.highlights(body, "mac") == ["Six", "Only Mac"]
    assert updates.highlights(None) == [] and updates.highlights("- plain line\n") == []


def test_notice_carries_highlights_and_fetch_reads_them(tmp_path):
    body = "## What's new\n\n- **Faster start:** it is.\n- **Tags:** sort meetings.\n"
    class R:
        def __init__(self, d): self.d = d
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return json.dumps(self.d).encode()
    got = updates.fetch_release(opener=lambda req, timeout: R({"tag_name": "v9.1.0", "body": body, "assets": []}))
    assert got["highlights"] == ["Faster start", "Tags"]
    updates.check(tmp_path, now=1.0, fetch=lambda: got)
    n = updates.notice(updates.load(tmp_path), "9.0.0", need_installer=False)
    assert n["highlights"] == ["Faster start", "Tags"]


def test_window_api_card_and_dismiss(tmp_path, monkeypatch):
    from ecoscribe import window
    monkeypatch.setattr(whatsnew, "NOTES", {__version__: [{"title": "Shiny", "text": "it shines."}]})
    api = window.Api.__new__(window.Api)
    api._data_dir = tmp_path
    (tmp_path / "welcome_done").write_text("x", encoding="utf-8")
    card = api.whats_new()
    assert titles(card) == ["Shiny"] and card["url"].endswith(f"/v{__version__}")
    assert api.dismiss_whats_new() == {"ok": True} and api.whats_new() == {}


def test_release_writes_notes_from_whatsnew(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    try:
        import release
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(release.tempfile, "gettempdir", lambda: str(tmp_path))
    p = release.notes_from_whatsnew(__version__)
    assert p and p.read_text(encoding="utf-8") == whatsnew.release_notes(__version__)
    assert release.notes_from_whatsnew("0.0.1") is None
