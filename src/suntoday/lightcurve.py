"""
The 24-hour AIA and GOES lightcurve figure and its data files.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import dates, ticker

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import AIA_COLORS, AIA_WAVELENGTHS
from suntoday.utils import atomic_save

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

__all__ = ["add_aia_lightcurve", "add_goes_lightcurve", "create_lightcurve_figure", "plot_lightcurve_from_timeseries"]

# Panel order top to bottom; GOES occupies the panel above these.
LIGHTCURVE_WAVELENGTH_ORDER = ["131", "94", "335", "211", "193", "171", "304", "1600", "1700"]

# AIA lev1 QUALITY bits that mark a frame as unusable for a lightcurve:
# 10-11 (>5%/>25% pixels missing), 12 (ACS not in science mode), 13 (eclipse),
# 14 (no sun presence), 15 (safe mode), 16 (dark frame), 17 (ISS loop open,
# set during calibration sequences where DATAMEAN drops to ~0), 18 and 20
# (calibration-sequence frames with off-nominal exposures — a 5 ms exposure
# turns into a ~1e6 DN/s spike once exposure-normalized), 21 (filter
# wheel not nominal — frames mid-move have partially blocked flux).
BAD_QUALITY_BITS = 0x37FC00

# Recessive hairlines: the grid is a reading aid, the curves are the data.
GRID_COLOR = "0.85"
# DN/s, not DN: the plotted value is DATAMEAN normalized by EXPTIME.
AIA_Y_LABEL = "Data Mean (DN/s)"
# W m^-2. SWPC reports this floor (as a float32, so a hair under 1e-9) when
# the electron correction swallows the signal, and 0 for a missing sample.
GOES_FLUX_FLOOR = 1e-9


def _format_aia_timeseries(timeseries: pd.DataFrame) -> str:
    data = timeseries.reset_index(names="DATE_OBS")[["DATE_OBS", "WAVELNTH", "DATAMEAN", "EXPTIME", "QUALITY"]].copy()
    data["DATE_OBS"] = data["DATE_OBS"].map(
        lambda value: value.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"
    )
    data["QUALITY"] = data["QUALITY"].map(lambda value: int(str(value), 0))
    return data.to_string(index=False, formatters={"DATAMEAN": "{:.2f}".format, "EXPTIME": "{:.6f}".format}) + "\n"


def _hour_minute_with_date_at_midnight(x: float, _pos: int | None = None) -> str:
    """
    Tick formatter: "HH:MM", plus the date underneath at midnight.
    """
    when = dates.num2date(x)
    if when.hour == 0 and when.minute == 0:
        return when.strftime("%H:%M\n%b-%d")
    return when.strftime("%H:%M")


def _style_lightcurve_axis(ax: plt.Axes) -> None:
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(_hour_minute_with_date_at_midnight))
    ax.tick_params(which="both", direction="in")
    ax.grid(axis="x", color=GRID_COLOR)


def add_aia_lightcurve(ax: plt.Axes, timeseries: pd.DataFrame, wavelengths: list[str] = AIA_WAVELENGTHS) -> None:
    """
    Plot the smoothed mean brightness of the given AIA channels on ``ax``.

    Frames flagged in ``BAD_QUALITY_BITS`` are dropped, and an axes left
    with nothing to plot says so.
    """
    grouped_wavelength = timeseries.groupby(by="WAVELNTH")
    for wavelength in wavelengths:
        if wavelength not in grouped_wavelength.groups:
            logger.warning(f"No data for AIA-{wavelength} in the last 24 hours.")
            continue
        data = grouped_wavelength.get_group(wavelength)
        data = data[data["QUALITY"].map(lambda quality: (int(str(quality), 0) & BAD_QUALITY_BITS) == 0)]
        if data.empty:
            logger.warning(f"No good-quality data for AIA-{wavelength} in the last 24 hours.")
            continue
        values = data["DATAMEAN"] / data["EXPTIME"]
        # Trim raw outliers before smoothing so one bad frame cannot smear
        # into its neighbors; no upper trim — the top of the range is real
        # flare signal and QUALITY filtering already drops bad frames.
        values = values[values >= values.quantile(0.005)]
        ax.plot(values.ewm(span=5).mean(), color=AIA_COLORS[wavelength], label=f"AIA {wavelength} Å")
    _style_lightcurve_axis(ax)
    ax.set_ylabel(AIA_Y_LABEL)
    if ax.lines:
        # The per-channel ranges are narrow, so a full tick ladder is noise;
        # min/max-only ticks show the range directly (matching the legacy
        # plot). The margin keeps them clear of the neighboring panels' ticks.
        ticks = ax.dataLim.intervaly
        ax.set_yticks(ticks, [f"{tick:.4g}" for tick in ticks])
        ax.margins(y=0.2)
        ax.legend(frameon=False)
    else:
        # Name the gap; the default 0-1 ticks would read as real zero data.
        ax.set_yticks([])
        ax.text(0.5, 0.5, f"AIA {', '.join(wavelengths)} Å: no data", transform=ax.transAxes, ha="center", va="center")


def add_goes_lightcurve(ax: plt.Axes, timeseries: pd.DataFrame) -> None:
    """
    Plot both GOES XRS bands on ``ax``, with the flare classes on the right.
    """
    sat_number = timeseries["satellite"].iloc[0]
    # A floored or missing reading is not a measurement: leave a gap instead
    # of a spike down to the bottom of the axis.
    flux = timeseries["flux"].where(timeseries["flux"] > GOES_FLUX_FLOOR).groupby(timeseries["energy"])
    ax.plot(flux.get_group("0.1-0.8nm"), color="red", label=f"GOES-{sat_number} 1.0-8.0 Å")
    ax.plot(flux.get_group("0.05-0.4nm"), color="blue", label=f"GOES-{sat_number} 0.5-4.0 Å")
    ax.set_ylabel(r"Flux (W m$^{-2}$)")
    ax.set_xlabel("Time (UTC)")
    ax.set_yscale("log")
    ax.set_ylim([GOES_FLUX_FLOOR, 10**-2])
    ax.set_yticks([10**-8, 10**-7, 10**-6, 10**-5, 10**-4, 10**-3])
    _style_lightcurve_axis(ax)
    # The decade lines are the flare class boundaries (A starts at 1e-8, X at
    # 1e-4), so each class letter labels the band between two of them.
    ax.grid(axis="y", color=GRID_COLOR)
    # Must follow set_yscale: a later scale change resets the tick labels.
    ax_rhs = ax.secondary_yaxis("right")
    ax_rhs.set_yticks([3 * 10**-8, 3 * 10**-7, 3 * 10**-6, 3 * 10**-5, 3 * 10**-4], ["A", "B", "C", "M", "X"])
    ax_rhs.tick_params(which="both", length=0)
    ax_rhs.set_ylabel("GOES Class")
    ax.legend(frameon=False, ncol=2)


def plot_lightcurve_from_timeseries(
    goes_timeseries: pd.DataFrame,
    aia_timeseries: pd.DataFrame,
    end_time: datetime,
) -> mpl.figure.Figure:
    """
    Return the figure: GOES on top, one panel per AIA channel beneath.
    """
    settings = Settings()
    dpi = settings.timeseries_fig_dpi
    fig, axes = plt.subplots(
        len(LIGHTCURVE_WAVELENGTH_ORDER) + 1,
        1,
        sharex=True,
        figsize=(settings.timeseries_fig_x_size / dpi, settings.timeseries_fig_y_size / dpi),  # pixels / dpi = inches
        dpi=dpi,
        # GOES spans seven labeled decades, each AIA panel only its min/max.
        height_ratios=[2] + [1] * len(LIGHTCURVE_WAVELENGTH_ORDER),
    )
    add_goes_lightcurve(axes[0], goes_timeseries)
    aia_axes = axes[1:]
    for axis, wavelength in zip(aia_axes, LIGHTCURVE_WAVELENGTH_ORDER, strict=True):
        add_aia_lightcurve(axis, aia_timeseries, [wavelength])
    for axis in aia_axes:
        axis.set_ylabel("")
    aia_axes[len(aia_axes) // 2].set_ylabel(AIA_Y_LABEL)
    # GOES sits on top, so the bottom (AIA) axis carries the time label.
    axes[0].set_xlabel("")
    axes[-1].set_xlabel("Time (UTC)")
    # The requested window, not the extent of the data: late or missing data
    # then shows as a gap at the edge instead of silently shifting the axis.
    axes[0].set_xlim(end_time - timedelta(days=1), end_time)
    fig.tight_layout(h_pad=0)
    return fig


def create_lightcurve_figure(end_time: datetime, save_directory: Path) -> list[Path]:
    """
    Fetch the 24 hours before ``end_time``; save the plot and its data.
    """
    from suntoday.downloaders.goes import fetch_goes_timeseries
    from suntoday.downloaders.jsoc import fetch_aia_timeseries

    logger.info("Fetching AIA and GOES timeseries for the last 24 hours")
    aia_timeseries = fetch_aia_timeseries(end_time)
    goes_timeseries = fetch_goes_timeseries(end_time)
    fig = plot_lightcurve_from_timeseries(goes_timeseries, aia_timeseries, end_time)
    plot_path = save_directory / "aia_light_curves.gif"
    with atomic_save(plot_path) as tmp_path:
        # Consumers expect a .gif name; the bytes are PNG, which browsers
        # recognize from the content.
        fig.savefig(str(tmp_path), format="png", dpi=fig.dpi)
    plt.close(fig)
    aia_path = save_directory / "aia_light_curves.txt"
    with atomic_save(aia_path) as tmp_path:
        tmp_path.write_text(_format_aia_timeseries(aia_timeseries))
    goes_path = save_directory / "goes_light_curves.txt"
    with atomic_save(goes_path) as tmp_path:
        goes_timeseries.to_csv(tmp_path, sep="\t", date_format="%Y-%m-%dT%H:%M:%SZ")
    return [plot_path, aia_path, goes_path]
