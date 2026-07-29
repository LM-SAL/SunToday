"""
Generates the SDO/AIA and GOES lightcurve the previous 24 hours.
"""

import matplotlib as mpl

mpl.use("module://mplcairo.base")

from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import dates, ticker

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import AIA_COLORS, AIA_WAVELENGTHS
from suntoday.utils import atomic_save

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

# Style sizes (points) for the lightcurve figure.
LABEL_FONTSIZE = 4
TICK_FONTSIZE = 4
Y_TICK_FONTSIZE = 3
LEGEND_FONTSIZE = 3
LINEWIDTH = 1
MAJOR_TICK_SIZE = 4
MINOR_TICK_SIZE = 2


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
    ax.tick_params(which="major", direction="in", size=MAJOR_TICK_SIZE, labelsize=TICK_FONTSIZE)
    ax.tick_params(which="minor", direction="in", size=MINOR_TICK_SIZE, labelsize=TICK_FONTSIZE)
    ax.tick_params(axis="y", labelsize=Y_TICK_FONTSIZE)
    ax.xaxis.grid(visible=True, which="major", color="black")


def add_aia_lightcurve(ax: plt.Axes, timeseries: pd.DataFrame, wavelengths: list[str] = AIA_WAVELENGTHS) -> None:
    """
    Plots the SDO/AIA lightcurve on the given axis.

    Parameters
    ----------
    ax : matplotlib.axes
        Axes to plot the lightcurve on.
    timeseries : pandas.DataFrame
        `~pandas.DataFrame` containing the AIA data.
    wavelengths : list of str
        Wavelengths to plot.
        Defaults to `~suntoday.constants.AIA_WAVELENGTHS`.
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
        values = values.ewm(span=5).mean()
        ax.plot(
            values,
            color=AIA_COLORS[wavelength],
            label=f"AIA-{wavelength}" + r"$\AA$",
            linewidth=LINEWIDTH,
        )
        _style_lightcurve_axis(ax)
        ax.legend(frameon=True, framealpha=1, loc="best", fontsize=LEGEND_FONTSIZE)
        ax.set_ylabel(r"Data Mean (DN)", size=LABEL_FONTSIZE)
    # The per-channel ranges are narrow, so a full tick ladder is noise;
    # min/max-only ticks show the range directly (matching the legacy plot).
    plotted = [line.get_ydata() for line in ax.lines if len(line.get_ydata())]
    if plotted:
        ax.set_yticks([min(data.min() for data in plotted), max(data.max() for data in plotted)])
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda value, _pos: f"{value:.4g}"))


def add_goes_lightcurve(ax: plt.Axes, timeseries: pd.DataFrame) -> None:
    """
    Plots the GOES JSON lightcurve on the given axis.

    Parameters
    ----------
    ax : matplotlib.pyplot.Axes
        Axes to plot the lightcurve on.
    timeseries : pandas.DataFrame
        `~pandas.DataFrame` containing the GOES data.
    """
    sat_number = timeseries["satellite"].iloc[0]
    grouped_energy = timeseries.groupby(by="energy")
    ax.plot(
        grouped_energy.get_group("0.1-0.8nm")["flux"],
        color="red",
        label=f"GOES-{sat_number} 1.0-8.0" + r"$\AA$",
        linewidth=LINEWIDTH,
    )
    ax.plot(
        grouped_energy.get_group("0.05-0.4nm")["flux"],
        color="blue",
        label=f"GOES-{sat_number} 0.5-4.0" + r"$\AA$",
        linewidth=LINEWIDTH,
    )
    ax.set_ylabel(r"Flux (Watts $\cdot$ m$^{-2}$)", size=LABEL_FONTSIZE)
    ax.set_xlabel("Time (UTC)", size=LABEL_FONTSIZE)
    ax.set_yscale("log")
    ax.set_ylim([10**-9, 10**-2])
    ax.set_yticks([10**-8, 10**-7, 10**-6, 10**-5, 10**-4, 10**-3])
    _style_lightcurve_axis(ax)
    ax.yaxis.set_minor_locator(ticker.LogLocator(numticks=999, subs="auto"))
    ax_rhs = ax.twinx()
    ax_rhs.set_yscale("log")
    ax_rhs.set_ylabel("GOES Class", size=LABEL_FONTSIZE)
    ax_rhs.set_ylim([10**-9, 10**-2])
    ax_rhs.set_yticks([3 * 10**-8, 3 * 10**-7, 3 * 10**-6, 3 * 10**-5, 3 * 10**-4])
    # Other choice is [1 * 10**-8, 1 * 10**-7, 1 * 10**-6, 1 * 10**-5, 1 * 10**-4, 1 * 10**-3]p
    for band in [3 * 10**-8, 3 * 10**-7, 3 * 10**-6, 3 * 10**-5, 3 * 10**-4]:
        ax_rhs.axhline(band, color="grey", ls="-", lw=0.4)
    ax_rhs.set_yticklabels(["A", "B", "C", "M", "X"], fontsize=Y_TICK_FONTSIZE)
    ax_rhs.tick_params(which="major", direction="in", size=MAJOR_TICK_SIZE, labelsize=Y_TICK_FONTSIZE)
    ax_rhs.tick_params(which="minor", direction="in", size=0, labelright=False, labelleft=False)
    ax.legend(frameon=True, framealpha=1, loc="best", ncol=2, fontsize=LEGEND_FONTSIZE)


def plot_lightcurve_from_timeseries(
    goes_timeseries: pd.DataFrame,
    aia_timeseries: pd.DataFrame,
) -> mpl.figure.Figure:
    """
    Creates the actual figure from the AIA and GOES dataframes.

    Parameters
    ----------
    goes_timeseries : pandas.DataFrame
        GOES JSON dataframe.
    aia_timeseries : pandas.DataFrame
        AIA dataframe.

    Returns
    -------
    `matplotlib.figure.Figure`
        The figure ready to be saved.
    """
    settings = Settings()
    fig, axes = plt.subplots(
        len(LIGHTCURVE_WAVELENGTH_ORDER) + 1,
        1,
        sharex=True,
        figsize=(settings.timeseries_fig_x_size, settings.timeseries_fig_y_size),
        dpi=settings.fig_dpi,
    )
    add_goes_lightcurve(axes[0], goes_timeseries)
    aia_axes = axes[1:]
    for axis, wavelength in zip(aia_axes, LIGHTCURVE_WAVELENGTH_ORDER, strict=True):
        add_aia_lightcurve(axis, aia_timeseries, [wavelength])
    for axis in aia_axes:
        axis.set_ylabel("")
    aia_axes[len(aia_axes) // 2].set_ylabel(r"Data Mean (DN)", size=LABEL_FONTSIZE)
    # GOES sits on top, so the bottom (AIA) axis carries the time label.
    axes[0].set_xlabel("")
    axes[-1].set_xlabel("Time (UTC)", size=LABEL_FONTSIZE)
    fig.tight_layout(h_pad=0)
    return fig


def create_lightcurve_figure(end_time: datetime, save_directory: Path) -> list[Path]:
    """
    Creates the full timeseries plot for the given datetime and saves it to the
    given directory.

    This also saves out the data used as text files.

    Parameters
    ----------
    end_time : datetime.datetime
        Datetime to create the plot for and the previous 24 hours.
    save_directory : pathlib.Path
        Save directory for the plot.

    Returns
    -------
    list of pathlib.Path
        Created plot and data files.
    """
    from suntoday.downloaders.goes import fetch_goes_timeseries
    from suntoday.downloaders.jsoc import fetch_aia_timeseries

    logger.info("Fetching AIA and GOES timeseries for the last 24 hours")
    aia_timeseries = fetch_aia_timeseries(end_time)
    goes_timeseries = fetch_goes_timeseries(end_time)
    fig = plot_lightcurve_from_timeseries(goes_timeseries, aia_timeseries)
    plot_path = save_directory / "aia_light_curves.gif"
    with atomic_save(plot_path) as tmp_path:
        # Legacy consumers expect a .gif name; the bytes are PNG (browsers
        # sniff content, and mplcairo cannot write GIF anyway).
        fig.savefig(str(tmp_path), format="png", dpi=fig.dpi)
    plt.close(fig)
    aia_path = save_directory / "aia_light_curves.txt"
    with atomic_save(aia_path) as tmp_path:
        tmp_path.write_text(_format_aia_timeseries(aia_timeseries))
    goes_path = save_directory / "goes_light_curves.txt"
    with atomic_save(goes_path) as tmp_path:
        goes_timeseries.to_csv(tmp_path, sep="\t", date_format="%Y-%m-%dT%H:%M:%SZ")
    return [plot_path, aia_path, goes_path]
