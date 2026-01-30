"""
Utility functions for image processing and visualization.
"""

import warnings
from pathlib import Path

import numpy as np
import sunpy.map as smap
from astropy.io.fits import CompImageHDU
from astropy.io.fits.verify import VerifyWarning

__all__ = ["apply_gamma_correction", "clip_image_percentiles", "normalize_image_percentiles", "save_fits"]


def clip_image_percentiles(
    image: np.ndarray, lower_percentile: float = 0.01, upper_percentile: float = 99.99
) -> np.ndarray:
    """
    Clip the dynamic range of an image based on percentiles.

    It will replace all NaNs with 0.

    Parameters
    ----------
    image : numpy.ndarray
        The input image to be clipped.
    lower_percentile : float, optional
        The lower percentile value to use for clipping.
        Default is 0.01.
    upper_percentile : float, optional
        The upper percentile value to use for clipping.
        Default is 99.99.

    Returns
    -------
    numpy.ndarray
        The clipped image.
    """
    image = np.nan_to_num(image)
    p_low, p_high = np.percentile(image, [lower_percentile, upper_percentile])
    return np.clip(image, p_low, p_high)


def apply_gamma_correction(image: np.ndarray, gamma: float = 0.5):
    """
    Apply gamma correction to an image.

    Parameters
    ----------
    image : `numpy.ndarray`
        The input image to apply gamma correction to.
    gamma : float, optional
        The gamma value for the correction. Default is 0.5.

    Returns
    -------
    `numpy.ndarray`
        The gamma-corrected image as an array of type uint8.

    References
    ----------
    https://en.wikipedia.org/wiki/Gamma_correction
    """
    image_normalized = image / 255.0
    image_gamma_corrected = np.power(image_normalized, gamma)
    return (image_gamma_corrected * 255).astype(np.uint8)


def normalize_image_percentiles(
    image: np.ndarray, lower_percentile: float = 0.001, upper_percentile: float = 99.8
) -> np.ndarray:
    """
    Normalize the dynamic range of an image to 0-255 based on percentiles.

    It will replace all NaNs with 0.

    Parameters
    ----------
    image : numpy.ndarray
        The input image to be normalized.
    lower_percentile : float, optional
        The lower percentile value to use for normalization.
        Default is 0.001.
    upper_percentile : float, optional
        The upper percentile value to use for normalization.
        Default is 99.8.

    Returns
    -------
    numpy.ndarray
        The normalized image as an array of type uint8.
    """
    image = np.nan_to_num(image)
    p_low, p_high = np.percentile(image, [lower_percentile, upper_percentile])
    image_clipped = np.clip(image, p_low, p_high)
    norm_image = 255 * (image_clipped - p_low) / (p_high - p_low)
    return norm_image.astype(np.uint8)


def save_fits(amap: smap.GenericMap, save_directory: Path, filename: str) -> None:
    """
    Save a SunPy map as a compressed FITS file.

    Parameters
    ----------
    amap : sunpy.map.GenericMap
        The map to write to disk.
    save_directory : pathlib.Path
        Directory to write the FITS file into.
    filename : str
        Name of the FITS file to create.
    """
    with warnings.catch_warnings():
        # VerifyWarning: Invalid 'BLANK' keyword in header.
        # The 'BLANK' keyword is only applicable to integer data, and will be ignored in this HDU.
        warnings.simplefilter("ignore", category=VerifyWarning)
        # Empty keyword somehow and it raises a warning we want to remove.
        amap.meta.pop("")
        amap.save(save_directory / filename, overwrite=True, hdu_type=CompImageHDU)
