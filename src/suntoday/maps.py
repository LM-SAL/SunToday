"""
Functions to create sunpy maps from FITS files.
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import sunpy.map as smap
from aiapy.calibrate import correct_degradation
from aiapy.calibrate.util import get_correction_table
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
    aia_map = smap.Map(file)
    aia_map = correct_degradation(aia_map, correction_table=get_correction_table(str(RESPONSE_TABLE_V10)))
    aia_map /= aia_map.exposure_time
    aia_map.meta["exptime"] = 1.0
    aia_map.meta["BUNIT"] = "ct / s"
    cmap = mpl.colormaps.get_cmap(aia_map.plot_settings["cmap"])
    cmap.set_bad(color="black")
    aia_map.plot_settings["cmap"] = cmap
    aia_map.data[aia_map.data <= 1] = 0
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
    map_hmi = smap.Map(file).rotate()
    fill_value = np.nan if map_hmi.measurement == "magnetogram" else 0
    map_hmi.data[~coordinate_is_on_solar_disk(all_coordinates_from_map(map_hmi))] = fill_value
    if map_hmi.measurement == "magnetogram":
        map_hmi.plot_settings["norm"] = plt.Normalize(-1000, 1000)
        map_hmi.plot_settings["cmap"] = "hmimag"
        cmap = mpl.colormaps.get_cmap(map_hmi.plot_settings["cmap"])
        cmap.set_bad(color="black")
        map_hmi.plot_settings["cmap"] = cmap
    return map_hmi
