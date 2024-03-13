from datetime import UTC, datetime, timedelta

import pandas as pd

from suntoday.constants import AIA_WAVELENGTHS
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_aia_timeseries, fetch_hmi_fits, get_aia_urls, get_hmi_urls


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
    assert aia_urls["WAVELNTH"].dtype == "object"
    assert aia_urls["EXPTIME"].dtype == "float64"


def test_get_hmi_urls() -> None:
    hmi_urls = get_hmi_urls(datetime.now(UTC) - timedelta(days=2))
    assert isinstance(hmi_urls, pd.DataFrame)
    assert len(hmi_urls) == 2
    assert len(hmi_urls.columns) == 2
    assert sorted(hmi_urls.columns) == sorted(["WAVELNTH", "URL"])
    assert sorted(hmi_urls["WAVELNTH"].tolist()) == sorted(["continuum", "magnetogram"])
    assert hmi_urls["WAVELNTH"].dtype == type(object)


def test_fetch_aia_fits(tmp_path) -> None:
    files = fetch_aia_fits(datetime.now(UTC) - timedelta(days=2), time_span="36s", save_directory=tmp_path)
    assert len(files) == 9
    assert all(str(tmp_path) in file for file in files)
    all_wavelengths = [f.split("_")[-1].split(".")[0] for f in files]
    assert set(all_wavelengths) == set(AIA_WAVELENGTHS)


def test_fetch_hmi_fits(tmp_path) -> None:
    files = fetch_hmi_fits(datetime.now(UTC) - timedelta(days=2), save_directory=tmp_path)
    assert len(files) == 2
    assert all(str(tmp_path) in file for file in files)
    all_wavelengths = [f.split("_")[-1].split(".")[0] for f in files]
    assert set(all_wavelengths) == {"magnetogram", "continuum"}


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
    assert aia_ts["WAVELNTH"].dtype == "object"
    assert aia_ts["DATAMEAN"].dtype == "float64"
    # Check that bad quality data has been replaced with NaNs
    assert aia_ts.loc[aia_ts["QUALITY"] != "0x40000000", "DATAMEAN"].isna().all()
    assert aia_ts["EXPTIME"].dtype == "float64"
    assert aia_ts.index.dtype == "datetime64[ns, UTC]"
