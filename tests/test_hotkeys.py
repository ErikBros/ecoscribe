import sys

import pytest

from ecoscribe import hotkeys

# Windows key rules (VK codes, Win key, AltGr). The Mac rules are in test_mac_keys.py.
win_rules = pytest.mark.skipif(sys.platform == "darwin", reason="Windows shortcut rules")


@win_rules
def test_lone_keys_and_combos_parse():
    assert hotkeys.parse("rctrl") == (frozenset(), "rctrl")
    assert hotkeys.normalize("Shift + Ctrl + D") == "ctrl+shift+d"
    assert hotkeys.normalize("ctrl+l") == "ctrl+l"
    assert hotkeys.normalize("win+f9") == "win+f9"
    assert hotkeys.label("ctrl+shift+d") == "Ctrl+Shift+D" and hotkeys.label("rctrl") == "Right Ctrl"
    assert hotkeys.label("alt+f9") == "Alt+F9"


@win_rules
@pytest.mark.parametrize("bad", ["", "l", "f5", "ctrl+c", "ctrl+v", "alt+tab", "alt+f4", "win+l",
                                 "ctrl+alt+d", "hyper+d", "ctrl+ctrl+d", "ctrl+esc", "ctrl+enter"])
def test_refused(bad):
    with pytest.raises(ValueError):
        hotkeys.parse(bad)


def feed(m, *events):
    return [m.key(vk, down) for vk, down in events]


LCTRL, RCTRL, SHIFT, L = 0xA2, 0xA3, 0xA0, 0x4C


@win_rules
def test_combo_fires_once_and_is_swallowed():
    m = hotkeys.ComboMatcher("ctrl+l")
    out = feed(m, (LCTRL, True), (L, True), (L, True), (L, False), (LCTRL, False))
    assert out == [(False, False), (True, True), (False, True), (False, True), (False, False)]


@win_rules
def test_either_ctrl_counts_and_extra_modifiers_dont_match():
    m = hotkeys.ComboMatcher("ctrl+l")
    assert feed(m, (RCTRL, True), (L, True), (L, False), (RCTRL, False))[1] == (True, True)
    assert feed(m, (LCTRL, True), (SHIFT, True), (L, True), (L, False))[2] == (False, False)  # Ctrl+Shift+L passes through


def test_plain_key_passes_through():
    m = hotkeys.ComboMatcher("ctrl+l")
    assert feed(m, (L, True), (L, False)) == [(False, False), (False, False)]


def test_cancel_hint_on_the_pill():
    """t0u.36: the Dictating pill says how to cancel. A combo has no Esc cancel (tray only)."""
    from ecoscribe.hotkeys import cancel_hint
    assert cancel_hint("rctrl") == "Right Ctrl + Esc to cancel"
    assert cancel_hint("f13") == "F13 + Esc to cancel"
    assert cancel_hint("ctrl+l") == "Cancel from the tray icon"


@win_rules
def test_command_mode_keys():
    """dictado-a1d: the dictation key + a letter (as the picker records it, or bare), or a combo of its own."""
    nc = hotkeys.normalize_command
    assert nc("rctrl+e", "rctrl") == "e" and nc("K", "rctrl") == "k" and nc("f13+7", "f13") == "7"
    assert nc("Shift + Ctrl + E", "rctrl") == "ctrl+shift+e" and nc("ctrl+shift+e", "ctrl+l") == "ctrl+shift+e"
    assert hotkeys.command_label("e", "rctrl") == "Right Ctrl + E" and hotkeys.command_label("ctrl+shift+e", "rctrl") == "Ctrl+Shift+E"
    assert hotkeys.command_parts("e")[0] == 0x45 and hotkeys.command_parts("e")[1] is None
    vk, combo = hotkeys.command_parts("ctrl+shift+e")
    assert vk == 0 and combo.spec == "ctrl+shift+e"


@win_rules
@pytest.mark.parametrize("value,dictation,why", [
    ("l", "rctrl", "next dictation's language"), ("rctrl+r", "rctrl", "pasting the last dictation"),
    ("e", "ctrl+l", "is a combo"), ("ctrl+l", "ctrl+l", "is the dictation key"), ("ctrl+c", "rctrl", "taken"),
    ("f14", "rctrl", "lone key"), ("ctrl+f13", "f13", "is the dictation key"), ("enter", "rctrl", "letter or a digit")])
def test_command_mode_keys_refused(value, dictation, why):
    with pytest.raises(ValueError, match=why):
        hotkeys.normalize_command(value, dictation)
