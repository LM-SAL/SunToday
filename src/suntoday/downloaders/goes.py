"""
Provides GOES XRS downloaders: the SWPC NRT JSON for recent times and the NOAA
NCEI science archive for historical backfills.
"""

import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests

from suntoday import DataNotReadyError

__all__ = ["fetch_goes_timeseries"]

GOES_NRT_URL = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"
GOES_RETRIES = 2
GOES_TIMEOUT = 60
GOES_RETRY_DELAY = 5
# sunpy XRS timeseries column -> energy band label used by the SWPC JSON.
GOES_ENERGY_BANDS = {"xrsa": "0.05-0.4nm", "xrsb": "0.1-0.8nm"}


def _reformat_goes_df(goes_df: pd.DataFrame) -> pd.DataFrame:
    """
    Set a datetime index, drop the unused columns and fix the dtypes.
    """
    goes_df = goes_df.set_index("time_tag")
    goes_df.index = pd.to_datetime(goes_df.index)
    goes_df = goes_df.drop(columns=["observed_flux", "electron_correction", "electron_contaminaton"])
    return goes_df.astype({"satellite": int, "flux": float, "energy": str})


def _read_goes_json(url: str) -> pd.DataFrame:
    """
    Fetch a GOES JSON file into a DataFrame, retrying transient failures.
    """
    last_error: Exception | None = None
    for attempt in range(GOES_RETRIES + 1):
        try:
            response = requests.get(url, timeout=GOES_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            last_error = e
            if attempt < GOES_RETRIES:
                time.sleep(GOES_RETRY_DELAY)
        else:
            return pd.DataFrame(data)
    msg = f"Failed to fetch GOES XRS data from {url}"
    raise RuntimeError(msg) from last_error


def _fetch_archive_goes_timeseries(start_time: datetime, end_time: datetime) -> pd.DataFrame:
    """
    Fetch science-quality 1-min GOES XRS data from the NOAA NCEI archive.
    """
    from sunpy.net import Fido
    from sunpy.net import attrs as a
    from sunpy.timeseries import TimeSeries

    results = Fido.search(
        a.Time(start_time, end_time),
        a.Instrument("XRS"),
        a.Resolution("avg1m"),
    )
    files = Fido.fetch(results)
    if not files:
        msg = f"No GOES XRS archive data found between {start_time} and {end_time}"
        raise DataNotReadyError(msg)
    satellite = int(results[0]["SatelliteNumber"][0])
    data = TimeSeries(files, concatenate=True).to_dataframe()
    data.index = data.index.tz_localize("UTC")
    goes_df = pd.concat(
        pd.DataFrame({"satellite": satellite, "flux": data[column], "energy": energy})
        for column, energy in GOES_ENERGY_BANDS.items()
    )
    # Drops NaN and the negative fill values the science files use for bad points.
    goes_df = goes_df[goes_df["flux"] > 0]
    return goes_df.astype({"satellite": int, "flux": float, "energy": str})


def fetch_goes_timeseries(end_time: datetime) -> pd.DataFrame:
    """
    Fetches the GOES XRS data for the 24 hours before ``end_time``.

    Windows the SWPC 7-day NRT JSON when it covers the requested time,
    otherwise falls back to the NOAA NCEI science archive via `sunpy`.

    Parameters
    ----------
    end_time : datetime.datetime
        End of the 24 hour window (timezone aware).

    Returns
    -------
    pandas.DataFrame
        GOES XRS data for the 24 hours before ``end_time``.

    Raises
    ------
    suntoday.DataNotReadyError
        If the requested window has no GOES XRS data yet.
    ValueError
        If ``end_time`` is timezone-naive.
    """
    if end_time.tzinfo is None:
        msg = "end_time must be timezone-aware"
        raise ValueError(msg)
    start_time = end_time - timedelta(days=1)
    if start_time >= datetime.now(UTC) - timedelta(days=7):
        goes_df = _reformat_goes_df(_read_goes_json(GOES_NRT_URL))
    else:
        goes_df = _fetch_archive_goes_timeseries(start_time, end_time)
    goes_df = goes_df[(goes_df.index > pd.Timestamp(start_time)) & (goes_df.index <= pd.Timestamp(end_time))]
    if goes_df.empty:
        msg = f"No GOES XRS data found between {start_time} and {end_time}"
        raise DataNotReadyError(msg)
    return goes_df
