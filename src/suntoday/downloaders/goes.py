"""
Provides a GOES NRT downloader for the 1 day JSON files.
"""

import pandas as pd

__all__ = ["fetch_goes_timeseries"]


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
    return goes_df.astype({"satellite": int, "flux": float, "energy": str}, copy=False)


def fetch_goes_timeseries() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetches the GOES XRS JSON data for the previous 24 hours.

    Returns
    -------
    pandas.DataFrame, pandas.DataFrame
        GOES XRS data for the previous 24 hours for the primary and secondary satellites.
    """
    goes_primary = pd.read_json("https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json")
    goes_secondary = pd.read_json("https://services.swpc.noaa.gov/json/goes/secondary/xrays-1-day.json")
    goes_primary = _reformat_goes_df(goes_primary)
    goes_secondary = _reformat_goes_df(goes_secondary)
    return goes_primary, goes_secondary
