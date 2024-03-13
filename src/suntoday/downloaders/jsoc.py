"""
Provides a JSOC NRT downloader for the AIA level 1.5 series.
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from parfive import Results
from requests.auth import HTTPBasicAuth

from suntoday import logger
from suntoday.config import Settings
from suntoday.constants import AIA_WAVELENGTHS
from suntoday.downloaders.downloader import create_downloader

__all__ = ["fetch_aia_fits", "fetch_aia_timeseries", "fetch_hmi_fits", "get_aia_urls", "get_hmi_urls"]


def _get_urls(query: str, keywords: str, segment: str) -> dict:
    """
    For a given query, keywords and segment query the JSOC.

    Parameters
    ----------
    query : str
        Query to run.
    keywords : str
        Keywords to return.
    segment : str
        Segment to return.

    Returns
    -------
    requests.Response
        Response from the JSOC.

    Raises
    ------
    OSError
        If the network connection fails to the JSOC.
    ValueError
        If the JSOC response has missing required keys.
    """
    settings = Settings()
    auth = None
    if settings.test_env:
        logger.warning("Using test environment credentials for JSOC.")
        auth = HTTPBasicAuth(settings.jsoc_user, settings.jsoc_password)
    params = {
        "ds": query,
        "op": "rs_list",
        "key": keywords,
        "seg": segment,
    }
    response = requests.get(settings.jsoc_info_url, params=params, auth=auth, timeout=60, verify=False)  # NOQA: S501
    logger.debug(f"JSOC request for {query} with params {params} returned {response.status_code}.")
    logger.debug(f"URL: {response.url}")
    if response.status_code != 200:
        msg = f"JSOC request failed with {response.status_code} and {response.text}."
        raise OSError(msg)
    json_response = response.json()
    if not {"keywords", "segments"}.issubset(set(json_response.keys())):
        msg = f"JSOC request returned with no data but with {json_response}."
        raise ValueError(msg)
    return json_response


def get_aia_urls(requested_time: datetime, time_span: str = "36s") -> pd.DataFrame:
    """
    Gets the NRT AIA FITS URLS for the given time.

    This uses the test data that John creates on JSOC 2.
    The AWS VM has been whitelisted.

    I can not see how to auth with the JSOC2 server using DRMS, so I use requests to get the data.

    Parameters
    ----------
    requested_time : datetime.datetime
        Time wanted for the data.
    time_span : str
        Time span for the data. Default is "36s".
        We go back 36 seconds to capture 1600 and 1700, but we get repeats of the other wavelengths.

    Returns
    -------
    pandas.DataFrame
        AIA data for the previous ``time_span`` hours.

    Raises
    ------
    ValueError
        If the JSOC response has no data.
        If the JSOC response has missing wavelengths.
    """
    settings = Settings()
    query = f"aia_test.lev1p5[{requested_time.strftime(settings.jsoc_str_fmt)}/{time_span}]"
    response = _get_urls(query, "DATE-OBS,WAVELNTH,EXPTIME", "image_lev1p5")
    keywords = response["keywords"]
    segments = response["segments"]
    if len(keywords[0]["values"]) == 0:
        msg = f"No data found for {query}."
        raise ValueError(msg)
    keywords = {ad["name"]: ad["values"] for ad in keywords}
    segments = {ad["name"]: ad["values"] for ad in segments}
    segments["image_lev1p5"] = [f"{settings.jsoc_base_url}{value}" for value in segments["image_lev1p5"]]
    aia_urls = pd.DataFrame.from_dict(keywords | segments)
    aia_urls = aia_urls.set_index("DATE-OBS")
    aia_urls.index = pd.to_datetime(aia_urls.index, format="mixed")
    aia_urls = aia_urls.drop_duplicates(subset="WAVELNTH", keep="last")
    missing_wavelengths = set(AIA_WAVELENGTHS) - set(aia_urls["WAVELNTH"])
    if len(missing_wavelengths) != 0:
        msg = f"Missing AIA wavelengths {missing_wavelengths}, only have {set(aia_urls['WAVELNTH'])}"
        raise ValueError(msg)
    return aia_urls.astype({"WAVELNTH": str, "EXPTIME": float})


def get_hmi_urls(requested_time: datetime) -> pd.DataFrame:
    """
    Gets the NRT (m45s and Ic_45s) HMI FITS URL for the given time.

    This uses the test data that John creates on JSOC 2.
    The AWS VM has been whitelisted.
    I can not see how to auth with the JSOC2 server using DRMS, so I use requests to get the data.

    Returns
    -------
    pandas.DataFrame
        HMI data.

    Raises
    ------
    OSError
        If the network connection fails to the JSOC.
    ValueError
        If no data is returned.
    """
    settings = Settings()
    auth = None
    if settings.test_env:
        logger.warning("Using test environment credentials for JSOC.")
        auth = HTTPBasicAuth(settings.jsoc_user, settings.jsoc_password)
    keyword_store = {"T_REC": [], "WAVELNTH": []}
    segment_store = {"URL": []}
    for query, segment in [("lm_jps.m45s_nrt[{}]", "magnetogram"), ("lm_jps.Ic_45s[{}]", "continuum")]:
        params = {
            "ds": query.format(requested_time.strftime(settings.jsoc_str_fmt)),
            "op": "rs_list",
            "key": "T_REC",
            "seg": segment,
        }
        response = requests.get(settings.jsoc_info_url, params=params, auth=auth, timeout=60)
        logger.debug(f"JSOC request for {query} with params {params} returned {response.status_code}.")
        logger.debug(f"URL: {response.url}")
        if response.status_code != 200:
            msg = f"JSOC request failed with {response.status_code} and {response.text}."
            raise OSError(msg)
        keywords = response.json()["keywords"]
        segments = response.json()["segments"]
        if len(keywords[0]["values"]) == 0:
            msg = f"No data found for {params['ds']}."
            raise ValueError(msg)
        keywords = {ad["name"]: ad["values"] for ad in keywords}
        segments = {ad["name"]: ad["values"] for ad in segments}
        segments[segment] = [f"{settings.jsoc_base_url}{value}" for value in segments[segment]]
        keyword_store["T_REC"].extend(keywords["T_REC"])
        keyword_store["WAVELNTH"].append(segment)
        segment_store["URL"].extend(segments[segment])
    keyword_store["T_REC"] = [
        datetime.strptime(str(value), settings.jsoc_str_fmt).astimezone() for value in keyword_store["T_REC"]
    ]
    hmi_urls = pd.DataFrame.from_dict(keyword_store | segment_store)
    hmi_urls = hmi_urls.set_index("T_REC")
    hmi_urls.index = pd.to_datetime(hmi_urls.index, format="mixed")
    return hmi_urls


def fetch_aia_timeseries(end_time: datetime) -> pd.DataFrame:
    """
    Fetches the NRT AIA data mean for the previous 24 hours.

    This uses the test data that John creates on JSOC 2.

    Parameters
    ----------
    end_time : datetime.datetime
        End time for the data.

    Returns
    -------
    pandas.DataFrame
        AIA data for the previous 24 hours.

    Raises
    ------
    OSError
        If the network connection fails to the JSOC.
    ValueError
        If no data is returned.
    """
    settings = Settings()
    start_time = end_time - timedelta(days=1)
    auth = None
    if settings.test_env:
        logger.warning("Using test environment credentials for JSOC.")
        auth = HTTPBasicAuth(settings.jsoc_user, settings.jsoc_password)
    params = {
        # Sampling does not work on this series.
        "ds": f"aia_test.lev1p5[{start_time.strftime(settings.jsoc_str_fmt)}-{end_time.strftime(settings.jsoc_str_fmt)}]",
        "op": "rs_list",
        "key": "DATE-OBS,WAVELNTH,DATAMEAN,QUALITY,EXPTIME",
    }
    response = requests.get(settings.jsoc_info_url, params=params, auth=auth, timeout=60, verify=False)  # NOQA: S501
    logger.debug(f"JSOC request for {settings.jsoc_info_url} with params {params} returned {response.status_code}.")
    logger.debug(f"URL: {response.url}")
    if response.status_code != 200:
        msg = f"JSOC request failed with {response.status_code} and {response.text}."
        raise OSError(msg)
    keywords = response.json()["keywords"]
    if len(keywords[0]["values"]) == 0:
        msg = f"No data found for {params['ds']}."
        raise ValueError(msg)
    keywords = {ad["name"]: ad["values"] for ad in keywords}
    aia_timeseries = pd.DataFrame.from_dict(keywords)
    aia_timeseries = aia_timeseries.set_index("DATE-OBS")
    aia_timeseries.index = pd.to_datetime(aia_timeseries.index, format="mixed")
    # Replace bad quality data with NaNs, good data is 0x40000000
    aia_timeseries.loc[aia_timeseries["QUALITY"] != "0x40000000", ["DATAMEAN"]] = np.nan
    return aia_timeseries.astype({"WAVELNTH": str, "DATAMEAN": float, "EXPTIME": float})


def fetch_aia_fits(requested_time: datetime, time_span: str = "36s", save_directory: Path = Path("./")) -> Results:
    """
    Download AIA fits files for a given time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Datetime to download AIA fits files for.
    time_span : str
        Time span to download files for.
        Defaults to "36s".
    save_directory : Path, optional
        Directory to save the files to.
        Defaults to ``Path("./")`` which saves to current directory.

    Returns
    -------
    parfive.Results
        Results object from parfive.Downloader.

    Raises
    ------
    OSError
        If parfive fails to download any files.
    """
    aia_info = get_aia_urls(requested_time, time_span=time_span)
    downloader = create_downloader()
    for idx, row in aia_info.iterrows():
        downloader.enqueue_file(
            row["image_lev1p5"],
            path=save_directory,
            filename=f"{idx.strftime('%Y%m%d_%H%M%S')}_{row['WAVELNTH']}.fits",
        )
    files = downloader.download()
    if files.errors:
        msg = f"Failed to download {files.errors}."
        raise OSError(msg)
    return files


def fetch_hmi_fits(requested_time: datetime, save_directory: Path = Path("./")) -> Results:
    """
    Download HMI FITS files for a given time.

    Parameters
    ----------
    save_directory : Path, optional
        Directory to save the files to.
        Defaults to ``Path("./")`` which saves to current directory.

    Returns
    -------
    parfive.Results
        Results object from parfive.Downloader.

    Raises
    ------
    OSError
        If parfive fails to download any files.
    """
    hmi_info = get_hmi_urls(requested_time)
    downloader = create_downloader()
    for idx, row in hmi_info.iterrows():
        downloader.enqueue_file(
            row["URL"],
            path=save_directory,
            filename=f"{idx.strftime('%Y%m%d_%H%M%S')}_{row['WAVELNTH']}.fits",
        )
    files = downloader.download()
    if files.errors:
        msg = f"Failed to download {files.errors}."
        raise OSError(msg)
    return files
