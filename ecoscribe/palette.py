"""The Ecoscribe palette. Every Ecoscribe surface uses only these."""
PAPER = "#f6f5f1"
INK = "#18212b"
AEGEAN = "#23557a"
TILE = "#b0491c"
# derived tints
INK_SOFT = "#4f5966"
LINE = "#e4e1da"
AEGEAN_SOFT = "#e4edf4"
TILE_SOFT = "#f6e3d9"
CLAY_LIGHT = "#e58a5f"  # the logo's dot, on aegean (dictado-6oe.1)
TILE_DIM = "#7a3a17"   # the recording dot between breaths, on ink
TILE_HALO = "#4a2a1f"  # the soft ring around the lit recording dot, on ink (dictado-6oe.9)
PILL_OFF = "#4a525c"   # unlit level bar on the ink pill; a quiet button on ink
INK_2 = "#323a45"      # a raised surface on ink (the language menu, a pressed quiet button)
AEGEAN_BRIGHT = "#3a77a4"  # aegean that reads on ink (a primary button on the dark box)

# overlays as one family, on ink (dictado-6oe.9)
KEYCAP_LINE = "#4a5563"   # the outline of a keycap in the pill's hint
AEGEAN_MID = "#7fa6c4"    # the prompt's countdown line; the busy pill's middle dot
AEGEAN_PALE = "#c9dcea"   # the busy pill's last dot
AEGEAN_MUTED = "#9db7cc"  # the glyph on a prompt's tile (clock, mic, page)
PAPER_HOVER = "#dfe5ea"   # the light primary button under the mouse
CLAY_BRIGHT = "#e06a35"   # the dot on the "a call started" tile
TILE_CALL = "#3a2a22"     # the icon tile of "a call started"
TILE_NOTE = "#2a3542"     # the icon tile of every other prompt

# dictado-u9h: the window in dark mode (its page colour, before the page paints) and the prompt box's
# transparency key (not a colour anyone sees)
PAPER_DARK = "#10161c"
COLOR_KEY = "#010203"


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
