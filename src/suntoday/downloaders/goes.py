"""
Provides a GOES NRT downloader for the 1 day JSON files.
"""

import time

import pandas as pd
import requests

__all__ = ["fetch_goes_timeseries"]

GOES_PRIMARY_URL = "https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json"
GOES_SECONDARY_URL = "https://services.swpc.noaa.gov/json/goes/secondary/xrays-1-day.json"
GOES_RETRIES = 2
GOES_TIMEOUT = 60
GOES_RETRY_DELAY = 5


def _reformat_goes_df(goes_df: pd.DataFrame) -> pd.DataFrame:
    """
    Reformats the GOES DataFrame to have a proper datetime index and correct
    data types.

    Parameters
    ----------
    goes_df : pandas.DataFrame
        The GOES DataFrame to reformat.

    Returns
    -------
    pandas.DataFrame
        The reformatted GOES DataFrame.
    """
    goes_df = goes_df.set_index("time_tag")
    goes_df.index = pd.to_datetime(goes_df.index)
    goes_df = goes_df.drop(columns=["observed_flux", "electron_correction", "electron_contaminaton"])
    return goes_df.astype({"satellite": int, "flux": float, "energy": str})


def _read_goes_json(url: str) -> pd.DataFrame:
    """
    Fetches a GOES JSON file into a DataFrame, retrying transient failures.

    Parameters
    ----------
    url : str
        URL of the GOES JSON file.

    Returns
    -------
    pandas.DataFrame
        The raw GOES data.

    Raises
    ------
    RuntimeError
        If the download still fails after all retries.
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


def fetch_goes_timeseries() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetches the GOES XRS JSON data for the previous 24 hours.

    Returns
    -------
    pandas.DataFrame, pandas.DataFrame
        GOES XRS data for the previous 24 hours for the primary and secondary satellites.
    """
    goes_primary = _read_goes_json(GOES_PRIMARY_URL)
    goes_secondary = _read_goes_json(GOES_SECONDARY_URL)
    goes_primary = _reformat_goes_df(goes_primary)
    goes_secondary = _reformat_goes_df(goes_secondary)
    return goes_primary, goes_secondary
