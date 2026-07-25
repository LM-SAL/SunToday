"""
Constants about SDO/AIA or the combinations.

TODO: Probably should be config.
"""

from functools import partial

from matplotlib import colors

__all__ = [
    "AIA_COLORS",
    "AIA_SCALING",
    "AIA_WAVELENGTHS",
    "HMI_NORM_GAUSS",
    "RGB_COMBINATIONS",
]
HMI_NORM_GAUSS = 70
# Absolute display scaling per AIA channel, as a factory that `suntoday.maps.aia_norm`
# calls for a fresh norm. vmin/vmax are in the degradation-corrected DN/s that
# create_aia_map produces. LogNorm is log10 between the limits, which is exactly what
# the previous IDL pipeline did, e.g. for 193:
#   bytscl(alog10(image*(2.9995/exptime) > (120d/2.2) < (6000d/2.2)))
# clip=True so out-of-range pixels land on the end colours instead of the "bad"
# colour, matching IDL's bytscl of a hard-clipped image.
AIA_SCALING = {
    "94": partial(colors.PowerNorm, 0.7, vmin=0.33, vmax=9.6, clip=True),
    "131": partial(colors.LogNorm, vmin=1.19, vmax=223.0, clip=True),
    "171": partial(colors.PowerNorm, 0.5, vmin=5.9, vmax=1255.0, clip=True),
    "193": partial(colors.LogNorm, vmin=65.5, vmax=3021.0, clip=True),
    "211": partial(colors.LogNorm, vmin=10.1, vmax=4619.0, clip=True),
    "304": partial(colors.LogNorm, vmin=10.8, vmax=518.0, clip=True),
    "335": partial(colors.LogNorm, vmin=1.03, vmax=231.0, clip=True),
    "1600": partial(colors.PowerNorm, 0.7, vmin=19.4, vmax=737.0, clip=True),
    "1700": partial(colors.PowerNorm, 0.6, vmin=268.0, vmax=6435.0, clip=True),
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
