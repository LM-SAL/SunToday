"""
Provides all the functions needed to create SDO/AIA JPEGS.
"""

import matplotlib as mpl

mpl.use("module://mplcairo.base")

import datetime
import gc
import tempfile
from collections.abc import Iterable
from pathlib import Path

import astropy.units as u
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import sunpy.map as smap
from astropy.visualization import AsinhStretch, LogStretch, ManualInterval, make_rgb
from matplotlib import colors
from mplcairo import operator_t
from PIL import Image
from sunpy.coordinates import SphericalScreen

from suntoday.config import Settings
from suntoday.constants import AIA_WAVELENGTHS, RGB_COMBINATIONS
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits
from suntoday.logos import PNG_IMAGE
from suntoday.maps import (
    create_aia_map,
    create_hmi_map,
)
from suntoday.utils import atomic_save, save_fits

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
HMI_MEASUREMENT_FITS = {"magnetogram": "blos", "continuum": "continuum"}


def _full_bleed(ax: plt.Axes) -> None:
    """
    Expand the axes to fill the full figure canvas.

    This avoids default subplot padding so the map scales to the
    intended pixel size instead of being surrounded by margins.

    This was not required but all of a sudden I did and I cba to track
    down why.
    """
    fig = ax.figure
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_position([0, 0, 1, 1])


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


def _black_out_cmap_mid(
    cmap: colors.Colormap,
    norm: colors.Normalize,
    mid_low: float,
    mid_high: float,
    n: int = 256,
) -> colors.Colormap:
    """
    Return a copy of the colormap with a middle value range set to black.

    The mid range is specified in data units and converted through the
    norm.

    Parameters
    ----------
    cmap : matplotlib.colors.Colormap
        Colormap to copy and modify.
    norm : matplotlib.colors.Normalize
        Normalization used to convert data values into the [0, 1] range.
    mid_low : float
        Lower bound of the middle range in data units.
    mid_high : float
        Upper bound of the middle range in data units.
    n : int, optional
        Number of samples to use when generating the modified colormap.

    Returns
    -------
    matplotlib.colors.Colormap
        A new colormap with the specified middle range set to black.
    """
    samples = np.linspace(0, 1, n)
    rgba = cmap(samples)
    low = float(norm(mid_low))
    high = float(norm(mid_high))
    if np.isnan(low) or np.isnan(high):
        return cmap
    low, high = sorted((low, high))
    low = float(np.clip(low, 0.0, 1.0))
    high = float(np.clip(high, 0.0, 1.0))
    mask = (samples >= low) & (samples <= high)
    rgba[mask] = (0.0, 0.0, 0.0, 1.0)
    new_cmap = colors.ListedColormap(rgba, name=f"{cmap.name}_midblack")
    return new_cmap.with_extremes(bad="black")


def _adjust_rgb_contrast(rgb: np.ndarray, contrast: float) -> np.ndarray:
    """
    Adjust contrast for an RGB image assumed to be in the [0, 1] range.

    Parameters
    ----------
    rgb : np.ndarray
        RGB image data.
    contrast : float
        Contrast multiplier where 1.0 is no change.

    Returns
    -------
    np.ndarray
        RGB image data with adjusted contrast, clipped to [0, 1].
    """
    if contrast == 1.0:  # NOQA: RUF069
        return rgb
    rgb = np.asarray(rgb, dtype=np.float32)
    # Be defensive if upstream values drift slightly outside [0, 1].
    rgb_min = float(np.nanmin(rgb))
    rgb_max = float(np.nanmax(rgb))
    if rgb_min < 0.0 or rgb_max > 1.0:
        denom = rgb_max - rgb_min
        if denom > 0:
            rgb = (rgb - rgb_min) / denom
    midpoint = 0.5
    adjusted = (rgb - midpoint) * contrast + midpoint
    return np.clip(adjusted, 0.0, 1.0)


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
    _full_bleed(ax)
    clip_interval = (0.01, 99.99) * u.percent if "AIA" in amap.instrument else None
    amap.plot(axes=ax, clip_interval=clip_interval, autoalign=False, interpolation="nearest")
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
    _full_bleed(ax)
    # Use the maximum value of the 99% percentile over all three filters
    # as the maximum value
    pctl = 99
    maximum = 0
    for img in [maps[0].data, maps[1].data, maps[2].data]:
        val = np.percentile(img, pctl)
        maximum = max(maximum, val)
    # Since this is combo specific, I just hardcode it here.
    # This is not a good solution, but it works for now.
    # This looks nice for RGB 1 (94, 335, 193)
    if maps[0].wavelength.value == 94:
        intervals = [
            ManualInterval(vmin=0, vmax=maximum * 0.04),
            ManualInterval(vmin=0, vmax=maximum * 0.15),
            ManualInterval(vmin=0, vmax=maximum * 1.5),
        ]
        stretch = LogStretch(100)
    # This looks nice for RGB 2 (211, 193, 171)
    elif maps[0].wavelength.value == 211:
        intervals = [
            ManualInterval(vmin=0, vmax=maximum * 0.3),
            ManualInterval(vmin=0, vmax=maximum * 0.9),
            ManualInterval(vmin=0, vmax=maximum * 0.8),
        ]
        stretch = AsinhStretch(0.04)
    # This looks nice for RGB 3 (304, 211, 171)
    elif maps[0].wavelength.value == 304:
        intervals = [
            ManualInterval(vmin=0, vmax=maximum),
            ManualInterval(vmin=0, vmax=maximum),
            ManualInterval(vmin=0, vmax=maximum),
        ]
        stretch = AsinhStretch(0.04)
    else:
        msg = f"No RGB stretch/interval defined for lead wavelength {maps[0].wavelength.value}."
        raise ValueError(msg)
    rgb = make_rgb(maps[0].data, maps[1].data, maps[2].data, stretch=stretch, interval=intervals)
    rgb = _adjust_rgb_contrast(rgb, settings.rgb_contrast)
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
    """
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = fig.add_subplot(111, projection=maps[0].wcs)
    _full_bleed(ax)
    modified_hmi_cmap = plt.get_cmap(maps[0].plot_settings["cmap"]).copy()
    norm = maps[0].plot_settings.get("norm")
    modified_hmi_cmap = _black_out_cmap_mid(modified_hmi_cmap, norm, -50, 50)
    maps[0].plot(
        axes=ax,
        cmap=modified_hmi_cmap,
        autoalign=False,
        interpolation="nearest",
    )
    wavelength_names = []
    for i, amap in enumerate(maps):
        wavelength = (
            # "align" 171 label
            "     " + WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value) + "     "
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
            reprojected_map = amap.reproject_to(
                maps[0].wcs, parallel=True, return_footprint=False, block_size=(256, 256)
            )
    im_aia = reprojected_map.plot(axes=ax, interpolation="nearest", autoalign=False)
    del reprojected_map
    operator_t.SCREEN.patch_artist(im_aia)
    ax.set_axis_off()
    ax.set_title("")
    _add_lmsal_logo(ax)
    return "_".join(wavelength_names), fig


def save_figures(list_of_figs: Iterable[tuple[str, plt.Figure]], save_directory: Path) -> list[Path]:
    """
    Save figures as JPEG images.

    Parameters
    ----------
    list_of_figs : (Iterable[Tuple[str, plt.Figure]])
        An iterable of tuples containing the wavelength and the corresponding figure.
        Figures are closed after saving to free memory.
    save_directory : pathlib.Path
        The directory where the JPEG images will be saved.

    Returns
    -------
    list of pathlib.Path
        Saved JPEG paths.
    """
    settings = Settings()
    saved_paths = []
    for wavelength, fig in list_of_figs:
        full_path = save_directory / settings.sdo_fig_name_large.format(wavelength)
        small_path = save_directory / settings.sdo_fig_name_small.format(wavelength)
        try:
            with atomic_save(full_path) as full_tmp:
                fig.savefig(full_tmp, dpi=settings.fig_dpi)
                # Resize to 1024 - We avoid using MPL to resize the image to font issues
                with atomic_save(small_path) as small_tmp, Image.open(str(full_tmp)) as full_jpeg:
                    resized_image = full_jpeg.resize((settings.resize_fig_size, settings.resize_fig_size))
                    try:
                        resized_image.save(str(small_tmp))
                    finally:
                        resized_image.close()
            saved_paths.extend((full_path, small_path))
        finally:
            plt.close(fig)
            gc.collect()
    return saved_paths


def create_sdo_images(requested_time: datetime.datetime, save_directory: Path) -> list[Path]:
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

    Returns
    -------
    list of pathlib.Path
        Created files.
    """
    # The reason the files are for looped is an attempt to keep memory use <4GB for the
    # cheap VM on AWS.
    saved_paths = []
    with tempfile.TemporaryDirectory() as temp_dir:
        aia_files = fetch_aia_fits(requested_time, save_directory=Path(temp_dir))
        aia_files = sorted(aia_files, key=lambda x: AIA_WAVELENGTHS.index(Path(x).stem.split("_")[-1]))
        hmi_files = fetch_hmi_fits(requested_time, save_directory=Path(temp_dir))
        aia_files_by_wavelength = {}
        hmi_files_by_measurement = {}

        for aia_file in aia_files:
            aia_path = Path(aia_file)
            wavelength_key = aia_path.stem.split("_")[-1]
            aia_files_by_wavelength[wavelength_key] = aia_path
            aia_map = create_aia_map(aia_path)
            saved_paths.append(
                save_fits(aia_map, save_directory, f"f{WAVELENGTH_FORMAT.format(aia_map.wavelength.value)}.fits")
            )
            saved_paths.extend(save_figures([create_figure_from_map(aia_map)], save_directory))
            del aia_map
            gc.collect()

        for hmi_file in hmi_files:
            hmi_path = Path(hmi_file)
            hmi_map = create_hmi_map(hmi_path)
            hmi_files_by_measurement[hmi_map.measurement] = hmi_path
            hmi_fits_name = HMI_MEASUREMENT_FITS.get(hmi_map.measurement)
            saved_paths.append(save_fits(hmi_map, save_directory, f"f{hmi_fits_name}.fits"))
            saved_paths.extend(save_figures([create_figure_from_map(hmi_map)], save_directory))
            del hmi_map
            gc.collect()

        for rgb_comb in RGB_COMBINATIONS:
            maps = [create_aia_map(aia_files_by_wavelength[wavelength]) for wavelength in rgb_comb]
            saved_paths.extend(save_figures([create_rgb_figure_from_maps(maps)], save_directory))
            del maps
            gc.collect()

        # Blend combination is only HMI B_LOS and AIA 171 currently
        hmi_blos = hmi_files_by_measurement["magnetogram"]
        maps = [create_hmi_map(hmi_blos), create_aia_map(aia_files_by_wavelength["171"])]
        saved_paths.extend(save_figures([create_blended_figure_from_maps(maps)], save_directory))
        del maps
        gc.collect()
    return saved_paths
