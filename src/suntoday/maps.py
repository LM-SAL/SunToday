"""
Functions to create sunpy maps from FITS files.
"""

import matplotlib as mpl

mpl.use("module://mplcairo.base")

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import sunpy.map as smap
from aiapy.calibrate import correct_degradation
from aiapy.calibrate.utils import get_correction_table
from astropy.io import fits
from sunpy.map import all_coordinates_from_map, coordinate_is_on_solar_disk

from suntoday.data import RESPONSE_TABLE_V10

__all__ = ["create_aia_map", "create_hmi_map"]


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
    with fits.open(file, memmap=True) as hdul:
        aia_map = smap.Map(hdul[1].data, hdul[1].header).rotate()
        aia_map = correct_degradation(aia_map, correction_table=get_correction_table(str(RESPONSE_TABLE_V10)))
        aia_map /= aia_map.exposure_time
        aia_map.meta["exptime"] = 1.0
        aia_map.meta["BUNIT"] = "ct / s"
        cmap = mpl.colormaps.get_cmap(aia_map.plot_settings["cmap"])
        cmap.set_bad(color="black")
        aia_map.plot_settings["cmap"] = cmap
        aia_map._data[aia_map._data <= 1] = 0  # NOQA: SLF001
        aia_map._data[np.isnan(aia_map._data)] = 0  # NOQA: SLF001
        aia_map._data = aia_map._data.astype(int)  # NOQA: SLF001
        return aia_map


def create_hmi_map(file: Path) -> smap.GenericMap:
    """
    Creates a rotated HMI map.

    Parameters
    ----------
    file : Path
        Path to the HMI FITS file.

    Returns
    -------
    `sunpy.map.GenericMap`
        HMI Map.
    """
    with fits.open(file, memmap=True) as hdul:
        hmi_map = smap.Map(hdul[1].data, hdul[1].header).rotate()
        fill_value = np.nan if hmi_map.measurement == "magnetogram" else 0
        hmi_map.data[~coordinate_is_on_solar_disk(all_coordinates_from_map(hmi_map))] = fill_value
        if hmi_map.measurement == "magnetogram":
            hmi_map.plot_settings["norm"] = plt.Normalize(-1000, 1000)
            hmi_map.plot_settings["cmap"] = "hmimag"
            cmap = mpl.colormaps.get_cmap(hmi_map.plot_settings["cmap"])
            cmap.set_bad(color="black")
            hmi_map.plot_settings["cmap"] = cmap
        if hmi_map.measurement == "continuum":
            hmi_map._data[np.isnan(hmi_map._data)] = 0  # NOQA: SLF001
            with np.errstate(all="ignore"):
                hmi_map._data = hmi_map.data.astype(int)  # NOQA: SLF001
        return hmi_map
