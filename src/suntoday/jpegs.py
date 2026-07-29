"""
Provides all the functions needed to create the SDO JPEG products: AIA and HMI
single channels, RGB composites, the HMI/AIA blend and the PFSS overlay
variants.
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
from astropy.visualization import ManualInterval
from matplotlib import colors
from mplcairo import operator_t
from PIL import Image
from sunpy.coordinates import Heliocentric, SphericalScreen, propagate_with_solar_surface, transform_with_sun_center

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import (
    AIA_FITS_ONLY_WAVELENGTHS,
    AIA_SINGLE_NORMS,
    AIA_WAVELENGTHS,
    HMI_NORM_GAUSS,
    RGB_COMBINATIONS,
    RGB_MAX_PERCENTILE,
    RGB_RECIPES,
)
from suntoday.downloaders.adapt import fetch_adapt_fits
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits
from suntoday.logos import PNG_IMAGE
from suntoday.maps import (
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

TEXT_X_POS = 0.02
TEXT_Y_POS_MOD = 0.02
# Vertical center of the LMSAL logo inset, so the label sits inline with it.
TEXT_Y_POS_LOGO = 0.04
# Above ~16 the stacked RGB/blend labels start overlapping.
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
# Screen blending adds light, so a colormap with a light/gray midpoint (e.g.
# "hmimag") washes out the disk instead of showing polarity. This map holds
# black out to the noise threshold and saturates to blue(-)/red(+) at the
# saturation threshold. Independent of the HMI_NORM_GAUSS display norm.
BLEND_HMI_NOISE_GAUSS = 15
BLEND_HMI_SATURATION_GAUSS = 120
# A shared instance is safe: the limits are fixed and nothing mutates it.
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
# Auto-exposure for the RGB composites: if the luminance at this percentile
# exceeds 1, the image is scaled down so it lands at the target instead.
EXPOSURE_PERCENTILE = 99.99
EXPOSURE_TARGET = 0.98
# RGB tone chain, applied after the per-channel stretch in this order:
# contrast (slope around mid-gray), auto-exposure, brightness, highlight knee
# (luminance above the shoulder rolls off toward white instead of clipping).
# Pushing brightness/contrast up or the shoulder down flattens the highlights
# into one near-white band.
RGB_CONTRAST = 1.15
RGB_BRIGHTNESS = 1.10
RGB_KNEE_SHOULDER = 0.70
# Per-frame percentile clip for single-channel AIA JPEGs, on top of sunpy's
# default per-channel stretch.
AIA_CLIP_INTERVAL = (0.01, 99.99) * u.percent
# Quality 90: Pillow's default 75 bands in the dark corona. No
# optimize/progressive: with subsampling=0 they trigger a libjpeg
# suspend-buffer bug ("OSError: broken data stream") on some real images.
JPEG_SAVE_OPTIONS = {"quality": 90, "subsampling": 0}
# Thin white closed lines match the historical LMSAL PFSS rendering; cyan
# distinguishes open lines without obscuring the solar image beneath them.
FIELD_LINE_KWARGS = {"linewidth": 0.4, "alpha": 0.9}
FIELD_LINE_COLORS = {False: "white", True: "cyan"}
# The logo PNG is quite dim against the black corner; brighten it.
LOGO_BRIGHTNESS = 1.25


def _full_bleed(ax: plt.Axes) -> None:
    """
    Expand the axes to fill the full figure canvas.

    This avoids default subplot padding so the map scales to the
    intended pixel size instead of being surrounded by margins.
    """
    fig = ax.figure
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_position([0, 0, 1, 1])


def _add_lmsal_logo(ax: plt.Axes) -> None:
    """
    Add the LMSAL logo to the bottom-right corner of the axes.
    """
    ax_logo = ax.inset_axes([0.72, 0, 0.28, 0.08])
    logo = plt.imread(PNG_IMAGE).copy()
    logo[..., :3] = np.clip(logo[..., :3] * LOGO_BRIGHTNESS, 0, 1)
    ax_logo.imshow(logo)
    ax_logo.set_axis_off()


def _create_canvas(projection=None) -> tuple[plt.Figure, plt.Axes]:
    """
    Create the full-bleed square figure and axes at the output pixel size.

    Parameters
    ----------
    projection : optional
        Passed through to ``add_subplot``, e.g. a map or a WCS.

    Returns
    -------
    tuple of (`plt.Figure`, `plt.Axes`)
        The figure and its single axes.
    """
    settings = Settings()
    fig = plt.figure(figsize=(settings.map_fig_size, settings.map_fig_size), dpi=settings.fig_dpi, frameon=False)
    ax = fig.add_subplot(111, projection=projection)
    _full_bleed(ax)
    return fig, ax


def _finish_figure(ax: plt.Axes) -> None:
    """
    Strip the axes decorations and add the LMSAL logo.
    """
    ax.set_axis_off()
    ax.set_title("")
    _add_lmsal_logo(ax)


def _draw_label(ax: plt.Axes, line: int, text: str, stroke: str = "black") -> None:
    """
    Draw one monospace annotation line, counted upward from the logo line.

    Parameters
    ----------
    ax : `matplotlib.pyplot.Axes`
        The axes to draw on.
    line : int
        Stacked line index; 0 sits inline with the logo.
    text : str
        The label text.
    stroke : str, optional
        Outline color around the white text.
    """
    ax.text(
        TEXT_X_POS,
        TEXT_Y_POS_LOGO + line * TEXT_Y_POS_MOD,
        text,
        color="white",
        transform=ax.transAxes,
        va="center",
        fontdict={"fontsize": LABEL_FONTSIZE, "family": "monospace"},
        path_effects=[pe.withStroke(linewidth=4, foreground=stroke)],
    )


def _map_label(amap: smap.GenericMap, wavelength: str) -> str:
    """
    Build the on-image label; ``wavelength`` is already formatted.
    """
    return LABEL_FORMAT.format(
        observatory=amap.observatory,
        instrument=amap.instrument.split()[0],
        wavelength=wavelength,
        date=amap.date.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _rec709_luminance(rgb: np.ndarray) -> np.ndarray:
    """
    Perceived brightness of the output image.

    Uses the Rec. 709 relative-luminance weights, which match the sRGB
    primaries the JPEGs are viewed with.

    Parameters
    ----------
    rgb : np.ndarray
        RGB image data in the last axis.

    Returns
    -------
    np.ndarray
        Relative luminance per pixel.
    """
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _tone_map_highlights(rgb: np.ndarray, shoulder: float) -> np.ndarray:
    """
    Roll off luminance above ``shoulder`` with a tanh curve instead of
    clipping.

    Expects unclipped stretched data (values may exceed 1). All three channels
    are scaled by the same per-pixel ratio, so the channel balance and hue are
    preserved; pixels below the shoulder are untouched.

    Parameters
    ----------
    rgb : np.ndarray
        RGB image data, >= 0, highlights may exceed 1.
    shoulder : float
        Luminance where the rolloff starts, in (0, 1).

    Returns
    -------
    np.ndarray
        RGB image data compressed into the [0, 1] range.
    """
    lum = _rec709_luminance(rgb)
    out_lum = np.where(
        lum > shoulder,
        shoulder + (1 - shoulder) * np.tanh((lum - shoulder) / (1 - shoulder)),
        lum,
    )
    ratio = np.where(lum > 1e-6, out_lum / np.maximum(lum, 1e-6), 1.0)
    return np.clip(rgb * ratio[..., None], 0.0, 1.0)


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
    is_open = (field_lines.info.meta or {}).get("is_open")
    if is_open is None:
        ax.plot(pixel_x, pixel_y, color=FIELD_LINE_COLORS[False], **FIELD_LINE_KWARGS)
    else:
        for open_line in (False, True):
            if np.any(is_open == open_line):
                ax.plot(
                    np.where(is_open == open_line, pixel_x, np.nan),
                    np.where(is_open == open_line, pixel_y, np.nan),
                    color=FIELD_LINE_COLORS[open_line],
                    **FIELD_LINE_KWARGS,
                )
    # Pad so the datetime column lines up with the monospace labels already on the axes.
    date_starts = [
        match.start()
        for text in ax.texts
        if (match := re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text.get_text()))
    ]
    prefix_width = max(date_starts, default=13) - 3
    _draw_label(
        ax,
        len(ax.texts),
        f"{'PFSS ADAPT':<{prefix_width}} - {field_lines.obstime.strftime('%Y-%m-%d %H:%M:%S')}",
    )
    _draw_label(ax, len(ax.texts), "PFSS: cyan=open, white=closed")
    # The off-limb line points would otherwise autoscale the axes outwards.
    n_y, n_x = amap.data.shape
    ax.set_xlim(-0.5, n_x - 0.5)
    ax.set_ylim(-0.5, n_y - 0.5)


def create_figure_from_map(amap: smap.GenericMap) -> tuple[str, plt.Figure]:
    """
    Creates the final figure from the input AIA or HMI Map.

    Adds the LMSAL logo, the timestamp and the wavelength/measurement label.

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
    fig, ax = _create_canvas(projection=amap)
    is_aia = "AIA" in amap.instrument
    norm = None
    if is_aia:
        override = AIA_SINGLE_NORMS.get(f"{amap.wavelength.value:.0f}")
        norm = override() if override is not None else None
    clip_interval = AIA_CLIP_INTERVAL if is_aia and norm is None else None
    # Forwarding norm=None would override the map's plot_settings norm and autoscale.
    norm_kwargs = {} if norm is None else {"norm": norm}
    amap.plot(axes=ax, clip_interval=clip_interval, autoalign=False, interpolation="nearest", **norm_kwargs)
    wavelength = (
        WAVELENGTH_FORMAT_LABEL.format(amap.wavelength.value) if is_aia else HMI_MEASUREMENT_JPEG[amap.measurement]
    )
    if not is_aia and amap.measurement == "magnetogram":
        wavelength += f" +-{HMI_NORM_GAUSS} G"
    wavelength_filename = (
        WAVELENGTH_FORMAT.format(amap.wavelength.value) if is_aia else HMI_MEASUREMENT_JPEG_FILENAMES[amap.measurement]
    )
    _draw_label(ax, 0, _map_label(amap, wavelength))
    _finish_figure(ax)
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
        If the wavelength combination has no `suntoday.constants.RGB_RECIPES` entry.
    """
    if len(maps) != 3:
        msg = "RGB figure needs exactly three maps."
        raise ValueError(msg)
    combo = tuple(f"{amap.wavelength.value:.0f}" for amap in maps)
    if (recipe := RGB_RECIPES.get(combo)) is None:
        msg = f"No RGB recipe for wavelength combination {combo}."
        raise ValueError(msg)
    factors, stretch = recipe
    fig, ax = _create_canvas()
    maximum = max(np.percentile(amap.data, RGB_MAX_PERCENTILE) for amap in maps)
    intervals = [ManualInterval(vmin=0, vmax=maximum * factor) for factor in factors]
    # Not astropy's make_rgb: it hard-clips to [0, 1] before the highlight
    # rolloff can compress the bright cores. float32 per channel: the float64
    # stack would transiently cost ~600 MB at 4096 px.
    channels = [
        stretch(np.clip(interval(amap.data, clip=False), 0, None), clip=False).astype(np.float32)
        for amap, interval in zip(maps, intervals, strict=True)
    ]
    rgb = np.stack(channels, axis=-1)
    del channels
    rgb = (rgb - 0.5) * RGB_CONTRAST + 0.5
    rgb = np.clip(rgb, 0, None)
    peak = np.percentile(_rec709_luminance(rgb), EXPOSURE_PERCENTILE)
    if peak > 1:
        rgb *= EXPOSURE_TARGET / peak
    rgb *= RGB_BRIGHTNESS
    rgb = _tone_map_highlights(rgb, RGB_KNEE_SHOULDER)
    ax.imshow(rgb, origin="lower")
    wavelength_names = []
    for i, (amap, color) in enumerate(zip(maps, ("red", "green", "blue"), strict=True)):
        wavelength_names.append(WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value))
        label = _map_label(amap, WAVELENGTH_FORMAT_LABEL.format(amap.wavelength.value))
        _draw_label(ax, len(maps) - 1 - i, label, stroke=color)
    _finish_figure(ax)
    return "_" + "_".join(wavelength_names), fig


def create_blended_figure_from_maps(maps: list[smap.GenericMap]) -> tuple[str, plt.Figure]:
    """
    Create a blended figure from an HMI magnetogram and an AIA map.

    Parameters
    ----------
    maps : `list[smap.GenericMap]`
        Exactly two maps: the HMI map first, then the AIA map screened
        on top of it.

    Returns
    -------
    str
        The wavelength of the map(s). This is used as part of the filename.
    `plt.Figure`
        The figure object.
    """
    hmi_map, aia_map = maps
    fig, ax = _create_canvas(projection=hmi_map.wcs)
    hmi_map.plot(axes=ax, cmap=BLEND_HMI_CMAP, norm=BLEND_HMI_NORM, autoalign=False, interpolation="nearest")
    _draw_label(ax, 2, BLEND_POLARITY_LABEL)
    hmi_label = HMI_MEASUREMENT_JPEG[hmi_map.measurement]
    _draw_label(ax, 1, _map_label(hmi_map, hmi_label))
    # Pad to the HMI label width so the monospace columns line up.
    aia_label = WAVELENGTH_FORMAT_LABEL.format(aia_map.wavelength.value).strip().center(len(hmi_label))
    _draw_label(ax, 0, _map_label(aia_map, aia_label))
    with SphericalScreen(hmi_map.observer_coordinate):
        # Serial: parallel worker processes exceed the 4 GB VM, and with
        # roundtrip_coords off serial is faster anyway.
        reprojected_map = aia_map.reproject_to(
            hmi_map.wcs, parallel=False, return_footprint=False, block_size=(256, 256), roundtrip_coords=False
        )
    im_aia = reprojected_map.plot(axes=ax, interpolation="nearest", autoalign=False)
    del reprojected_map
    operator_t.SCREEN.patch_artist(im_aia)
    _finish_figure(ax)
    wavelength_names = [
        HMI_MEASUREMENT_JPEG_FILENAMES[hmi_map.measurement],
        WAVELENGTH_FORMAT_BLEND.format(aia_map.wavelength.value),
    ]
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
    """
    with atomic_save(full_path) as full_tmp:
        fig.savefig(full_tmp, dpi=settings.fig_dpi, pil_kwargs=JPEG_SAVE_OPTIONS)
        # Resized with Pillow, not a second savefig, to keep the fonts sharp;
        # the thumb comes from the 1024 image because refiltering the 4096
        # JPEG costs seconds for no visible difference at 256 px.
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
    download_directory: Path | None = None,
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
        ``requested_time`` to the matched GONG ADAPT file time and leave
        ``hmi_time`` unset so all the image timestamps match.
    download_directory : pathlib.Path, optional
        Directory to download the FITS files into. Files already present
        are not re-downloaded, so passing the same directory to the main
        and PFSS runs of a backfill fetches the data once. Defaults to a
        per-call temporary directory.

    Returns
    -------
    list of pathlib.Path
        Created files.
    """
    # Looped per file to stay under the production VM's 4 GB of memory.
    saved_paths = []
    with tempfile.TemporaryDirectory() as temp_dir:
        fits_directory = download_directory or Path(temp_dir)
        field_lines = None
        if pfss:
            adapt_file = fetch_adapt_fits(requested_time, save_directory=fits_directory)
            logger.info("Tracing PFSS field lines")
            field_lines = trace_field_lines(create_adapt_map(adapt_file))

        aia_files = fetch_aia_fits(requested_time, save_directory=fits_directory)
        aia_order = AIA_WAVELENGTHS + AIA_FITS_ONLY_WAVELENGTHS
        aia_files = sorted(aia_files, key=lambda x: aia_order.index(Path(x).stem.split("_")[-1]))
        hmi_files = fetch_hmi_fits(hmi_time or requested_time, save_directory=fits_directory)
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
