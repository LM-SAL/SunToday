"""
Functions to create sunpy maps from FITS files.
"""

import matplotlib as mpl

mpl.use("module://mplcairo.base")

import warnings
from pathlib import Path

import numpy as np
import sunpy.map as smap
from aiapy.calibrate import correct_degradation
from aiapy.calibrate.utils import get_correction_table
from astropy.io import fits
from matplotlib import colors
from sunkit_magex.pfss.utils import car_to_cea
from sunpy.map import all_coordinates_from_map, coordinate_is_on_solar_disk
from sunpy.util.exceptions import SunpyMetadataWarning

from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS, HMI_NORM_GAUSS
from suntoday.data import RESPONSE_TABLE_V10

__all__ = ["create_adapt_map", "create_aia_map", "create_hmi_map"]


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
        aia_map = smap.Map(hdul[1].data, hdul[1].header).rotate()
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


def create_adapt_map(file: Path, realization: int = 0) -> smap.GenericMap:
    """
    Creates a full-Sun Carrington map from one realization of an ADAPT
    synchronic magnetogram FITS file.

    ADAPT's header is standard enough that sunpy recognizes it directly,
    but the map ships in a plate-carree (CAR) projection; the PFSS solver
    needs the equal-area (CEA) one, so it is reprojected here.

    Parameters
    ----------
    file : `pathlib.Path`
        Path to the ADAPT FITS file written by
        `suntoday.downloaders.adapt.fetch_adapt_fits`.
    realization : int, optional
        Which of the 12 model realizations to use (default the first).

    Returns
    -------
    `sunpy.map.GenericMap`
        Full-Sun magnetogram in the heliographic Carrington frame.
    """
    with warnings.catch_warnings():
        # ADAPT is a modeled composite with no observer keywords; the Earth
        # fallback is correct. The warning fires lazily inside car_to_cea.
        warnings.filterwarnings("ignore", category=SunpyMetadataWarning, message="Missing metadata for observer")
        with fits.open(file, memmap=False) as hdul:
            adapt_map = smap.Map(hdul[0].data[realization], hdul[0].header)
        return car_to_cea(adapt_map)


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
    with fits.open(file, memmap=False) as hdul:
        hmi_map = smap.Map(hdul[1].data, hdul[1].header).rotate()
        fill_value = np.nan if hmi_map.measurement == "magnetogram" else 0
        hmi_map.data[~coordinate_is_on_solar_disk(all_coordinates_from_map(hmi_map))] = fill_value
        if hmi_map.measurement == "magnetogram":
            hmi_map.plot_settings["norm"] = colors.Normalize(-HMI_NORM_GAUSS, HMI_NORM_GAUSS)
            hmi_map.plot_settings["cmap"] = mpl.colormaps.get_cmap("gray").with_extremes(bad="black")
        if hmi_map.measurement == "continuum":
            hmi_map._data[np.isnan(hmi_map._data)] = 0  # ruff:ignore[private-member-access]
            with np.errstate(all="ignore"):
                hmi_map._data = hmi_map.data.astype(np.int32)  # ruff:ignore[private-member-access]
        return hmi_map
