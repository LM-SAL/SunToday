"""
Functions to create sunpy maps from FITS files.
"""

from typing import TYPE_CHECKING

import matplotlib as mpl
import numpy as np
import sunpy.map as smap
from aiapy.calibrate import correct_degradation
from aiapy.calibrate.utils import get_correction_table
from astropy.io import fits
from matplotlib import colors
from sunpy.coordinates import get_earth
from sunpy.map import coordinate_is_on_solar_disk, get_observer_meta
from sunpy.time import parse_time

from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS, HMI_NORM_GAUSS
from suntoday.data import RESPONSE_TABLE_V10

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["create_aia_map", "create_hmi_map", "create_hmi_synoptic_map"]

_HMI_MASK_ROWS = 256


def _north_up(amap: smap.GenericMap) -> smap.GenericMap:
    """
    Rotate a map so solar north is up, without resampling one that already is.
    """
    if not np.array_equal(amap.rotation_matrix, np.eye(2)):
        return amap.rotate()
    # The series used here are delivered derotated (CROTA2 = 0; HMI is natively
    # upside down, but its header says "De-rotation: ON"), and rotate()
    # resamples regardless: about 1 s per 4096 px frame, and it blanks the
    # neighbors of every NaN pixel. Leave the header as rotate() would, the
    # PCi_j matrix in place of CROTA2, so the planning FITS do not change.
    amap.meta.pop("crota2", None)
    amap.meta.update({"pc1_1": 1.0, "pc1_2": 0.0, "pc2_1": 0.0, "pc2_2": 1.0})
    return amap


def create_aia_map(file: Path) -> smap.GenericMap:
    """
    Creates a degradation corrected and exposure normalized AIA Map.

    Since the production data is level 1.5, we do not do any further calibration.

    Parameters
    ----------
    file : `pathlib.Path`
        Path to the AIA FITS file.

    Returns
    -------
    `sunpy.map.GenericMap`
        Degradation corrected and exposure normalized AIA Map.
    """
    with fits.open(file, memmap=False) as hdul:
        aia_map = _north_up(smap.Map(hdul[1].data, hdul[1].header))
        wavelength = f"{aia_map.wavelength.value:.0f}"
        # The visible channels (e.g. 4500) have no entry in the degradation table.
        if wavelength not in AIA_FITS_ONLY_WAVELENGTHS:
            aia_map = correct_degradation(aia_map, correction_table=get_correction_table(str(RESPONSE_TABLE_V10)))
        aia_map /= aia_map.exposure_time
        aia_map.meta["exptime"] = 1.0
        aia_map.meta["BUNIT"] = "ct / s"
        cmap = mpl.colormaps.get_cmap(aia_map.plot_settings["cmap"]).with_extremes(bad="black")
        aia_map.plot_settings["cmap"] = cmap
        aia_map._data[aia_map._data <= 1] = 0  # ruff:ignore[private-member-access]
        aia_map._data[np.isnan(aia_map._data)] = 0  # ruff:ignore[private-member-access]
        aia_map._data = aia_map._data.astype(np.int32)  # ruff:ignore[private-member-access]
        return aia_map


def create_hmi_synoptic_map(file: Path) -> smap.GenericMap:
    """
    Normalize an HMI NRT radial synoptic frame to Carrington CEA coordinates.

    JSOC's daily product uses Carrington *time*, which increases opposite
    to longitude, and sine latitude. Convert both axes to FITS-WCS degrees
    without flipping or interpolating the data. Center the reference pixel
    because the PFSS tracer assumes CRVAL1 is the longitude at map center.

    Parameters
    ----------
    file : pathlib.Path
        FITS file from `suntoday.downloaders.jsoc.fetch_hmi_synoptic_fits`.

    Returns
    -------
    sunpy.map.GenericMap
        Radial boundary with corrected WCS and its original observation time.
    """
    data, header = fits.getdata(file, header=True, memmap=False)
    center = (data.shape[1] + 1) / 2
    header["CRVAL1"] = (-header["CRVAL1"] - (center - header["CRPIX1"]) * header["CDELT1"]) % 360
    header["CRPIX1"] = center
    header["CDELT1"] = -header["CDELT1"]
    # Full-Sun sine-latitude grid: exact CEA spacing rather than JSOC's rounded value.
    header["CDELT2"] = np.rad2deg(2 / data.shape[0])
    header["CTYPE1"], header["CTYPE2"] = "CRLN-CEA", "CRLT-CEA"
    header["CUNIT1"] = header["CUNIT2"] = "deg"
    date = parse_time(header["T_OBS"]).utc
    header["DATE-OBS"] = date.isot
    header.update(get_observer_meta(get_earth(date)))
    return smap.GenericMap(data, header)


def create_hmi_map(file: Path) -> smap.GenericMap:
    """
    Creates a north-up HMI map with everything off the solar disk masked.

    Parameters
    ----------
    file : Path
        Path to the HMI FITS file.

    Returns
    -------
    `sunpy.map.GenericMap`
        HMI Map.
    """
    with fits.open(file, memmap=False) as hdul:
        hmi_map = _north_up(smap.Map(hdul[1].data, hdul[1].header))
        fill_value = np.nan if hmi_map.measurement == "magnetogram" else 0
        for start in range(0, hmi_map.data.shape[0], _HMI_MASK_ROWS):
            stop = min(start + _HMI_MASK_ROWS, hmi_map.data.shape[0])
            pixel_y, pixel_x = np.indices((stop - start, hmi_map.data.shape[1]))
            coordinates = hmi_map.wcs.pixel_to_world(pixel_x, pixel_y + start)
            block = hmi_map.data[start:stop]
            block[~coordinate_is_on_solar_disk(coordinates)] = fill_value
        if hmi_map.measurement == "magnetogram":
            hmi_map.plot_settings["norm"] = colors.Normalize(-HMI_NORM_GAUSS, HMI_NORM_GAUSS)
            hmi_map.plot_settings["cmap"] = mpl.colormaps.get_cmap("gray").with_extremes(bad="black")
        if hmi_map.measurement == "continuum":
            hmi_map._data[np.isnan(hmi_map._data)] = 0  # ruff:ignore[private-member-access]
            with np.errstate(all="ignore"):
                hmi_map._data = hmi_map.data.astype(np.int32)  # ruff:ignore[private-member-access]
        return hmi_map
