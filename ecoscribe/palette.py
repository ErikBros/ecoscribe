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
PILL_OFF = "#4a525c"   # unlit level bar on the ink pill; a quiet button on ink
INK_2 = "#323a45"      # a raised surface on ink (the language menu, a pressed quiet button)
AEGEAN_BRIGHT = "#3a77a4"  # aegean that reads on ink (a primary button on the dark box)


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
