"""
Provides all the functions needed to create SDO/AIA JPEGS.
"""

import matplotlib as mpl

mpl.use("module://mplcairo.base")

import datetime
import gc
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

import astropy.units as u
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import sunpy.map as smap
from astropy.coordinates import SkyCoord
from matplotlib import colors
from mplcairo import operator_t
from PIL import Image
from sunpy.coordinates import Heliocentric, SphericalScreen, propagate_with_solar_surface, transform_with_sun_center

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS, AIA_WAVELENGTHS, RGB_COMBINATIONS
from suntoday.downloaders.adapt import fetch_adapt_fits
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits
from suntoday.logos import PNG_IMAGE
from suntoday.maps import (
    aia_norm,
    create_adapt_map,
    create_aia_map,
    create_hmi_map,
)
from suntoday.pfss import trace_field_lines
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
TEXT_Y_POS_MOD = 0.02
# Vertical center of the LMSAL logo inset ([0.72, 0, 0.28, 0.08]) so the
# single-map label sits inline with the logo.
TEXT_Y_POS_LOGO = 0.04
# Above ~16 the stacked RGB/blend labels start overlapping (TEXT_Y_POS_MOD
# spacing is 0.02 of a 4096 px axis, ~82 px per line).
LABEL_FONTSIZE = 14
LABEL_FORMAT = "{observatory}/{instrument} - {wavelength} - {date}"
WAVELENGTH_FORMAT = "{:04.0f}"
WAVELENGTH_FORMAT_BLEND = "{:03.0f}"
# Space-padded variant for the on-image labels (monospace keeps the columns
# aligned); the zero-padded formats above feed the filenames and must not change.
WAVELENGTH_FORMAT_LABEL = "{:>4.0f}"
HMI_MEASUREMENT_JPEG = {"magnetogram": "HMI BLOS", "continuum": " HMI Continuum (AIA scale)"}
HMI_MEASUREMENT_JPEG_FILENAMES = {"magnetogram": "_HMImag", "continuum": "_HMI_cont_aiascale"}
HMI_MEASUREMENT_FITS = {"magnetogram": "blos", "continuum": "continuum"}
# Screen blending adds light, so any non-black pixel brightens the AIA layer
# beneath it: a colormap with a light/gray midpoint (e.g. "hmimag") washes
# out most of the disk instead of showing polarity. This map instead holds
# black out to +-15 G (only true photon/readout noise stays invisible) and
# saturates to blue/red by +-120 G, so network- and plage-strength field pops
# clearly. Polarity: red = positive (toward observer), blue = negative (away
# from observer); also called out in BLEND_POLARITY_LABEL on the figure
# itself. The blend uses its own norm rather than the magnetogram display one
# from HMI_NORM_GAUSS, so the two can be tuned independently.
BLEND_HMI_NOISE_GAUSS = 15
BLEND_HMI_SATURATION_GAUSS = 120
# The limits are fixed (never autoscaled) and nothing
# mutates a norm (no set_clim, no colorbar).
BLEND_HMI_NORM = colors.Normalize(-BLEND_HMI_SATURATION_GAUSS, BLEND_HMI_SATURATION_GAUSS)
BLEND_HMI_CMAP = colors.LinearSegmentedColormap.from_list(
    "hmi_polarity_blend",
    [
        (0.0, "blue"),
        (0.5 - BLEND_HMI_NOISE_GAUSS / (2 * BLEND_HMI_SATURATION_GAUSS), "black"),
        (0.5 + BLEND_HMI_NOISE_GAUSS / (2 * BLEND_HMI_SATURATION_GAUSS), "black"),
        (1.0, "red"),
    ],
)
BLEND_POLARITY_LABEL = "HMI polarity: red = +, blue = -"
# Pillow's default JPEG quality (75) leaves visible banding in the dark
# corona; 90 removes it for ~35% more bytes than 85. optimize/progressive
# are NOT used: combined with subsampling=0 they make Pillow do a two-pass
# encode, and for some real images (e.g. a PFSS field-line overlay on the
# 335 channel) libjpeg's suspend-buffer handling breaks with "OSError:
# broken data stream" (libjpeg's JERR_CANT_SUSPEND). Baseline single-pass
# encoding at subsampling=0 doesn't hit this.
JPEG_SAVE_OPTIONS = {"quality": 90, "subsampling": 0}
# Thin white lines matching the historical LMSAL PFSS rendering; ~1.2 px wide
# on the 4096 px canvas.
FIELD_LINE_KWARGS = {"color": "white", "linewidth": 0.4, "alpha": 0.9}
# The logo PNG is quite dim against the black corner; brighten it.
LOGO_BRIGHTNESS = 1.25


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
    logo = plt.imread(PNG_IMAGE).copy()
    logo[..., :3] = np.clip(logo[..., :3] * LOGO_BRIGHTNESS, 0, 1)
    ax_logo.imshow(logo)
    ax_logo.set_axis_off()


def _draw_field_lines(ax: plt.Axes, amap: smap.GenericMap, field_lines: SkyCoord) -> None:
    """
    Draw PFSS field lines over a plotted map.

    The lines are converted to pixel coordinates of ``amap`` so this works
    on both WCS axes and the plain axes used by the RGB composites. Points
    on the far side of the Sun that the disk occults are blanked out.

    Parameters
    ----------
    ax : `matplotlib.pyplot.Axes`
        Axes the map is plotted on.
    amap : `sunpy.map.GenericMap`
        The map defining the pixel grid and the observer.
    field_lines : `astropy.coordinates.SkyCoord`
        NaN-separated field line polyline from
        `suntoday.pfss.trace_field_lines`.
    """
    rsun = amap.rsun_meters.to_value(u.m)
    with propagate_with_solar_surface(), transform_with_sun_center():
        heliocentric = field_lines.transform_to(Heliocentric(observer=amap.observer_coordinate, obstime=amap.date))
        pixel_x, pixel_y = amap.wcs.world_to_pixel(field_lines)
    occulted = (heliocentric.z.to_value(u.m) < 0) & (
        np.hypot(heliocentric.x.to_value(u.m), heliocentric.y.to_value(u.m)) < rsun
    )
    pixel_x = np.asarray(pixel_x, dtype=float)
    pixel_y = np.asarray(pixel_y, dtype=float)
    pixel_x[occulted] = np.nan
    ax.plot(pixel_x, pixel_y, **FIELD_LINE_KWARGS)
    # Pad the prefix so the datetime column lines up with the instrument
    # label(s) already on the axes (all the labels are monospace).
    date_starts = [
        match.start()
        for text in ax.texts
        if (match := re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text.get_text()))
    ]
    prefix_width = max(date_starts, default=13) - 3
    ax.text(
        TEXT_X_POS,
        TEXT_Y_POS_LOGO + len(ax.texts) * TEXT_Y_POS_MOD,
        f"{'PFSS ADAPT':<{prefix_width}} - {field_lines.obstime.strftime('%Y-%m-%d %H:%M:%S')}",
        color="white",
        transform=ax.transAxes,
        va="center",
        fontdict={"fontsize": LABEL_FONTSIZE, "family": "monospace"},
        path_effects=[pe.withStroke(linewidth=4, foreground="black")],
    )
    # The off-limb line points would otherwise autoscale the axes outwards.
    n_y, n_x = amap.data.shape
    ax.set_xlim(-0.5, n_x - 0.5)
    ax.set_ylim(-0.5, n_y - 0.5)


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

    Raises
    ------
    ValueError
        If an AIA map carries no fixed display norm (no
        `suntoday.constants.AIA_SCALING` entry): plotting would silently
        autoscale to the frame, breaking the fixed-scaling contract.
    """
    if "AIA" in amap.instrument:
        norm = amap.plot_settings.get("norm")
        if norm is None or norm.vmin is None or norm.vmax is None:
            msg = f"AIA map for wavelength {amap.wavelength.value:.0f} has no fixed display norm (see AIA_SCALING)."
            raise ValueError(msg)
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = plt.subplot(projection=amap)
    _full_bleed(ax)
    amap.plot(axes=ax, autoalign=False, interpolation="nearest")
    wavelength = (
        WAVELENGTH_FORMAT_LABEL.format(amap.wavelength.value)
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
        TEXT_Y_POS_LOGO,
        LABEL_FORMAT.format(
            observatory=amap.observatory,
            instrument=amap.instrument.split()[0],
            wavelength=wavelength,
            date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
        ),
        color="white",
        transform=ax.transAxes,
        va="center",
        fontdict={"fontsize": LABEL_FONTSIZE, "family": "monospace"},
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
        If a map's wavelength has no `suntoday.constants.AIA_SCALING` entry.
    """
    if len(maps) != 3:
        msg = "RGB figure needs exactly three maps."
        raise ValueError(msg)
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = fig.add_subplot(111)
    _full_bleed(ax)
    # Each channel is normalized with the same fixed norm as its single wavelength JPEG.
    channels = []
    for amap in maps:
        wavelength = f"{amap.wavelength.value:.0f}"
        if (norm := aia_norm(wavelength)) is None:
            msg = f"No AIA scaling defined for wavelength {wavelength}."
            raise ValueError(msg)
        channels.append(np.ma.filled(norm(amap.data), 0).astype(np.float32))
    rgb = np.stack(channels, axis=-1)
    ax.imshow(rgb, origin="lower")
    wavelength_names = []
    for i, amap in enumerate(maps):
        color = "red" if i == 0 else "green" if i == 1 else "blue"
        wavelength = WAVELENGTH_FORMAT_LABEL.format(amap.wavelength.value)
        wavelength_names.append(WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value))
        plt.text(
            TEXT_X_POS,
            TEXT_Y_POS_LOGO + (len(maps) - 1 - i) * TEXT_Y_POS_MOD,
            LABEL_FORMAT.format(
                observatory=amap.observatory,
                instrument=amap.instrument.split()[0],
                wavelength=wavelength,
                date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
            ),
            color="white",
            transform=ax.transAxes,
            va="center",
            fontdict={"fontsize": LABEL_FONTSIZE, "family": "monospace"},
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
    maps[0].plot(
        axes=ax,
        cmap=BLEND_HMI_CMAP,
        norm=BLEND_HMI_NORM,
        autoalign=False,
        interpolation="nearest",
    )
    plt.text(
        TEXT_X_POS,
        TEXT_Y_POS_LOGO + len(maps) * TEXT_Y_POS_MOD,
        BLEND_POLARITY_LABEL,
        color="white",
        transform=ax.transAxes,
        va="center",
        fontdict={"fontsize": LABEL_FONTSIZE, "family": "monospace"},
        path_effects=[pe.withStroke(linewidth=4, foreground="black")],
    )
    wavelength_names = []
    for i, amap in enumerate(maps):
        wavelength = (
            # Pad to the HMI label width so the monospace columns line up.
            WAVELENGTH_FORMAT_LABEL
            .format(amap.wavelength.value)
            .strip()
            .center(len(HMI_MEASUREMENT_JPEG[maps[0].measurement]))
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
            TEXT_Y_POS_LOGO + (len(maps) - 1 - i) * TEXT_Y_POS_MOD,
            LABEL_FORMAT.format(
                observatory=amap.observatory,
                instrument=amap.instrument.split()[0],
                wavelength=wavelength,
                date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
            ),
            color="white",
            transform=ax.transAxes,
            va="center",
            fontdict={"fontsize": LABEL_FONTSIZE, "family": "monospace"},
            path_effects=[pe.withStroke(linewidth=4, foreground="black")],
        )
        if i == 0:
            continue
        with SphericalScreen(maps[0].observer_coordinate):
            # Serial on purpose: parallel=True spawns worker processes whose
            # memory the 4 GB VM cannot spare, and with roundtrip_coords off
            # (bit-identical output here) serial is faster than parallel was.
            reprojected_map = amap.reproject_to(
                maps[0].wcs, parallel=False, return_footprint=False, block_size=(256, 256), roundtrip_coords=False
            )
    im_aia = reprojected_map.plot(axes=ax, interpolation="nearest", autoalign=False)
    del reprojected_map
    operator_t.SCREEN.patch_artist(im_aia)
    ax.set_axis_off()
    ax.set_title("")
    _add_lmsal_logo(ax)
    return "_".join(wavelength_names), fig


def save_figures(
    list_of_figs: Iterable[tuple[str, plt.Figure]], save_directory: Path, *, close: bool = True
) -> list[Path]:
    """
    Save figures as JPEG images.

    Parameters
    ----------
    list_of_figs : (Iterable[Tuple[str, plt.Figure]])
        An iterable of tuples containing the wavelength and the corresponding figure.
        Figures are closed after saving to free memory.
    save_directory : pathlib.Path
        The directory where the JPEG images will be saved.
    close : bool, optional
        Close each figure after saving (the default). Pass False when the
        figure will be saved again, e.g. for the PFSS overlay variants.

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
        thumb_path = save_directory / settings.sdo_fig_name_thumb.format(wavelength)
        try:
            _save_jpeg_set(fig, full_path, small_path, thumb_path, settings)
            saved_paths.extend((full_path, small_path, thumb_path))
        finally:
            if close:
                plt.close(fig)
                gc.collect()
    return saved_paths


def _save_jpeg_set(fig: plt.Figure, full_path: Path, small_path: Path, thumb_path: Path, settings: Settings) -> None:
    """
    Save one figure as its full/small/thumb JPEG set, atomically.

    Parameters
    ----------
    fig : `plt.Figure`
        The figure to save.
    full_path, small_path, thumb_path : pathlib.Path
        Destination paths for the three sizes.
    settings : Settings
        The application settings.
    """
    with atomic_save(full_path) as full_tmp:
        fig.savefig(full_tmp, dpi=settings.fig_dpi, pil_kwargs=JPEG_SAVE_OPTIONS)
        # Resize to 1024 - We avoid using MPL to resize the image to font issues.
        # The thumb is resized from the 1024 image, not the 4096 one: decoding
        # the full JPEG and LANCZOS-filtering it a second time costs seconds
        # per figure for no visible difference at 256 px.
        with atomic_save(small_path) as small_tmp, atomic_save(thumb_path) as thumb_tmp:
            with Image.open(str(full_tmp)) as full_jpeg:
                small_image = full_jpeg.resize(
                    (settings.resize_fig_size, settings.resize_fig_size), Image.Resampling.LANCZOS
                )
            with small_image:
                small_image.save(str(small_tmp), **JPEG_SAVE_OPTIONS)
                with small_image.resize(
                    (settings.thumb_fig_size, settings.thumb_fig_size), Image.Resampling.LANCZOS
                ) as thumb_image:
                    thumb_image.save(str(thumb_tmp), **JPEG_SAVE_OPTIONS)


def create_sdo_images(  # ruff:ignore[too-many-statements]
    requested_time: datetime.datetime,
    save_directory: Path,
    hmi_time: datetime.datetime | None = None,
    *,
    pfss: bool = False,
) -> list[Path]:
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
    hmi_time : datetime.datetime, optional
        Datetime for the HMI data; the NRT series lags AIA by an hour or
        more, so live runs pass its own freshest time. Defaults to
        ``requested_time``.
    pfss : bool, optional
        Create the matched-time PFSS variants instead of the regular
        products: every JPEG is saved twice (``pfssnolines`` base and
        ``pfss`` field line overlay from an ADAPT boundary map) and no
        planning FITS files are written. The caller should anchor
        ``requested_time`` to the lagging HMI NRT series and leave
        ``hmi_time`` unset so all the image timestamps match.

    Returns
    -------
    list of pathlib.Path
        Created files.
    """
    # The reason the files are for looped is an attempt to keep memory use <4GB for the
    # cheap VM on AWS.
    saved_paths = []
    with tempfile.TemporaryDirectory() as temp_dir:
        field_lines = None
        if pfss:
            adapt_file = fetch_adapt_fits(requested_time, save_directory=Path(temp_dir))
            logger.info("Tracing PFSS field lines")
            field_lines = trace_field_lines(create_adapt_map(adapt_file))

        aia_files = fetch_aia_fits(requested_time, save_directory=Path(temp_dir))
        aia_order = AIA_WAVELENGTHS + AIA_FITS_ONLY_WAVELENGTHS
        aia_files = sorted(aia_files, key=lambda x: aia_order.index(Path(x).stem.split("_")[-1]))
        hmi_files = fetch_hmi_fits(hmi_time or requested_time, save_directory=Path(temp_dir))
        aia_files_by_wavelength = {}
        hmi_files_by_measurement = {}

        logger.info(f"Creating figures for {len(aia_files)} AIA channels")
        for aia_file in aia_files:
            aia_path = Path(aia_file)
            wavelength_key = aia_path.stem.split("_")[-1]
            aia_files_by_wavelength[wavelength_key] = aia_path
            if pfss and wavelength_key in AIA_FITS_ONLY_WAVELENGTHS:
                continue
            aia_map = create_aia_map(aia_path)
            if not pfss:
                saved_paths.append(
                    save_fits(aia_map, save_directory, f"f{WAVELENGTH_FORMAT.format(aia_map.wavelength.value)}.fits")
                )
            if wavelength_key not in AIA_FITS_ONLY_WAVELENGTHS:
                saved_paths.extend(_save_product(create_figure_from_map(aia_map), aia_map, field_lines, save_directory))
            del aia_map
            gc.collect()

        logger.info(f"Creating figures for {len(hmi_files)} HMI measurements")
        for hmi_file in hmi_files:
            hmi_path = Path(hmi_file)
            hmi_map = create_hmi_map(hmi_path)
            hmi_files_by_measurement[hmi_map.measurement] = hmi_path
            if not pfss:
                hmi_fits_name = HMI_MEASUREMENT_FITS.get(hmi_map.measurement)
                saved_paths.append(save_fits(hmi_map, save_directory, f"f{hmi_fits_name}.fits"))
            saved_paths.extend(_save_product(create_figure_from_map(hmi_map), hmi_map, field_lines, save_directory))
            del hmi_map
            gc.collect()

        logger.info(f"Creating {len(RGB_COMBINATIONS)} RGB composite figures")
        for rgb_comb in RGB_COMBINATIONS:
            maps = [create_aia_map(aia_files_by_wavelength[wavelength]) for wavelength in rgb_comb]
            figure = create_rgb_figure_from_maps(maps)
            # Only the first map (pixel grid anchor) is needed past this point;
            # drop the other two before the savefig memory spike.
            maps = maps[0]
            saved_paths.extend(_save_product(figure, maps, field_lines, save_directory))
            del maps
            gc.collect()

        # Blend combination is only HMI B_LOS and AIA 171 currently
        logger.info("Creating HMI/AIA blended figure")
        hmi_blos = hmi_files_by_measurement["magnetogram"]
        maps = [create_hmi_map(hmi_blos), create_aia_map(aia_files_by_wavelength["171"])]
        figure = create_blended_figure_from_maps(maps)
        maps = maps[0]
        saved_paths.extend(_save_product(figure, maps, field_lines, save_directory))
        del maps
        gc.collect()
    return saved_paths


def _save_product(
    figure: tuple[str, plt.Figure],
    amap: smap.GenericMap,
    field_lines: SkyCoord | None,
    save_directory: Path,
) -> list[Path]:
    """
    Save one figure product, as a pfssnolines/pfss pair when field lines are
    given.

    Parameters
    ----------
    figure : tuple of (str, `plt.Figure`)
        Wavelength filename part and figure, as the create_* functions
        return them. The figure is closed after the last save.
    amap : `sunpy.map.GenericMap`
        Map defining the pixel grid the figure's main axes uses.
    field_lines : `astropy.coordinates.SkyCoord` or None
        Field lines from `suntoday.pfss.trace_field_lines`, or None to
        save the plain product.
    save_directory : pathlib.Path
        Save directory for the JPEGs.

    Returns
    -------
    list of pathlib.Path
        Saved JPEG paths.
    """
    wavelength, fig = figure
    if field_lines is None:
        return save_figures([(wavelength, fig)], save_directory)
    saved_paths = save_figures([(wavelength + "pfssnolines", fig)], save_directory, close=False)
    _draw_field_lines(fig.axes[0], amap, field_lines)
    saved_paths.extend(save_figures([(wavelength + "pfss", fig)], save_directory))
    return saved_paths
