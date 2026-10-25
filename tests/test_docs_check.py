"""The user guides (dictado-xr3v): pr-shape's docs check, and every link in docs/ lands somewhere."""
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("docs_check", REPO / "tools" / "docs_check.py")
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)


def test_a_ui_change_without_docs_or_reason_fails():
    err = dc.check(["ecoscribe/web/app.js", "tests/ui/smoke.test.js"], "Adds a button.")
    assert err and "ecoscribe/web/app.js" in err and "docs: not needed, because" in err


def test_a_ui_change_with_a_guide_change_passes():
    assert dc.check(["ecoscribe/web/index.html", "docs/meetings.md"], "") is None


def test_the_look_checklist_is_not_a_guide():
    assert dc.check(["ecoscribe/web/app.css", "docs/look-checklist.md"], "")


def test_a_reason_on_its_own_line_passes():
    body = "Fixes the spacing.\n\n- docs: not needed, because nothing a guide describes changes\n"
    assert dc.check(["ecoscribe/platform/windows/pillart.py"], body) is None


def test_a_reason_needs_words_after_because():
    assert dc.check(["ecoscribe/meetui.py"], "docs: not needed, because")


def test_logic_only_changes_need_nothing():
    assert dc.check(["ecoscribe/engine.py", "tools/before_after.py", "tests/test_engine_proc.py"], "") is None


def _slug(heading: str) -> str:  # GitHub's anchor for a heading
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def _anchors(md: Path) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#+\s+(.+)$", md.read_text(encoding="utf-8"), re.M)}


def test_every_link_in_the_guides_lands():
    bad = []
    for md in sorted((REPO / "docs").glob("*.md")) + [REPO / "README.md"]:
        for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, anchor = target.partition("#")
            dest = (md.parent / path).resolve() if path else md
            if not dest.exists():
                bad.append(f"{md.name}: {target} (no such file)")
            elif anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
                bad.append(f"{md.name}: {target} (no such heading)")
    assert not bad, "\n".join(bad)


def test_every_guide_is_on_the_index():
    index = (REPO / "docs" / "README.md").read_text(encoding="utf-8")
    missing = [p.name for p in (REPO / "docs").glob("*.md")
               if p.name not in {"README.md", *(Path(n).name for n in dc.NOT_GUIDES)} and f"({p.name})" not in index]
    assert not missing, missing


def test_the_window_opens_only_the_guides_of_its_own_version(tmp_path, monkeypatch):
    """Api.open_guide (dictado-2xpp): a guide by name, as of this version's tag; anything else is refused."""
    from ecoscribe.window import GUIDES, Api
    opened = []
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", open_url=opened.append)
    monkeypatch.setattr("ecoscribe.window.__version__", "1.24.0")
    assert api.open_guide("meetings", "before-you-record") == {"ok": True}
    assert opened == ["https://github.com/ErikBros/ecoscribe/blob/v1.24.0/docs/meetings.md#before-you-record"]
    for page, sec in (("../README", ""), ("look-checklist", ""), ("dictation", "x\"y"), ("https://example.com", "")):
        assert api.open_guide(page, sec) == {"ok": False}
    assert len(opened) == 1
    assert all((REPO / "docs" / f"{g}.md").exists() for g in GUIDES)


def test_every_guide_link_in_the_window_lands():
    """data-guide="page#heading" in the window: the guide exists and has that heading (#os: both platforms')."""
    from ecoscribe.window import GUIDES
    targets = set(re.findall(r'data-guide="([^"]+)"', (REPO / "ecoscribe" / "web" / "index.html").read_text(encoding="utf-8")))
    assert targets
    bad = []
    for t in sorted(targets):
        page, _, anchor = t.partition("#")
        if page not in GUIDES:
            bad.append(f"{t}: not a guide")
            continue
        for a in (("windows", "mac") if anchor == "os" else (anchor,) if anchor else ()):
            if a not in _anchors(REPO / "docs" / f"{page}.md"):
                bad.append(f"{t}: no heading #{a}")
    assert not bad, "\n".join(bad)
