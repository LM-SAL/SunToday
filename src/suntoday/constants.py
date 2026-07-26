"""
Constants about SDO/AIA or the combinations.

TODO: Probably should be config.
"""

from functools import partial

from astropy.visualization import (
    AsinhStretch,
    AsymmetricPercentileInterval,
    ImageNormalize,
    LinearStretch,
    LogStretch,
)
from matplotlib import colors

__all__ = [
    "AIA_193_IDL_NORM",
    "AIA_COLORS",
    "AIA_SINGLE_NORMS",
    "AIA_WAVELENGTHS",
    "HMI_NORM_GAUSS",
    "RGB_COMBINATIONS",
    "RGB_MAX_PERCENTILE",
    "RGB_RECIPES",
]
# HMI magnetogram display half-range in Gauss; the polarity blend in jpegs.py
# has its own saturation, tuned separately.
HMI_NORM_GAUSS = 100
# Norm overrides for single-channel JPEGs; unlisted channels get sunpy's
# default stretch plus the AIA_CLIP_INTERVAL clip in jpegs.py. Factories, not
# instances: norms cache limits, so each figure needs a fresh one.
# 1600/1700: with the default treatment the disk saturates near-white and the
# CCD bleed glows around it. The disk covers just under half the frame, so a
# floor at the 50th percentile blacks out sky and bleed, and the linear
# stretch spreads the plage network over the range instead of piling it at
# white. Limits still autoscale per frame.
AIA_SINGLE_NORMS = {
    "1600": partial(ImageNormalize, interval=AsymmetricPercentileInterval(50, 99.99), stretch=LinearStretch()),
    "1700": partial(ImageNormalize, interval=AsymmetricPercentileInterval(50, 99.99), stretch=LinearStretch()),
}
# The extra full-resolution-only 193 product (f0193i.jpg) with the previous
# IDL pipeline's absolute scaling, in degradation-corrected DN/s:
#   bytscl(alog10(image*(2.9995/exptime) > (120d/2.2) < (6000d/2.2)))
# clip=True matches IDL's bytscl of a hard-clipped image.
AIA_193_IDL_NORM = partial(colors.LogNorm, vmin=65.5, vmax=3021.0, clip=True)
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
# Channels saved as planning FITS only, no JPEGs.
AIA_FITS_ONLY_WAVELENGTHS = ["4500"]
# Recipe per RGB composite, keyed by the (R, G, B) wavelength combo:
# (per-channel interval multipliers, stretch). Each channel is clipped to
# [0, multiplier * shared max] before the stretch; the shared max is the
# largest RGB_MAX_PERCENTILE'th percentile over the three channels.
# Multipliers tuned by eye. Stretches are stateless and safe to share.
RGB_MAX_PERCENTILE = 99
RGB_RECIPES = {
    ("211", "193", "171"): ((0.3, 0.9, 0.8), AsinhStretch(0.04)),
    ("304", "211", "171"): ((1.0, 1.0, 1.0), AsinhStretch(0.04)),
    ("94", "335", "193"): ((0.04, 0.15, 1.5), LogStretch(100)),
}
RGB_COMBINATIONS = list(RGB_RECIPES)
