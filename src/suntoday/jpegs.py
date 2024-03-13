"""
Provides all the functions needed to create SDO/AIA JPEGS.
"""

import datetime
import tempfile
import warnings
from pathlib import Path

import astropy.units as u
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import sunpy.map as smap
from astropy.io.fits.verify import VerifyWarning
from astropy.visualization import AsinhStretch, LogStretch, ManualInterval, make_rgb
from matplotlib import colors
from PIL import Image
from sunpy.coordinates import SphericalScreen

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import AIA_WAVELENGTHS, RGB_COMBINATIONS
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits
from suntoday.logos import PNG_IMAGE
from suntoday.maps import (
    create_aia_map,
    create_hmi_map,
)

__all__ = [
    "create_blended_figure_from_maps",
    "create_figure_from_map",
    "create_rgb_figure_from_maps",
    "create_sdo_images",
    "save_figures",
]

# Aren't magic numbers great?!
TEXT_X_POS = 0.02
TEXT_Y_POS = 0.07
TEXT_Y_POS_MOD = 0.02
LABEL_FORMAT = "{observatory}/{instrument} - {wavelength} - {date}"
WAVELENGTH_FORMAT = "{:04.0f}"
WAVELENGTH_FORMAT_BLEND = "{:03.0f}"
HMI_MEASUREMENT_JPEG = {"magnetogram": "HMI BLOS", "continuum": " HMI Continuum (AIA scale)"}
HMI_MEASUREMENT_JPEG_FILENAMES = {"magnetogram": "_HMImag", "continuum": "_HMI_cont_aiascale"}
HMI_MEASUREMENT_FITS = {"magnetogram": "blos"}


def _add_lmsal_logo(ax: plt.Axes) -> None:
    """
    Add LMSAL logo to the given Axes object.

    Parameters
    ----------
    ax : `matplotlib.pyplot.Axes`
        The Axes object to add the logo to.
    """
    # Aren't magic numbers great?!
    ax_logo = ax.inset_axes([0.72, 0, 0.28, 0.08])
    ax_logo.imshow(plt.imread(PNG_IMAGE))
    ax_logo.set_axis_off()


def create_figure_from_map(amap: smap.GenericMap) -> tuple[str, plt.Figure]:
    """
    Creates the final figure from the input Map.

    Adds the AIA LMSAL logo, the timestamp and wavelength.

    Parameters
    ----------
    amap : sunpy.map.GenericMap
        Input Map to plot.

    Returns
    -------
    str
        The wavelength of the map(s). This is used as part of the filename.
    `plt.Figure`
        The figure object.
    """
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = plt.subplot(projection=amap)
    clip_interval = (0.01, 99.99) * u.percent if "AIA" in amap.instrument else None
    amap.plot(axes=ax, clip_interval=clip_interval)
    wavelength = (
        WAVELENGTH_FORMAT.format(amap.wavelength.value)
        if "AIA" in amap.instrument
        else HMI_MEASUREMENT_JPEG[amap.measurement]
    )
    wavelength_filename = (
        WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value).zfill(4)
        if "AIA" in amap.instrument
        else HMI_MEASUREMENT_JPEG_FILENAMES[amap.measurement]
    )
    plt.text(
        TEXT_X_POS,
        TEXT_Y_POS_MOD,
        LABEL_FORMAT.format(
            observatory=amap.observatory,
            instrument=amap.instrument.split()[0],
            wavelength=wavelength,
            date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
        ),
        color="white",
        transform=ax.transAxes,
        fontdict={"fontsize": 10},
        path_effects=[pe.withStroke(linewidth=4, foreground="black")],
    )
    ax.set_axis_off()
    ax.set_title("")
    _add_lmsal_logo(ax)
    return wavelength_filename, fig


def create_rgb_figure_from_maps(maps: list[smap.GenericMap]) -> tuple[str, plt.Figure]:
    """
    Creates a RGB figure from a list of 3 maps.

    Parameters
    ----------
    maps : `list[sunpy.map.GenericMap]`
        List of maps to create the RGB figure from.

    Returns
    -------
    str
        The wavelength of the map(s).
    `plt.Figure`
        The figure object.

    Raises
    ------
    ValueError
        If not 3 maps are passed.
    """
    if len(maps) != 3:
        msg = "RGB figure needs exactly three maps."
        raise ValueError(msg)
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = fig.add_subplot(111)

    # Use the maximum value of the 99.8% percentile over all three filters
    # as the maximum value:
    pctl = 99.8
    maximum = 0.0
    for img in [maps[0].data, maps[1].data, maps[2].data]:
        val = np.percentile(img, pctl)
        maximum = max(maximum, val)
    # Even though the RGB maps I created are correct, the existing JPEGS were not
    # blended correctly and as such have less red than green or blue.
    # Since this is combo specific, I just hardcode it here.
    # This is not a good solution, but it works for now.

    # This looks nice for RGB 1 (94, 335, 193)
    if maps[0].wavelength.value == 94:
        intervals = [
            ManualInterval(vmin=0, vmax=maximum * 0.0055),
            ManualInterval(vmin=0, vmax=maximum * 0.03),
            ManualInterval(vmin=0, vmax=maximum * 0.4),
        ]
        stretch = AsinhStretch(0.099)
    # This looks nice for RGB 2 (211, 193, 171)
    if maps[0].wavelength.value == 211:
        intervals = [
            ManualInterval(vmin=0, vmax=maximum * 0.5),
            ManualInterval(vmin=0, vmax=maximum),
            ManualInterval(vmin=0, vmax=maximum),
        ]
        stretch = LogStretch(75)
    # This looks nice for RGB 3 (304, 211, 171)
    if maps[0].wavelength.value == 304:
        intervals = [
            ManualInterval(vmin=0, vmax=maximum * 0.5),
            ManualInterval(vmin=0, vmax=maximum),
            ManualInterval(vmin=0, vmax=maximum),
        ]
        stretch = LogStretch(75)
    rgb = make_rgb(maps[0].data, maps[1].data, maps[2].data, stretch=stretch, interval=intervals)
    ax.imshow(rgb, origin="lower")
    wavelength_names = []
    for i, amap in enumerate(maps):
        color = "red" if i == 0 else "green" if i == 1 else "blue"
        wavelength = WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value)
        wavelength_names.append(wavelength)
        plt.text(
            TEXT_X_POS,
            TEXT_Y_POS - i * TEXT_Y_POS_MOD,
            LABEL_FORMAT.format(
                observatory=amap.observatory,
                instrument=amap.instrument.split()[0],
                wavelength=wavelength,
                date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
            ),
            color="white",
            transform=ax.transAxes,
            fontdict={"fontsize": 12},
            path_effects=[pe.withStroke(linewidth=4, foreground=color)],
        )
    ax.set_axis_off()
    ax.set_title("")
    _add_lmsal_logo(ax)
    return "_" + "_".join(wavelength_names), fig


def create_blended_figure_from_maps(maps: list[smap.GenericMap]) -> tuple[str, plt.Figure]:
    """
    Create a blended figure from a list of maps.

    .. warning::

        HMI maps should be the first map in the list, followed by AIA maps.

    Parameters
    ----------
    maps : `list[smap.GenericMap]`
        A list of maps to be blended.

    Returns
    -------
    str
        The wavelength of the map(s). This is used as part of the filename.
    `plt.Figure`
        The figure object.

    Notes
    -----
    This function creates a blended figure by overlaying multiple maps onto a single figure.
    The first map in the list is used as the base map, and the remaining maps are blended on top of it.
    The blending is done using a specified colormap and transparency.
    """
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = fig.add_subplot(111, projection=maps[0].wcs)
    clip_interval = (1, 99.9) * u.percent if maps[0].instrument == "AIA" else None
    maps[0].plot(axes=ax, clip_interval=clip_interval)
    wavelength_names = []
    for i, amap in enumerate(maps):
        wavelength = (
            WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value)
            if "AIA" in amap.instrument
            else HMI_MEASUREMENT_JPEG[amap.measurement]
        )
        wavelength_filename = (
            WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value)
            if "AIA" in amap.instrument
            else HMI_MEASUREMENT_JPEG_FILENAMES[amap.measurement]
        )
        wavelength_names.append(wavelength_filename)
        plt.text(
            TEXT_X_POS,
            (TEXT_Y_POS - TEXT_Y_POS_MOD) - i * TEXT_Y_POS_MOD,
            LABEL_FORMAT.format(
                observatory=amap.observatory,
                instrument=amap.instrument.split()[0],
                wavelength=wavelength,
                date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
            ),
            color="white",
            transform=ax.transAxes,
            fontdict={"fontsize": 12},
            path_effects=[pe.withStroke(linewidth=4, foreground="black")],
        )
        if i == 0:
            continue
        with SphericalScreen(maps[0].observer_coordinate):
            reprojected_map = amap.reproject_to(maps[0].wcs)
        reprojected_map.plot(axes=ax, alpha=0.7, norm=colors.PowerNorm(gamma=0.4, vmin=0, vmax=2000))
    ax.set_axis_off()
    ax.set_title("")
    _add_lmsal_logo(ax)
    return "_".join(wavelength_names), fig


def save_figures(list_of_figs: list[tuple[str, plt.figure]], save_directory: Path) -> None:
    """
    Save a list of figures as JPEG images.

    Parameters
    ----------
    list_of_figs : (List[Tuple[str, plt.figure]])
        A list of tuples containing the wavelength and the corresponding figure.
    save_directory : pathlib.Path
        The directory where the JPEG images will be saved.
    """
    settings = Settings()
    for wavelength, fig in list_of_figs:
        fig.savefig(save_directory / settings.sdo_fig_name_large.format(wavelength), dpi=settings.fig_dpi)
        logger.debug(
            f"Wavelength: {wavelength} figure saved to {save_directory / settings.sdo_fig_name_large.format(wavelength)}"
        )
        # Resize to 1024 - We avoid using MPL to resize the image to font issues
        full_jpeg = Image.open(str(save_directory / settings.sdo_fig_name_large.format(wavelength)))
        resized_image = full_jpeg.resize((settings.resize_fig_size, settings.resize_fig_size))
        resized_image.save(str(save_directory / settings.sdo_fig_name_small.format(wavelength)))
        logger.debug(
            f"Resized wavelength: {wavelength} figure saved to {save_directory / settings.sdo_fig_name_small.format(wavelength)}"
        )


def create_sdo_images(requested_time: datetime, save_directory: Path) -> None:
    """
    Creates the full set of SDO images for the given datetime and saves it to
    the given directory.

    Also saves the FITS files used for planning by someone.

    Parameters
    ----------
    requested_time : datetime.datetime
        Datetime to create the plot.
    save_directory : pathlib.Path
        Save directory for the plot.

    Raises
    ------
    OSError
        If the incorrect number of AIA or HMI files are downloaded.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        aia_files = fetch_aia_fits(requested_time, save_directory=temp_dir)
        if len(aia_files) != len(AIA_WAVELENGTHS):
            msg = f"Mismatch of AIA files downloaded, expected {len(AIA_WAVELENGTHS)}, got {len(aia_files)}, missing: {set(AIA_WAVELENGTHS) - {f.split('_')[-1].split('.')[0] for f in aia_files}}"
            raise OSError(msg)
        aia_files = sorted(aia_files, key=lambda x: AIA_WAVELENGTHS.index(x.split("_")[-1].split(".")[0]))
        # HMI files are not always available at the same time as AIA files
        hmi_files = fetch_hmi_fits(requested_time - datetime.timedelta(hours=2), save_directory=temp_dir)
        if len(hmi_files) != 2:
            msg = "Mismatch of HMI files downloaded"
            raise OSError(msg)
        aia_maps = [create_aia_map(aia_file) for aia_file in aia_files]
        hmi_maps = [create_hmi_map(hmi_file) for hmi_file in hmi_files]
        filenames = [
            WAVELENGTH_FORMAT.format(amap.wavelength.value)
            if "AIA" in amap.instrument
            else HMI_MEASUREMENT_FITS.get(amap.measurement)
            for amap in (aia_maps + hmi_maps)
        ]
        with warnings.catch_warnings():
            # Need to bypass
            # VerifyWarning: Invalid 'BLANK' keyword in header.
            # The 'BLANK' keyword is only applicable to integer data, and will be ignored in this HDU.
            warnings.simplefilter("ignore", category=VerifyWarning)
            [
                amap.save(save_directory / ("f" + filenames[i] + ".fits"), overwrite=True)
                for i, amap in enumerate(aia_maps + hmi_maps)
                if filenames[i] is not None
            ]
        figures = [create_figure_from_map(aia_map) for aia_map in aia_maps]
        figures.extend(create_figure_from_map(hmi_map) for hmi_map in hmi_maps)
        for rgb_comb in RGB_COMBINATIONS:
            maps = [aia_maps[AIA_WAVELENGTHS.index(wavelength)] for wavelength in rgb_comb]
            figures.append(create_rgb_figure_from_maps(maps))
        # Blend combinations is only HMI B_LOS and AIA 171
        maps = [hmi_maps[0], aia_maps[AIA_WAVELENGTHS.index("171")]]
        figures.append(create_blended_figure_from_maps(maps))
        save_figures(figures, save_directory)
        plt.close("all")
