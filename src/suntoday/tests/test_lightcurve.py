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


def _has_jsoc_credentials() -> bool:
    from suntoday.config import Settings

    settings = Settings()
    return bool(settings.jsoc_user and settings.jsoc_password)


@mpl_svg_compare
def test_plot_goes_secondary_timeseries(goes_secondary_timeseries):
    fig, ax = plt.subplots(1, 1)
    add_goes_lightcurve(ax, goes_secondary_timeseries)
    return fig


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


# Never compared in CI: tox's figure comparison env filters out remote_data,
# so this only runs under figure-generate as a live rendering smoke test.
@pytest.mark.remote_data
@pytest.mark.skipif(not _has_jsoc_credentials(), reason="JSOC test credentials are not configured.")
@mpl_svg_compare
def test_lightcurve_figure_latest():
    from suntoday.downloaders.goes import fetch_goes_timeseries
    from suntoday.downloaders.jsoc import fetch_aia_timeseries

    aia_timeseries = fetch_aia_timeseries(datetime.now(UTC))
    goes_primary_timeseries, _goes_secondary_timeseries = fetch_goes_timeseries()
    return plot_lightcurve_from_timeseries(goes_primary_timeseries, aia_timeseries)


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
