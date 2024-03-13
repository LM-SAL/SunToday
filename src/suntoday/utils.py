"""
Utility functions for image processing and visualization.
"""

import numpy as np

__all__ = ["apply_gamma_correction", "clip_image_percentiles", "normalize_image_percentiles"]


def clip_image_percentiles(
    image: np.array, lower_percentile: float = 0.01, upper_percentile: float = 99.99
) -> np.array:
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


def apply_gamma_correction(image: np.array, gamma: float = 0.5):
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
    image: np.array, lower_percentile: float = 0.001, upper_percentile: float = 99.8
) -> np.array:
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
