"""
Constants about SDO/AIA or the combinations.

TODO: Probably should be config.
"""

__all__ = [
    "AIA_COLORS",
    "AIA_SCALING",
    "AIA_WAVELENGTHS",
    "HMI_NORM_GAUSS",
    "RGB_COMBINATIONS",
]
HMI_NORM_GAUSS = 70
# Absolute display scaling per AIA channel as (kind, curve parameter, vmin,
# vmax), with vmin/vmax in the degradation-corrected DN/s that create_aia_map
# produces. "log" means log10 between the limits, which is exactly what the
# previous IDL pipeline did, e.g. for 193:
#   bytscl(alog10(image*(2.9995/exptime) > (120d/2.2) < (6000d/2.2)))
AIA_SCALING = {
    "94": ("power", 0.7, 0.33, 9.6),
    "131": ("log", None, 1.19, 223.0),
    "171": ("power", 0.5, 5.9, 1255.0),
    "193": ("log", None, 65.5, 3021.0),
    "211": ("log", None, 10.1, 4619.0),
    "304": ("log", None, 10.8, 518.0),
    "335": ("log", None, 1.03, 231.0),
    "1600": ("power", 0.7, 19.4, 737.0),
    "1700": ("power", 0.6, 268.0, 6435.0),
}
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
# Channels saved as planning FITS only, no JPEGs. Taken roughly hourly, so
# they are usually absent from the query window and never required.
AIA_FITS_ONLY_WAVELENGTHS = ["4500"]
RGB_COMBINATIONS = [
    ("211", "193", "171"),
    ("304", "211", "171"),
    ("94", "335", "193"),
]
