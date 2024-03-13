"""
Generates the SDO/AIA and GOES lightcurve the previous 24 hours.
"""

from datetime import datetime
from pathlib import Path

import matplotlib.figure
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import dates, ticker

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import AIA_COLORS, AIA_WAVELENGTHS

__all__ = ["add_aia_lightcurve", "add_goes_lightcurve", "create_lightcurve_figure", "plot_lightcurve_from_timeseries"]


def add_aia_lightcurve(ax: plt.Axes, timeseries: pd.DataFrame, wavelengths: list[str] = AIA_WAVELENGTHS) -> None:
    """
    Plots the SDO/AIA lightcurve on the given axis.

    Parameters
    ----------
    ax : matplotlib.axes
        Axes to plot the lightcurve on.
    timeseries : pandas.DataFrame
        `~pandas.DataFrame` containing the AIA data.
    wavelengths : list of int
        Wavelengths to plot.
        Defaults to `~suntoday.constants.AIA_WAVELENGTHS`.
    """
    grouped_wavelength = timeseries.groupby(["WAVELNTH"])
    for wavelength in wavelengths:
        if wavelength not in grouped_wavelength.groups:
            logger.warning(f"No data for AIA-{wavelength} in the last 24 hours.")
            continue
        data = grouped_wavelength.get_group((wavelength,))
        values = (data["DATAMEAN"] / data["EXPTIME"]).ewm(span=5).mean()
        ax.plot(
            values[values.between(values.quantile(0.005), values.quantile(0.999))],
            color=AIA_COLORS[wavelength],
            label=f"AIA-{wavelength}" + r"$\AA$",
            linewidth=2,
        )
        # Only set the hour and minute as the last axis is the GOES axis
        # which will have the full date.
        time_formatter = dates.DateFormatter("%H:%M")
        ax.xaxis.set_major_formatter(time_formatter)
        ax.tick_params(which="major", direction="in", size=8, labelsize=10)
        ax.tick_params(which="minor", direction="in", size=3, labelsize=10)
        ax.xaxis.grid(visible=True, which="major", color="black")
        ax.legend(frameon=True, framealpha=1, loc="best")
        ax.set_ylabel(r"Data Mean (DN)", size=10)


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
    grouped_energy = timeseries.groupby(["energy"])
    ax.plot(
        grouped_energy.get_group(("0.1-0.8nm",))["flux"],
        color="red",
        label=f"GOES-{sat_number} 1.0-8.0" + r"$\AA$",
        linewidth=2,
    )
    ax.plot(
        grouped_energy.get_group(("0.05-0.4nm",))["flux"],
        color="blue",
        label=f"GOES-{sat_number} 0.5-4.0" + r"$\AA$",
        linewidth=2,
    )
    ax.set_ylabel(r"Flux (Watts $\cdot$ m$^{-2}$)", size=10)
    ax.set_xlabel("Time (UTC)", size=10)
    ax.set_yscale("log")
    ax.set_ylim([10**-9, 10**-2])
    ax.set_yticks([10**-8, 10**-7, 10**-6, 10**-5, 10**-4, 10**-3])
    ax.tick_params(which="major", direction="in", size=8, labelsize=10)
    ax.tick_params(which="minor", direction="in", size=3, labelsize=10)
    ax.yaxis.set_minor_locator(ticker.LogLocator(numticks=999, subs="auto"))
    ax_rhs = ax.twinx()
    ax_rhs.set_yscale("log")
    ax_rhs.set_ylabel("GOES Class", size=10)
    ax_rhs.set_ylim([10**-9, 10**-2])
    ax_rhs.set_yticks([3 * 10**-8, 3 * 10**-7, 3 * 10**-6, 3 * 10**-5, 3 * 10**-4])
    # Other choice is [1 * 10**-8, 1 * 10**-7, 1 * 10**-6, 1 * 10**-5, 1 * 10**-4, 1 * 10**-3]p
    for band in [3 * 10**-8, 3 * 10**-7, 3 * 10**-6, 3 * 10**-5, 3 * 10**-4]:
        ax_rhs.axhline(band, color="grey", ls="-", lw=0.4)
    ax_rhs.set_yticklabels(["A", "B", "C", "M", "X"], fontsize=10)
    ax_rhs.tick_params(which="major", direction="in", size=8, labelsize=10)
    ax_rhs.tick_params(which="minor", direction="in", size=0, labelsize=0)
    locator = ax.xaxis.get_major_locator()
    ax.xaxis.set_major_formatter(dates.ConciseDateFormatter(locator))
    ax.xaxis.grid(visible=True, which="major", color="black")
    ax.legend(frameon=True, framealpha=1, loc="best", ncol=2)


def plot_lightcurve_from_timeseries(
    goes_timeseries: pd.DataFrame,
    aia_timeseries: pd.DataFrame,
) -> matplotlib.figure.Figure:
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
        len(AIA_WAVELENGTHS) + 1,
        1,
        figsize=(settings.timeseries_fig_x_size, settings.timeseries_fig_y_size),
        dpi=settings.fig_dpi,
    )
    for axis, wavelength in zip(axes[:-1], AIA_WAVELENGTHS, strict=True):
        add_aia_lightcurve(axis, aia_timeseries, [wavelength])
    add_goes_lightcurve(axes[-1], goes_timeseries)
    fig.tight_layout()
    return fig


def create_lightcurve_figure(end_time: datetime, save_directory: Path) -> None:
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
    """
    from suntoday.downloaders.goes import fetch_goes_timeseries
    from suntoday.downloaders.jsoc import fetch_aia_timeseries

    aia_timeseries = fetch_aia_timeseries(end_time)
    goes_primary_timeseries, _goes_secondary_timeseries = fetch_goes_timeseries()
    fig = plot_lightcurve_from_timeseries(goes_primary_timeseries, aia_timeseries)
    plot_path = save_directory / f"lightcurve_{end_time:%Y%m%d}.png"
    fig.savefig(str(plot_path), dpi=fig.dpi)
    logger.debug(f"Timeseries figure saved to {plot_path}")
    plt.close(fig)
    aia_path = save_directory / "aia_light_curves.txt"
    aia_timeseries.to_csv(aia_path, sep="\t", date_format="%Y-%m-%dT%H:%M:%SZ")
    logger.debug(f"AIA timeseries txt saved to {aia_path}")
    goes_path = save_directory / "goes_light_curves.txt"
    goes_primary_timeseries.to_csv(goes_path, sep="\t", date_format="%Y-%m-%dT%H:%M:%SZ")
    logger.debug(f"GOES timeseries txt saved to {goes_path}")
