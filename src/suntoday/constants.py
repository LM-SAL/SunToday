"""
Constants about SDO/AIA or the combinations.

TODO: Probably should be config.
"""

__all__ = [
    "AIA_COLORS",
    "AIA_WAVELENGTHS",
    "BLEND_COMBINATIONS",
    "RGB_COMBINATIONS",
]
AIA_COLORS = {
    "131": "blue",
    "1600": "green",
    "1700": "crimson",
    "171": "gold",
    "193": "brown",
    "211": "purple",
    "304": "darkorange",
    "335": "darkblue",
    "94": "darkgreen",
}
AIA_WAVELENGTHS = list(AIA_COLORS.keys())
RGB_COMBINATIONS = [
    ("211", "193", "171"),
    ("304", "211", "171"),
    ("94", "335", "193"),
]
BLEND_COMBINATIONS = [
    ("171", "B_LOS"),
]
GOES_PRIMARY = 19
