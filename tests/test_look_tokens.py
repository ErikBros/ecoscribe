"""One look (dictado-u9h): every colour, corner and font size of the window comes from the :root tokens in
app.css, and the native surfaces (pill, tray, prompt box) from ecoscribe/palette.py, which the light tokens
match. A value written anywhere else fails here, so a new screen can't drift from the set (or from dark mode).
Reads the files only: runs the same on Windows, macOS and CI."""
import ast
import re
from pathlib import Path

import pytest

from ecoscribe import palette

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "ecoscribe" / "web"
CSS = (WEB / "app.css").read_text(encoding="utf-8")
TOKEN_BLOCK = re.compile(r":root(\[[^\]]*\])?\s*\{([^}]*)\}")
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(|(?<![\w-])(?:white|black)(?![\w-])", re.IGNORECASE)
# drawings, not icons: their strokes are part of the picture
DRAWINGS = (".hero-wave", ".r-now-wave", ".i-chart")


def _blocks() -> dict[str, dict[str, str]]:
    """{"": light tokens, '[data-theme="dark"]': dark tokens}"""
    out = {}
    for m in TOKEN_BLOCK.finditer(CSS):
        body = re.sub(r"/\*.*?\*/", "", m.group(2), flags=re.S)
        out[m.group(1) or ""] = {k.strip(): v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)}
    return out


def _rules() -> list[tuple[str, str]]:
    """(selector, declarations) of every rule outside the token blocks, comments dropped."""
    rest = re.sub(r"/\*.*?\*/", "", TOKEN_BLOCK.sub("", CSS), flags=re.S)
    rest = re.sub(r"@font-face\s*\{[^}]*\}", "", rest)
    return [(s.strip().split("{")[-1].strip(), d) for s, d in re.findall(r"([^{}]+)\{([^{}]*)\}", rest)]


def _decls(name: str):
    for sel, body in _rules():
        for m in re.finditer(rf"(?<![\w-]){name}\s*:\s*([^;]+)", body):
            yield sel, m.group(1).strip()


def test_there_is_a_light_and_a_dark_set():
    b = _blocks()
    assert set(b) == {"", '[data-theme="dark"]'}, set(b)
    assert b['[data-theme="dark"]'].keys() <= b[""].keys(), "dark mode may only redefine tokens the light set has"
    assert "color-scheme: dark" in CSS


def test_no_colour_outside_the_tokens():
    stray = [f"{sel} {{ {d.strip()[:80]} }}" for sel, d in _rules()
             if COLOUR.search(re.sub(r"url\([^)]*\)", "", d))]  # an inline SVG's own %23 colours are data
    assert not stray, "write a var(--token) from app.css :root instead:\n" + "\n".join(stray)


def test_corners_come_from_the_tokens():
    bad = [f"{sel}: {v}" for sel, v in _decls("border-radius")
           if any(p not in ("0", "50%") and not p.startswith("var(--radius") for p in v.split())]
    assert not bad, "use --radius-* tokens:\n" + "\n".join(bad)


def test_font_sizes_come_from_the_tokens():
    size = re.compile(r"\b\d+(\.\d+)?(px|em|rem|pt)\b")
    bad = [f"{sel}: {v}" for sel, v in _decls("font-size") if size.search(v)]
    bad += [f"{sel}: font: {v}" for sel, v in _decls("font") if size.search(v)]
    assert not bad, "use --fs-* tokens:\n" + "\n".join(bad)


def test_icons_share_one_stroke():
    bad = [f"{sel}: {v}" for sel, v in _decls("stroke-width")
           if not v.startswith("var(--icon-stroke") and not any(d in sel for d in DRAWINGS)]
    assert not bad, "line icons use var(--icon-stroke):\n" + "\n".join(bad)


def test_every_token_used_is_defined():
    defined = _blocks()[""].keys()
    used = set()
    for f in ("app.css", "index.html", "app.js"):
        used |= set(re.findall(r"var\((--[\w-]+)", (WEB / f).read_text(encoding="utf-8")))
    assert not used - defined, f"undefined tokens: {sorted(used - defined)}"


@pytest.mark.parametrize("name", ["index.html", "app.js"])
def test_the_page_and_its_script_write_no_colours(name):
    text = (WEB / name).read_text(encoding="utf-8")
    hits = re.findall(r"""(?:fill|stroke|color|background)\s*[=:]\s*["']?(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))""", text)
    assert not hits, f"{name}: {hits} (use var(--token))"


# CSS token -> the palette.py name with the same colour (the pill, tray and prompt box use palette.py)
SHARED = {"--paper": "PAPER", "--ink": "INK", "--aegean": "AEGEAN", "--tile": "TILE", "--ink-soft": "INK_SOFT",
          "--line": "LINE", "--aegean-soft": "AEGEAN_SOFT", "--tile-soft": "TILE_SOFT", "--clay-light": "CLAY_LIGHT",
          "--night": "INK", "--night-line": "KEYCAP_LINE", "--night-wave": "AEGEAN_MID", "--on-accent-soft": "AEGEAN_PALE",
          "--on-night-accent": "AEGEAN_MUTED", "--logo": "AEGEAN", "--logo-line": "PAPER", "--on-night": "PAPER"}


def test_the_light_tokens_match_palette_py():
    light = _blocks()[""]
    wrong = {k: (light.get(k), getattr(palette, v)) for k, v in SHARED.items() if (light.get(k) or "").lower() != getattr(palette, v).lower()}
    assert not wrong, f"app.css and palette.py disagree: {wrong}"
    assert _blocks()['[data-theme="dark"]']["--paper"].lower() == palette.PAPER_DARK.lower()


def test_python_colours_live_in_palette_py():
    hex_str = re.compile(r"^#[0-9a-fA-F]{6}$")
    bad = []
    for f in (ROOT / "ecoscribe").rglob("*.py"):
        if f.name == "palette.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and hex_str.match(node.value):
                bad.append(f"{f.relative_to(ROOT)}:{node.lineno} {node.value}")
    assert not bad, "add it to ecoscribe/palette.py:\n" + "\n".join(bad)
