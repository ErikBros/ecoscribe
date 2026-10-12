"""The Ecoscribe palette. Every Ecoscribe surface uses only these."""
PAPER = "#fbfaf6"
INK = "#232a33"
AEGEAN = "#2e6187"
TILE = "#b3541e"
# derived tints
INK_SOFT = "#5b6470"
LINE = "#e4e1d8"
AEGEAN_SOFT = "#dbe6ef"
TILE_SOFT = "#f3e0d4"
CLAY_LIGHT = "#e58a5f"  # the logo's dot, on aegean (dictado-6oe.1)
PILL_OFF = "#4a525c"   # unlit level bar on the ink pill; a quiet button on ink
INK_2 = "#323a45"      # a raised surface on ink (the language menu, a pressed quiet button)
AEGEAN_BRIGHT = "#3a77a4"  # aegean that reads on ink (a primary button on the dark box)


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
