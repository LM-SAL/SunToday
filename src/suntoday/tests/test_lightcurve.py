from datetime import UTC, datetime
from pathlib import Path

import matplotlib as mpl

mpl.use("module://mplcairo.base")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from suntoday.lightcurve import (
    add_aia_lightcurve,
    add_goes_lightcurve,
    create_lightcurve_figure,
    plot_lightcurve_from_timeseries,
)


def _has_jsoc_credentials() -> bool:
    from suntoday.config import Settings

    settings = Settings()
    return bool(settings.jsoc_user and settings.jsoc_password)


@pytest.mark.mpl_image_compare
def test_plot_goes_secondary_timeseries(goes_secondary_timeseries):
    fig, ax = plt.subplots(1, 1)
    add_goes_lightcurve(ax, goes_secondary_timeseries)
    return fig


@pytest.mark.mpl_image_compare
def test_plot_goes_primary_timeseries(goes_primary_timeseries):
    fig, ax = plt.subplots(1, 1)
    add_goes_lightcurve(ax, goes_primary_timeseries)
    return fig


@pytest.mark.mpl_image_compare
def test_add_aia_lightcurve(aia_timeseries):
    fig, ax = plt.subplots(1, 1)
    add_aia_lightcurve(ax, aia_timeseries)
    return fig


@pytest.mark.mpl_image_compare
def test_plot_lightcurve_from_timeseries(aia_timeseries, goes_primary_timeseries):
    return plot_lightcurve_from_timeseries(goes_primary_timeseries, aia_timeseries)


@pytest.mark.remote_data
@pytest.mark.skipif(not _has_jsoc_credentials(), reason="JSOC test credentials are not configured.")
@pytest.mark.mpl_image_compare
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
    saved_figure = tmpdir / Path("lightcurve_" + datetime_now.strftime("%Y%m%d") + ".png")
    assert saved_figure.exists()
    assert saved_figure.isfile()

    aia_lightcurve_file = tmpdir / Path("aia_light_curves.txt")
    goes_lightcurve_file = tmpdir / Path("goes_light_curves.txt")
    assert set(saved_files) == {saved_figure, aia_lightcurve_file, goes_lightcurve_file}
    assert aia_lightcurve_file.exists()
    assert aia_lightcurve_file.isfile()
    assert goes_lightcurve_file.exists()
    assert goes_lightcurve_file.isfile()
    aia_lightcurve = pd.read_csv(aia_lightcurve_file, sep="\t")
    assert list(aia_lightcurve.columns) == ["DATE-OBS", "WAVELNTH", "DATAMEAN", "QUALITY", "EXPTIME"]
    assert not aia_lightcurve.empty
    assert datetime.strptime(aia_lightcurve["DATE-OBS"][0], "%Y-%m-%dT%H:%M:%S%z")
    assert aia_lightcurve["QUALITY"][0] == "0x40000000"
