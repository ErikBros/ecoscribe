"""The Settings tabs are Dictation, Words, Meetings and General (dictado-o955).

Nothing in the app, its tests or its guides may still point at a section name from
before that change, or the user is sent to a tab that does not exist and the desktop
test clicks a button that is gone (dictado-r9au).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_NAMES = ("Languages and words", "Help and setup")
SCAN = ("ecoscribe", "tests", "docs", "tools")
SUFFIXES = {".py", ".js", ".mjs", ".html", ".md", ".swift"}


def _tabs():
    html = (ROOT / "ecoscribe" / "web" / "index.html").read_text(encoding="utf-8")
    return re.findall(r'<button type="button" class="seg[^"]*" data-sec="[^"]+">([^<]+)</button>', html)


def test_settings_tabs_are_the_four_from_o955():
    assert _tabs() == ["Dictation", "Words", "Meetings", "General"]


def test_no_old_section_name_left():
    me = Path(__file__).resolve()
    hits = []
    for top in SCAN:
        for path in (ROOT / top).rglob("*"):
            if path.suffix not in SUFFIXES or path.resolve() == me or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for n, line in enumerate(text.splitlines(), 1):
                for old in OLD_NAMES:
                    if old.lower() in line.lower():
                        hits.append(f"{path.relative_to(ROOT)}:{n}: {old}")
    assert not hits, "old Settings section names:\n" + "\n".join(hits)


def test_empty_replace_list_messages_name_the_words_tab():
    assert "Words" in _tabs()
    want = "add pairs in Settings › Words."
    for rel in ("ecoscribe/window.py", "ecoscribe/web/app.js"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Your Replace list is empty: " + want in text, rel


def test_desktop_test_clicks_a_tab_that_exists():
    text = (ROOT / "tests" / "test_quiet_window.py").read_text(encoding="utf-8")
    tabs = set(_tabs())
    clicked = re.findall(r'get_by_role\("button", name="([^"]+)"\)', text)
    # Settings and Meetings are the side menu; the rest must be a Settings tab.
    for name in clicked:
        if name not in {"Settings", "Meetings"}:
            assert name in tabs, f"test_quiet_window clicks {name!r}, not a Settings tab"
