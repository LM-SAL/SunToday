from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from suntoday.constants import AIA_WAVELENGTHS
from suntoday.downloaders.jsoc import (
    fetch_aia_fits,
    fetch_aia_timeseries,
    fetch_hmi_fits,
    get_aia_urls,
    get_hmi_urls,
)


@pytest.mark.remote_data
def test_get_aia_urls() -> None:
    aia_urls = get_aia_urls(datetime.now(UTC) - timedelta(days=2))
    assert isinstance(aia_urls, pd.DataFrame)
    assert len(aia_urls) == len(AIA_WAVELENGTHS)
    assert len(aia_urls.columns) == 3
    assert sorted(aia_urls.columns) == sorted(["WAVELNTH", "EXPTIME", "image_lev1p5"])
    assert sorted(aia_urls["WAVELNTH"].tolist()) == sorted([
        "94",
        "131",
        "171",
        "193",
        "211",
        "304",
        "335",
        "1600",
        "1700",
    ])
    assert str(aia_urls["WAVELNTH"].dtype) == "str"
    assert aia_urls["EXPTIME"].dtype == "float64"


@pytest.mark.remote_data
def test_get_hmi_urls() -> None:
    hmi_urls = get_hmi_urls(datetime.now(UTC) - timedelta(days=2))
    assert isinstance(hmi_urls, pd.DataFrame)
    assert len(hmi_urls) == 2
    assert len(hmi_urls.columns) == 2
    assert sorted(hmi_urls.columns) == sorted(["WAVELNTH", "URL"])
    assert sorted(hmi_urls["WAVELNTH"].tolist()) == sorted(["continuum", "magnetogram"])
    assert str(hmi_urls["WAVELNTH"].dtype) == "str"


@pytest.mark.remote_data
def test_fetch_aia_fits(tmp_path) -> None:
    files = fetch_aia_fits(datetime.now(UTC) - timedelta(days=2), time_span="36s", save_directory=tmp_path)
    assert len(files) == 9
    assert all(str(tmp_path) in file for file in files)
    all_wavelengths = [f.split("_")[-1].split(".")[0] for f in files]
    assert set(all_wavelengths) == set(AIA_WAVELENGTHS)


@pytest.mark.remote_data
def test_fetch_hmi_fits(tmp_path) -> None:
    files = fetch_hmi_fits(datetime.now(UTC) - timedelta(days=2), save_directory=tmp_path)
    assert len(files) == 2
    assert all(str(tmp_path) in file for file in files)
    all_wavelengths = [f.split("_")[-1].split(".")[0] for f in files]
    assert set(all_wavelengths) == {"magnetogram", "continuum"}


@pytest.mark.remote_data
def test_fetch_aia_timeseries() -> None:
    aia_ts = fetch_aia_timeseries(datetime.now(UTC) - timedelta(days=2))
    assert isinstance(aia_ts, pd.DataFrame)
    assert len(aia_ts) > 0
    assert len(aia_ts.columns) == 4
    assert sorted(aia_ts.columns) == sorted(["WAVELNTH", "DATAMEAN", "QUALITY", "EXPTIME"])
    assert sorted(aia_ts["WAVELNTH"].unique().tolist()) == sorted([
        "94",
        "131",
        "171",
        "193",
        "211",
        "304",
        "335",
        "1600",
        "1700",
        "4500",
    ])
    assert str(aia_ts["WAVELNTH"].dtype) == "str"
    assert aia_ts["DATAMEAN"].dtype == "float64"
    assert aia_ts["EXPTIME"].dtype == "float64"
    assert str(aia_ts.index.dtype) == "datetime64[us, UTC]"
