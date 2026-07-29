from datetime import UTC, datetime
from pathlib import Path

import matplotlib as mpl

mpl.use("module://mplcairo.base")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from suntoday.lightcurve import (
    _format_aia_timeseries,
    add_aia_lightcurve,
    add_goes_lightcurve,
    create_lightcurve_figure,
    plot_lightcurve_from_timeseries,
)
from suntoday.tests.conftest import mpl_svg_compare


def test_format_aia_timeseries() -> None:
    timeseries = pd.DataFrame(
        {
            "WAVELNTH": [211, 335],
            "DATAMEAN": [81.184, 1.98],
            "QUALITY": ["0x40000004", "0x40000004"],
            "EXPTIME": [2.0, 2.0],
        },
        index=pd.to_datetime(["2026-07-15T03:23:09.620Z", "2026-07-15T03:23:12.620Z"]),
    )
    timeseries.index.name = "DATE-OBS"

    assert _format_aia_timeseries(timeseries) == (
        "               DATE_OBS  WAVELNTH DATAMEAN  EXPTIME    QUALITY\n"
        "2026-07-15T03:23:09.62Z       211    81.18 2.000000 1073741828\n"
        "2026-07-15T03:23:12.62Z       335     1.98 2.000000 1073741828\n"
    )


def test_add_aia_lightcurve_drops_bad_quality_frames() -> None:
    # Middle frame is an ISS-loop-open calibration frame (bit 17) with a
    # near-zero DATAMEAN; it must not be plotted or drag the smoothed curve.
    timeseries = pd.DataFrame(
        {
            "WAVELNTH": ["171"] * 5,
            "DATAMEAN": [132.0, 131.0, -0.1, 130.0, 133.0],
            "QUALITY": ["0x40000004", "0x40000004", "0x40220004", "0x40000004", "0x40000004"],
            "EXPTIME": [2.0] * 5,
        },
        index=pd.date_range("2026-07-15T03:00:00Z", periods=5, freq="90s"),
    )
    fig, ax = plt.subplots(1, 1)
    add_aia_lightcurve(ax, timeseries, ["171"])
    plotted = ax.lines[0].get_ydata()
    assert len(plotted) > 0
    assert (plotted > 50).all()
    plt.close(fig)


def test_add_aia_lightcurve_drops_calibration_frames() -> None:
    # Middle frame is a calibration-sequence frame (bit 18) with a 5 ms
    # exposure; exposure-normalized it would be a ~1e6 DN/s spike.
    timeseries = pd.DataFrame(
        {
            "WAVELNTH": ["211"] * 5,
            "DATAMEAN": [114.0, 115.0, 11170.0, 113.0, 114.0],
            "QUALITY": ["0x40000000", "0x40000000", "0x40040000", "0x40000000", "0x40000000"],
            "EXPTIME": [2.9, 2.9, 0.005, 2.9, 2.9],
        },
        index=pd.date_range("2026-07-28T20:05:00Z", periods=5, freq="90s"),
    )
    fig, ax = plt.subplots(1, 1)
    add_aia_lightcurve(ax, timeseries, ["211"])
    plotted = ax.lines[0].get_ydata()
    assert len(plotted) > 0
    assert (plotted < 100).all()
    plt.close(fig)


@mpl_svg_compare
def test_plot_goes_primary_timeseries(goes_primary_timeseries):
    fig, ax = plt.subplots(1, 1)
    add_goes_lightcurve(ax, goes_primary_timeseries)
    return fig


@mpl_svg_compare
def test_add_aia_lightcurve(aia_timeseries):
    fig, ax = plt.subplots(1, 1)
    add_aia_lightcurve(ax, aia_timeseries)
    return fig


@mpl_svg_compare
def test_plot_lightcurve_from_timeseries(aia_timeseries, goes_primary_timeseries):
    return plot_lightcurve_from_timeseries(goes_primary_timeseries, aia_timeseries)


@mpl_svg_compare
def test_plot_lightcurve_from_timeseries_real(real_aia_timeseries, real_goes_primary_timeseries):
    # Real flare morphology, so styling changes can be judged on data that
    # actually looks like production, not the synthetic ramps above.
    return plot_lightcurve_from_timeseries(real_goes_primary_timeseries, real_aia_timeseries)


@pytest.mark.remote_data
def test_create_lightcurve_figure(tmpdir) -> None:
    datetime_now = datetime.now(UTC)
    saved_files = create_lightcurve_figure(datetime_now, tmpdir)
    saved_figure = tmpdir / Path("aia_light_curves.gif")
    assert saved_figure.exists()
    assert saved_figure.isfile()

    aia_lightcurve_file = tmpdir / Path("aia_light_curves.txt")
    goes_lightcurve_file = tmpdir / Path("goes_light_curves.txt")
    assert set(saved_files) == {saved_figure, aia_lightcurve_file, goes_lightcurve_file}
    assert aia_lightcurve_file.exists()
    assert aia_lightcurve_file.isfile()
    assert goes_lightcurve_file.exists()
    assert goes_lightcurve_file.isfile()
    aia_lightcurve = pd.read_fwf(aia_lightcurve_file)
    assert list(aia_lightcurve.columns) == ["DATE_OBS", "WAVELNTH", "DATAMEAN", "EXPTIME", "QUALITY"]
    assert not aia_lightcurve.empty
    assert pd.to_datetime(aia_lightcurve["DATE_OBS"][0])
    assert pd.api.types.is_integer_dtype(aia_lightcurve["QUALITY"])
