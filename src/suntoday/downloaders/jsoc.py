"""
JSOC downloads: AIA and HMI FITS files, the AIA timeseries, and the newest time
each series has data for.

The data comes from the test series John creates on JSOC 2. The AWS VM
is whitelisted, and DRMS cannot authenticate against that server, so
plain requests are used throughout.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from astropy.io import fits
from astropy.time import Time
from parfive import Results
from requests.auth import HTTPBasicAuth

from suntoday import DataNotReadyError, logger
from suntoday.config import Settings
from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS, AIA_WAVELENGTHS
from suntoday.downloaders.downloader import create_downloader, format_download_errors
from suntoday.utils import atomic_save

__all__ = [
    "fetch_aia_fits",
    "fetch_aia_timeseries",
    "fetch_hmi_fits",
    "fetch_hmi_synoptic_fits",
    "find_hmi_synoptic_time",
    "find_latest_jsoc_times",
    "find_latest_pfss_time",
    "get_aia_urls",
    "get_hmi_urls",
]

HMI_SYNOPTIC_SERIES = "hmi.Mrdailysynframe_720s_nrt"
_SYNOPTIC_KEYS = "T_REC,T_OBS,CRVAL1,CRVAL2,CRPIX1,CRPIX2,CDELT1"


def _jsoc_auth(settings: Settings) -> HTTPBasicAuth | None:
    """
    Return basic auth for the test series when ``test_env`` is set, else None.
    """
    if not settings.test_env:
        return None
    if not (settings.jsoc_user and settings.jsoc_password):
        msg = "test_env is set but SUNTODAY_JSOC_USER / SUNTODAY_JSOC_PASSWORD are not configured."
        raise ValueError(msg)
    logger.warning("Using test environment credentials for JSOC.")
    return HTTPBasicAuth(settings.jsoc_user, settings.jsoc_password)


def _format_jsoc_time(value: datetime) -> str:
    """
    Format a UTC datetime as the equivalent JSOC TAI record time.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return Time(value.astimezone(UTC), scale="utc").tai.strftime(Settings().jsoc_str_fmt)


def _parse_jsoc_time(value: str) -> datetime:
    """
    Parse JSOC TAI records and ISO observation times as UTC.
    """
    value = str(value)
    if value.endswith("_TAI"):
        return Time.strptime(value, Settings().jsoc_str_fmt, scale="tai").utc.to_datetime(timezone=UTC)
    parsed = pd.to_datetime(value, format="mixed", utc=True).to_pydatetime()
    return parsed.astimezone(UTC)


def _get_urls(query: str, keywords: str, segment: str | None = None) -> dict:
    """
    Query jsoc_info for a record set.

    Returns
    -------
    dict
        The parsed JSON response.

    Raises
    ------
    OSError
        If the request fails.
    suntoday.DataNotReadyError
        If the JSOC has no records for the query yet.
    ValueError
        If the response is malformed.
    """
    settings = Settings()
    auth = _jsoc_auth(settings)
    params = {
        "ds": query,
        "op": "rs_list",
        "key": keywords,
    }
    if segment is not None:
        params["seg"] = segment
    response = requests.get(settings.jsoc_info_url, params=params, auth=auth, timeout=60)
    if response.status_code != 200:
        msg = f"JSOC request for {query!r} failed with {response.status_code} and {response.text}."
        raise OSError(msg)
    json_response = response.json()
    # A clean zero-count response means the JSOC has not exported the
    # requested time yet; anything else is a malformed response.
    if json_response.get("status") == 0 and json_response.get("count") == 0:
        msg = f"JSOC has no records yet for {query!r}."
        raise DataNotReadyError(msg)
    if not {"keywords", "segments"}.issubset(set(json_response.keys())):
        msg = f"JSOC request for {query!r} returned with no data but with {json_response}."
        raise ValueError(msg)
    return json_response


def get_aia_urls(requested_time: datetime, time_span: str = "60s") -> pd.DataFrame:
    """
    Find the newest AIA FITS file of each channel in a window after a time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Start of the window.
    time_span : str
        Length of the window. Production passes "180s" (the `fetch_aia_fits`
        default) to catch 1600 and 1700, whose cadence is slower than the
        EUV channels'.

    Returns
    -------
    pandas.DataFrame
        One row per wavelength with its exposure time and FITS URL, indexed
        by observation time.

    Raises
    ------
    ValueError
        If the response has no data, or a plotted wavelength is missing.
    """
    settings = Settings()
    query = f"aia_test.lev1p5[{_format_jsoc_time(requested_time)}/{time_span}]"
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
    aia_urls.index = pd.to_datetime(aia_urls.index, format="mixed", utc=True)
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
    Find the HMI magnetogram and continuum FITS files for a time.

    Returns
    -------
    pandas.DataFrame
        One row per measurement (named in ``WAVELNTH``) with its ``URL``,
        indexed by record time.

    Raises
    ------
    ValueError
        If a series returns no data.
    """
    rows = []
    for series, segment in [("lm_jps.m45s_nrt", "magnetogram"), ("lm_jps.Ic_45s", "continuum")]:
        query = f"{series}[{_format_jsoc_time(requested_time)}]"
        response = _get_urls(query, "T_REC", segment)
        times = response["keywords"][0]["values"]
        if not times:
            msg = f"No data found for {query}."
            raise ValueError(msg)
        # T_REC is the only keyword and the segment the only one requested.
        url = f"{Settings().jsoc_base_url}{response['segments'][0]['values'][0]}"
        rows.append({"T_REC": _parse_jsoc_time(times[0]), "WAVELNTH": segment, "URL": url})
    return pd.DataFrame(rows).set_index("T_REC")


def _get_latest_record_time(series: str, keyword: str, segment: str) -> datetime:
    """
    Return the time of the newest record in a series, as UTC.
    """
    # `$` selects the last record of a series, so one cheap query answers
    # how fresh it is.
    response = _get_urls(f"{series}[$]", keyword, segment)
    keywords = {ad["name"]: ad["values"] for ad in response["keywords"]}
    values = keywords.get(keyword, [])
    if not values:
        msg = f"No records returned for {series}[$]."
        raise ValueError(msg)
    value = str(values[-1])
    return _parse_jsoc_time(value)


def find_latest_jsoc_times() -> tuple[datetime, datetime]:
    """
    Find the newest times the AIA and HMI series have data for.

    AIA lags real time by a few minutes and HMI by an hour or more, so each
    instrument gets its own time instead of AIA being held back to HMI.

    Returns
    -------
    tuple of datetime.datetime
        ``(aia_time, hmi_time)``. AIA is stepped back three minutes so its
        forward query window lands inside the data.
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
    Return the newest time both AIA and HMI have data for, the PFSS anchor.
    """
    aia_time, hmi_time = find_latest_jsoc_times()
    anchor = min(aia_time, hmi_time)
    logger.info(f"PFSS anchor time: {anchor} (AIA {aia_time}, HMI {hmi_time})")
    return anchor


def _get_hmi_synoptic_record(requested_time: datetime) -> tuple[dict, str]:
    """
    Select the newest usable HMI radial boundary at or before a time.

    The search goes back two days: enough to ride out a missed update
    without quietly using a much older boundary. The NRT series currently
    has hourly records.

    Returns
    -------
    tuple of dict and str
        The record's keywords and the path of its FITS segment.

    Raises
    ------
    DataNotReadyError
        If no boundary in the window can be downloaded.
    """
    start = _format_jsoc_time(requested_time - timedelta(days=2))
    end = _format_jsoc_time(requested_time)
    response = _get_urls(f"{HMI_SYNOPTIC_SERIES}[{start}-{end}]", _SYNOPTIC_KEYS, "data")
    keywords = {item["name"]: item["values"] for item in response["keywords"]}
    segments = {item["name"]: item["values"] for item in response["segments"]}
    # Records without a data file or with MISSING keywords are unusable.
    records = [
        (metadata, path)
        for metadata, path in zip(pd.DataFrame(keywords).to_dict("records"), segments["data"], strict=True)
        if path.startswith("/") and "MISSING" not in metadata.values()
    ]
    if not records:
        msg = f"No available HMI synoptic frame in the two days before {requested_time}."
        raise DataNotReadyError(msg)
    return max(records, key=lambda record: _parse_jsoc_time(record[0]["T_REC"]))


def find_hmi_synoptic_time(requested_time: datetime) -> datetime:
    """
    Return the selected HMI boundary record time in UTC.
    """
    metadata, _ = _get_hmi_synoptic_record(requested_time)
    return _parse_jsoc_time(metadata["T_REC"])


def fetch_hmi_synoptic_fits(requested_time: datetime, save_directory: Path) -> Path:
    """
    Download the HMI radial synoptic frame at or before a time.

    A JSOC segment holds only the image array, so the record's coordinate
    and time keywords are written into the FITS header. A file already in
    ``save_directory`` is reused.

    Returns
    -------
    pathlib.Path
        The FITS file.

    Raises
    ------
    OSError
        If the download fails.
    """
    metadata, segment = _get_hmi_synoptic_record(requested_time)
    epoch = _parse_jsoc_time(metadata["T_REC"])
    destination = save_directory / f"{epoch:%Y%m%d_%H%M%S}_synoptic.fits"
    if destination.exists():
        return destination
    save_directory.mkdir(parents=True, exist_ok=True)
    with atomic_save(destination) as staging:
        downloader = create_downloader()
        downloader.enqueue_file(f"{Settings().jsoc_base_url}{segment}", path=save_directory, filename=staging.name)
        files = downloader.download()
        if files.errors:
            msg = f"Failed to download:\n{format_download_errors(files.errors)}"
            raise OSError(msg)
        with fits.open(staging, mode="update", memmap=False) as hdul:
            for key, value in metadata.items():
                hdul[0].header[key] = value if key.startswith("T_") else float(value)
            hdul[0].header["BUNIT"] = "G"
    return destination


def fetch_aia_timeseries(end_time: datetime) -> pd.DataFrame:
    """
    Fetch the AIA mean brightness of every frame in the 24 hours before a time.

    Returns
    -------
    pandas.DataFrame
        ``WAVELNTH``, ``DATAMEAN``, ``QUALITY`` and ``EXPTIME``, indexed by
        observation time.

    Raises
    ------
    ValueError
        If no data is returned.
    """
    start_time = end_time - timedelta(days=1)
    query = f"aia_test.lev1p5[{_format_jsoc_time(start_time)}-{_format_jsoc_time(end_time)}]"
    response = _get_urls(query, "DATE-OBS,WAVELNTH,DATAMEAN,QUALITY,EXPTIME")
    keywords = response["keywords"]
    if len(keywords[0]["values"]) == 0:
        msg = f"No data found for {query}."
        raise ValueError(msg)
    keywords = {ad["name"]: ad["values"] for ad in keywords}
    aia_timeseries = pd.DataFrame.from_dict(keywords)
    aia_timeseries = aia_timeseries.set_index("DATE-OBS")
    aia_timeseries.index = pd.to_datetime(aia_timeseries.index, format="mixed", utc=True)
    aia_timeseries = aia_timeseries.astype({"WAVELNTH": str, "DATAMEAN": float, "EXPTIME": float})
    # The series interleaves hourly 4500 A planning frames; they are never
    # plotted and only pollute the saved txt with ~2500 DN spikes.
    return aia_timeseries[aia_timeseries["WAVELNTH"].isin(AIA_WAVELENGTHS)]


def _download_fits(info: pd.DataFrame, url_column: str, save_directory: Path) -> Results:
    """
    Download one FITS file per row, named by its index time and ``WAVELNTH``.
    """
    downloader = create_downloader()
    for idx, row in info.iterrows():
        downloader.enqueue_file(
            row[url_column],
            path=save_directory,
            filename=f"{idx.strftime('%Y%m%d_%H%M%S')}_{row['WAVELNTH']}.fits",
        )
    files = downloader.download()
    if files.errors:
        msg = f"Failed to download:\n{format_download_errors(files.errors)}"
        raise OSError(msg)
    return files


def fetch_aia_fits(requested_time: datetime, time_span: str = "180s", *, save_directory: Path) -> Results:
    """
    Download the AIA FITS files for the window starting at a time.
    """
    aia_info = get_aia_urls(requested_time, time_span=time_span)
    logger.info(f"Downloading {len(aia_info)} AIA FITS files for {requested_time}")
    return _download_fits(aia_info, "image_lev1p5", save_directory)


def fetch_hmi_fits(requested_time: datetime, save_directory: Path) -> Results:
    """
    Download the HMI magnetogram and continuum FITS files for a time.
    """
    hmi_info = get_hmi_urls(requested_time)
    logger.info(f"Downloading {len(hmi_info)} HMI FITS files for {requested_time}")
    return _download_fits(hmi_info, "URL", save_directory)
