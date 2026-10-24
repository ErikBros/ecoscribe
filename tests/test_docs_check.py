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
