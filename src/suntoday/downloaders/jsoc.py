"""
JSOC NRT downloaders: AIA and HMI FITS files, the AIA timeseries, and series
freshness helpers.

The data comes from the test series John creates on JSOC 2. The AWS VM
is whitelisted, and DRMS cannot authenticate against that server, so
plain requests are used throughout.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from parfive import Results
from requests.auth import HTTPBasicAuth

from suntoday import DataNotReadyError, logger
from suntoday.config import Settings
from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS, AIA_WAVELENGTHS
from suntoday.downloaders.adapt import find_latest_adapt_time
from suntoday.downloaders.downloader import create_downloader

__all__ = [
    "fetch_aia_fits",
    "fetch_aia_timeseries",
    "fetch_hmi_fits",
    "find_latest_jsoc_times",
    "find_latest_pfss_time",
    "get_aia_urls",
    "get_hmi_urls",
]


def _jsoc_auth(settings: Settings) -> HTTPBasicAuth | None:
    """
    Build the JSOC basic-auth from configured credentials.

    Authentication is only used for the test data series (``test_env``). The
    credentials are not shipped in the code: set ``SUNTODAY_JSOC_USER`` and
    ``SUNTODAY_JSOC_PASSWORD`` (e.g. in your ``.env`` or CI secrets).

    Parameters
    ----------
    settings : Settings
        The application settings.

    Returns
    -------
    requests.auth.HTTPBasicAuth | None
        The auth object when ``test_env`` is set, otherwise ``None``.

    Raises
    ------
    ValueError
        If ``test_env`` is set but the credentials are not configured.
    """
    if not settings.test_env:
        return None
    if not (settings.jsoc_user and settings.jsoc_password):
        msg = "test_env is set but SUNTODAY_JSOC_USER / SUNTODAY_JSOC_PASSWORD are not configured."
        raise ValueError(msg)
    logger.warning("Using test environment credentials for JSOC.")
    return HTTPBasicAuth(settings.jsoc_user, settings.jsoc_password)


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
    dict
        Parsed JSON response from the JSOC.

    Raises
    ------
    OSError
        If the network connection fails to the JSOC.
    suntoday.DataNotReadyError
        If the JSOC has no records for the requested time yet.
    ValueError
        If the JSOC response has missing required keys.
    """
    settings = Settings()
    auth = _jsoc_auth(settings)
    params = {
        "ds": query,
        "op": "rs_list",
        "key": keywords,
        "seg": segment,
    }
    response = requests.get(settings.jsoc_info_url, params=params, auth=auth, timeout=60)
    if response.status_code != 200:
        msg = f"JSOC request for {query!r} failed with {response.status_code} and {response.text}."
        raise OSError(msg)
    json_response = response.json()
    if not {"keywords", "segments"}.issubset(set(json_response.keys())):
        # A clean zero-count response means the JSOC has not exported the
        # requested time yet; anything else is a malformed response.
        if json_response.get("status") == 0 and json_response.get("count") == 0:
            msg = f"JSOC has no records yet for {query!r}."
            raise DataNotReadyError(msg)
        msg = f"JSOC request for {query!r} returned with no data but with {json_response}."
        raise ValueError(msg)
    return json_response


def get_aia_urls(requested_time: datetime, time_span: str = "60s") -> pd.DataFrame:
    """
    Gets the NRT AIA FITS URLS for the given time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Time wanted for the data.
    time_span : str
        Length of the query window, which runs forward from
        ``requested_time``. Default is "60s"; production calls pass "180s"
        (the `fetch_aia_fits` default) to catch 1600 and 1700, which have
        a slower cadence than the EUV channels.

    Returns
    -------
    pandas.DataFrame
        One row per wavelength found in the window, newest record kept.

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
    # Keep only channels the pipeline knows: the nine plotted wavelengths are
    # required, the FITS-only ones (e.g. hourly 4500) are a bonus when they
    # happen to fall inside the window.
    known_wavelengths = AIA_WAVELENGTHS + AIA_FITS_ONLY_WAVELENGTHS
    aia_urls = aia_urls[aia_urls["WAVELNTH"].astype(str).isin(known_wavelengths)]
    aia_urls = aia_urls.drop_duplicates(subset="WAVELNTH", keep="last")
    missing_wavelengths = set(AIA_WAVELENGTHS) - set(aia_urls["WAVELNTH"])
    if len(missing_wavelengths) != 0:
        msg = f"Missing AIA wavelengths {missing_wavelengths} for {query!r}, only have {set(aia_urls['WAVELNTH'])}"
        raise ValueError(msg)
    return aia_urls.astype({"WAVELNTH": str, "EXPTIME": float})


def get_hmi_urls(requested_time: datetime) -> pd.DataFrame:
    """
    Gets the NRT (m45s and Ic_45s) HMI FITS URL for the given time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Time wanted for the data.

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
    auth = _jsoc_auth(settings)
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
        if response.status_code != 200:
            msg = f"JSOC request for {params['ds']!r} failed with {response.status_code} and {response.text}."
            raise OSError(msg)
        json_response = response.json()
        if "keywords" not in json_response or "segments" not in json_response:
            msg = f"JSOC request for {params['ds']!r} returned with no data but with {json_response}."
            raise ValueError(msg)
        keywords = json_response["keywords"]
        segments = json_response["segments"]
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


def _get_latest_record_time(series: str, keyword: str, segment: str) -> datetime:
    """
    Get the time of the newest record in a series.

    Uses the DRMS ``$`` record-set specifier, which selects the last record
    of a series, so a single cheap jsoc_info query answers "how fresh is
    this series".

    Parameters
    ----------
    series : str
        Series name, e.g. ``aia_test.lev1p5``.
    keyword : str
        Time keyword to read, e.g. ``T_REC`` or ``DATE-OBS``.
    segment : str
        Segment to request (required by the jsoc_info endpoint).

    Returns
    -------
    datetime.datetime
        Time of the newest record, as UTC.

    Raises
    ------
    ValueError
        If the series returns no records.
    """
    settings = Settings()
    response = _get_urls(f"{series}[$]", keyword, segment)
    keywords = {ad["name"]: ad["values"] for ad in response["keywords"]}
    values = keywords.get(keyword, [])
    if not values:
        msg = f"No records returned for {series}[$]."
        raise ValueError(msg)
    value = str(values[-1])
    try:
        parsed = datetime.strptime(value, settings.jsoc_str_fmt).replace(tzinfo=UTC)
    except ValueError:
        parsed = pd.to_datetime(value, format="mixed").to_pydatetime()
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def find_latest_jsoc_times() -> tuple[datetime, datetime]:
    """
    Find the most recent times the AIA and HMI NRT series have data for.

    AIA typically lags real time by only a few minutes while the HMI NRT
    series can lag by an hour or more, so the freshest usable time is found
    per instrument instead of holding the AIA images back to the HMI lag.

    Returns
    -------
    tuple of datetime.datetime
        ``(aia_time, hmi_time)``: the newest available time per instrument,
        with AIA stepped back three minutes so its forward query window
        lands inside the data.
    """
    # The AIA query window runs forward from the requested time, so step
    # back three minutes to have the full set of wavelengths land inside it.
    aia_time = _get_latest_record_time("aia_test.lev1p5", "DATE-OBS", "image_lev1p5") - timedelta(minutes=3)
    # Both HMI series are fetched at one time, so the older one limits.
    hmi_time = min(
        _get_latest_record_time("lm_jps.m45s_nrt", "T_REC", "magnetogram"),
        _get_latest_record_time("lm_jps.Ic_45s", "T_REC", "continuum"),
    )
    logger.info(f"Latest JSOC data: AIA at {aia_time}, HMI at {hmi_time}")
    return aia_time, hmi_time


def find_latest_pfss_time() -> datetime:
    """
    Find the anchor time for the PFSS job.

    The PFSS images must all carry the same timestamp as the field lines,
    so the anchor is the minimum of the latest AIA, HMI, and ADAPT times. ADAPT
    updates every 2 hours, so the record nearest the anchor (either side) is
    then at most an hour away.

    Returns
    -------
    datetime.datetime
        The newest time every PFSS data source has data for.
    """
    aia_time, hmi_time = find_latest_jsoc_times()
    adapt_time = find_latest_adapt_time()
    anchor = min(aia_time, hmi_time, adapt_time)
    logger.info(f"PFSS anchor time: {anchor} (AIA {aia_time}, HMI {hmi_time}, ADAPT {adapt_time})")
    return anchor


def fetch_aia_timeseries(end_time: datetime) -> pd.DataFrame:
    """
    Fetches the NRT AIA data mean for the previous 24 hours.

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
    auth = _jsoc_auth(settings)
    params = {
        # Sampling does not work on this series.
        "ds": f"aia_test.lev1p5[{start_time.strftime(settings.jsoc_str_fmt)}-{end_time.strftime(settings.jsoc_str_fmt)}]",
        "op": "rs_list",
        "key": "DATE-OBS,WAVELNTH,DATAMEAN,QUALITY,EXPTIME",
    }
    response = requests.get(settings.jsoc_info_url, params=params, auth=auth, timeout=60)
    if response.status_code != 200:
        msg = f"JSOC request for {params['ds']!r} failed with {response.status_code} and {response.text}."
        raise OSError(msg)
    keywords = response.json()["keywords"]
    if len(keywords[0]["values"]) == 0:
        msg = f"No data found for {params['ds']}."
        raise ValueError(msg)
    keywords = {ad["name"]: ad["values"] for ad in keywords}
    aia_timeseries = pd.DataFrame.from_dict(keywords)
    aia_timeseries = aia_timeseries.set_index("DATE-OBS")
    aia_timeseries.index = pd.to_datetime(aia_timeseries.index, format="mixed")
    aia_timeseries = aia_timeseries.astype({"WAVELNTH": str, "DATAMEAN": float, "EXPTIME": float})
    # The series interleaves hourly 4500 A planning frames; they are never
    # plotted and only pollute the saved txt with ~2500 DN spikes.
    return aia_timeseries[aia_timeseries["WAVELNTH"].isin(AIA_WAVELENGTHS)]


def fetch_aia_fits(requested_time: datetime, time_span: str = "180s", *, save_directory: Path) -> Results:
    """
    Download AIA fits files for a given time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Datetime to download AIA fits files for.
    time_span : str
        Time span to download files for.
        Defaults to "180s".
    save_directory : Path
        Directory to save the files to.

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
    logger.info(f"Downloading {len(aia_info)} AIA FITS files for {requested_time}")
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


def fetch_hmi_fits(requested_time: datetime, save_directory: Path) -> Results:
    """
    Download HMI FITS files for a given time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Datetime to download HMI FITS files for.
    save_directory : Path
        Directory to save the files to.

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
    logger.info(f"Downloading {len(hmi_info)} HMI FITS files for {requested_time}")
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
