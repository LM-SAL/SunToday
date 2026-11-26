"""
The SDO JPEG products: single AIA and HMI channels, RGB composites, the HMI/AIA
blend, and the PFSS overlay variant of each.

Every ``create_*_figure`` function returns the part of the filename that
names the product, and its figure.
"""

import gc
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import astropy.units as u
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
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
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits, fetch_hmi_synoptic_fits
from suntoday.logos import PNG_IMAGE
from suntoday.maps import (
    create_aia_map,
    create_hmi_map,
    create_hmi_synoptic_map,
)
from suntoday.pfss import trace_field_lines
from suntoday.utils import atomic_save, save_fits

if TYPE_CHECKING:
    import datetime as dt

    import sunpy.map as smap
    from astropy.coordinates import SkyCoord

__all__ = [
    "create_blended_figure_from_maps",
    "create_figure_from_map",
    "create_rgb_figure_from_maps",
    "create_sdo_images",
    "save_figure",
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
HMI_MEASUREMENT_JPEG = {"magnetogram": "HMI BLOS", "continuum": "HMI Continuum (AIA scale)"}
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
# Thin white closed lines match the historical LMSAL PFSS rendering;
# magenta/cyan distinguish positive/negative open-field polarity.
FIELD_LINE_KWARGS = {"linewidth": 0.4, "alpha": 0.9}
FIELD_LINE_COLORS = {0: "white", 1: "magenta", -1: "cyan"}
# The logo PNG is quite dim against the black corner; brighten it.
LOGO_BRIGHTNESS = 1.25


def _full_bleed(ax: plt.Axes) -> None:
    """
    Make the axes fill the canvas, so the map is drawn at the output pixel size
    with no margin.
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
    Return a full-bleed square figure and axes at the output pixel size.
    """
    settings = Settings()
    size = settings.map_fig_size / settings.fig_dpi  # pixels / dpi = inches
    fig = plt.figure(figsize=(size, size), dpi=settings.fig_dpi, frameon=False)
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
    Draw one line of white monospace label text with a ``stroke`` outline.

    ``line`` counts upward from 0, which sits level with the logo.
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
    Return per-pixel BT.709 luminance, the weighting sRGB displays use.
    """
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _tone_map_highlights(rgb: np.ndarray, shoulder: float) -> np.ndarray:
    """
    Roll luminance above ``shoulder`` off with a tanh curve instead of
    clipping.

    All three channels are scaled by the same per-pixel ratio, so hue and
    channel balance are preserved; pixels below the shoulder are untouched.

    Parameters
    ----------
    rgb : np.ndarray
        Unclipped stretched RGB, >= 0; highlights may exceed 1.
    shoulder : float
        Luminance where the rolloff starts, in (0, 1).

    Returns
    -------
    np.ndarray
        RGB compressed into [0, 1].
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
    Draw PFSS field lines, and their two label lines, over a plotted map.

    The lines are converted to pixel coordinates of ``amap``, so this
    works on WCS axes and on the plain axes of the RGB composites alike.
    Points hidden behind the solar disk are blanked.
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
    polarity = field_lines.info.meta["polarity"]
    for sign, color in FIELD_LINE_COLORS.items():
        if np.any(polarity == sign):
            ax.plot(
                np.where(polarity == sign, pixel_x, np.nan),
                np.where(polarity == sign, pixel_y, np.nan),
                color=color,
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
        f"{'HMI synoptic':<{prefix_width}} - {field_lines.info.meta['boundary_date'].strftime('%Y-%m-%d %H:%M:%S')}",
    )
    _draw_label(ax, len(ax.texts), "PFSS: magenta=open (+), cyan=open (-), white=closed")
    # The off-limb line points would otherwise autoscale the axes outwards.
    n_y, n_x = amap.data.shape
    ax.set_xlim(-0.5, n_x - 0.5)
    ax.set_ylim(-0.5, n_y - 0.5)


def create_figure_from_map(amap: smap.GenericMap) -> tuple[str, plt.Figure]:
    """
    Return the filename part and labeled figure for one AIA or HMI map.
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
        wavelength += f" ±{HMI_NORM_GAUSS} G"
    wavelength_filename = (
        WAVELENGTH_FORMAT.format(amap.wavelength.value) if is_aia else HMI_MEASUREMENT_JPEG_FILENAMES[amap.measurement]
    )
    _draw_label(ax, 0, _map_label(amap, wavelength))
    _finish_figure(ax)
    return wavelength_filename, fig


def create_rgb_figure_from_maps(maps: list[smap.GenericMap]) -> tuple[str, plt.Figure]:
    """
    Return the filename part and figure for an (R, G, B) AIA composite.
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
    # As 8-bit pixels, converted the way matplotlib would: the figure then
    # holds 50 MB instead of the 200 MB float image until it is closed.
    ax.imshow((rgb * 255).astype(np.uint8), origin="lower")
    del rgb
    wavelength_names = []
    for i, (amap, color) in enumerate(zip(maps, ("red", "green", "blue"), strict=True)):
        wavelength_names.append(WAVELENGTH_FORMAT_BLEND.format(amap.wavelength.value))
        label = _map_label(amap, WAVELENGTH_FORMAT_LABEL.format(amap.wavelength.value))
        _draw_label(ax, len(maps) - 1 - i, label, stroke=color)
    _finish_figure(ax)
    return "_" + "_".join(wavelength_names), fig


def create_blended_figure_from_maps(maps: list[smap.GenericMap]) -> tuple[str, plt.Figure]:
    """
    Return the filename part and figure for ``[hmi, aia]`` screen-blended.
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


def save_figure(wavelength: str, fig: plt.Figure, save_directory: Path, *, close: bool = True) -> list[Path]:
    """
    Save a figure as its full, small and thumbnail JPEGs.

    The figure is closed afterwards to free its memory unless ``close`` is
    False, which the PFSS variant needs in order to save it a second time.

    Returns
    -------
    list of pathlib.Path
        The three JPEGs.
    """
    settings = Settings()
    paths = [
        save_directory / name.format(wavelength)
        for name in (settings.sdo_fig_name_large, settings.sdo_fig_name_small, settings.sdo_fig_name_thumb)
    ]
    try:
        _save_jpeg_set(fig, *paths, settings)
    finally:
        if close:
            plt.close(fig)
            gc.collect()
    return paths


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
    requested_time: dt.datetime,
    save_directory: Path,
    hmi_time: dt.datetime | None = None,
    *,
    pfss: bool = False,
    boundary_time: dt.datetime | None = None,
    download_directory: Path | None = None,
) -> list[Path]:
    """
    Render and save every SDO product for a time, with the planning FITS files.

    Parameters
    ----------
    requested_time : datetime.datetime
        Time of the AIA data.
    save_directory : pathlib.Path
        Where the products are written.
    hmi_time : datetime.datetime, optional
        Time of the HMI data, which lags AIA by an hour or more, so live
        runs pass its own newest time. Defaults to ``requested_time``.
    pfss : bool, optional
        Make the PFSS variants instead: every JPEG is saved as a
        ``pfssnolines`` base and a ``pfss`` overlay, and no planning FITS
        are written. Leave ``hmi_time`` unset so the image times match.
    boundary_time : datetime.datetime, optional
        Latest acceptable HMI synoptic boundary time. Pass the epoch the job
        already chose, so the boundary traced is the one it records.
        Defaults to ``requested_time``.
    download_directory : pathlib.Path, optional
        Where the FITS files are downloaded. Files already there are reused,
        so a main and a PFSS run sharing it fetch the data once. Defaults to
        a temporary directory.

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
            synoptic_file = fetch_hmi_synoptic_fits(boundary_time or requested_time, save_directory=fits_directory)
            logger.info("Tracing PFSS field lines")
            field_lines = trace_field_lines(create_hmi_synoptic_map(synoptic_file))

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
                hmi_fits_name = HMI_MEASUREMENT_FITS[hmi_map.measurement]
                saved_paths.append(save_fits(hmi_map, save_directory, f"f{hmi_fits_name}.fits", quantize=True))
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
    Save a product, as a pfssnolines/pfss pair when given field lines.
    """
    wavelength, fig = figure
    if field_lines is None:
        return save_figure(wavelength, fig, save_directory)
    saved_paths = save_figure(wavelength + "pfssnolines", fig, save_directory, close=False)
    _draw_field_lines(fig.axes[0], amap, field_lines)
    return saved_paths + save_figure(wavelength + "pfss", fig, save_directory)
