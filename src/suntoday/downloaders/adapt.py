"""
Downloader for NSO ADAPT synchronic magnetograms.

ADAPT publishes a fresh full-Sun boundary map every 2 hours, built with
an actual flux-transport model that evolves older/far-side data forward
to a common instant, rather than a JSOC-style time-composite that just
freezes older longitude strips as they rotate out of view.
"""

import os
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from operator import itemgetter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import requests

from suntoday import DataNotReadyError

__all__ = ["fetch_adapt_fits", "find_latest_adapt_time", "find_nearest_adapt_time"]

_ADAPT_ROOT = "https://gong.nso.edu/adapt/maps/gong"
_ADAPT_FTP_ROOT = "ftp://gong2.nso.edu/adapt/maps/gong"
_ADAPT_FILE = re.compile(r'href="(adapt40[^"/]*_(\d{12})_[^"/]*\.fts\.gz)"')
_ADAPT_FTP_FILE = re.compile(r"\b(adapt40\S*_(\d{12})_\S*\.fts\.gz)\b")
_NEAREST_WINDOW = timedelta(hours=4)
_TIMEOUT = 30
_AdaptRow = tuple[datetime, str]


# Scheduled jobs run in fresh spawned processes, so caching each month
# listing for the process lifetime is enough.
_month_cache: dict[date, list[_AdaptRow]] = {}


def _as_utc(time: datetime) -> datetime:
    return time.replace(tzinfo=UTC) if time.tzinfo is None else time.astimezone(UTC)


def _clear_search_cache() -> None:
    _month_cache.clear()


def _month_rows(month: date) -> list[_AdaptRow]:
    """
    All public GONG-input ADAPT maps in one month's directory listing.
    """
    if month not in _month_cache:
        pattern = f"adapt40*_{month:%Y%m}*.fts.gz"
        listing_url = f"{_ADAPT_ROOT}/{month.year}/?{urlencode({'P': pattern})}"
        root = _ADAPT_ROOT
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            response = requests.get(listing_url, timeout=_TIMEOUT)
            if response.status_code == HTTPStatus.NOT_FOUND:
                # NSO creates year directories lazily, so a window crossing
                # Jan 1 must treat the missing new year as empty, not an error.
                listing = ""
            else:
                response.raise_for_status()
                listing = response.text
            matches = _ADAPT_FILE.findall(listing)
        except requests.RequestException:
            root = _ADAPT_FTP_ROOT
            with urlopen(f"{root}/{month.year}/", timeout=_TIMEOUT) as response:  # ruff: ignore[suspicious-url-open-usage]
                matches = _ADAPT_FTP_FILE.findall(response.read().decode())
        _month_cache[month] = sorted(
            (datetime.strptime(timestamp, "%Y%m%d%H%M").replace(tzinfo=UTC), f"{root}/{month.year}/{filename}")
            for filename, timestamp in matches
            if timestamp.startswith(f"{month:%Y%m}")
        )
    return _month_cache[month]


def _adapt_rows(start: datetime, end: datetime) -> list[_AdaptRow]:
    """
    Query for the public GONG-input ADAPT maps in a time range.

    Ask NSO's Apache index to return one month at a time; month listings are
    cached so overlapping searches reuse them.

    Returns
    -------
    list[tuple[datetime.datetime, str]]
        The matching rows, oldest first.

    Raises
    ------
    suntoday.DataNotReadyError
        If no map is found in the range.
    """
    start = _as_utc(start)
    end = _as_utc(end)
    rows = []
    month = start.date().replace(day=1)
    last_month = end.date().replace(day=1)
    while month <= last_month:
        rows.extend(row for row in _month_rows(month) if start <= _row_time(row) <= end)
        month = (month + timedelta(days=32)).replace(day=1)
    if not rows:
        msg = f"No ADAPT map found between {start!r} and {end!r}."
        raise DataNotReadyError(msg)
    return rows


_row_time = itemgetter(0)


def _latest_adapt_row(before: datetime, window: timedelta = timedelta(days=7)) -> _AdaptRow:
    """
    The newest public GONG-input ADAPT map at or before a time.

    The window is a week, not hours: ADAPT generates a map every 2 hours
    but the public archive backfills with a publication lag that has been
    observed to exceed 2 days. The search also covers the following nearest-map
    window so the scheduled job can reuse the same NSO directory scrape.

    Returns
    -------
    tuple[datetime.datetime, str]
        The newest matching row.

    Raises
    ------
    suntoday.DataNotReadyError
        If no map is found at or before the requested time.
    """
    before = _as_utc(before)
    rows = [row for row in _adapt_rows(before - window, before + _NEAREST_WINDOW) if _row_time(row) <= before]
    if not rows:
        msg = f"No ADAPT map found between {before - window!r} and {before!r}."
        raise DataNotReadyError(msg)
    return rows[-1]


def _nearest_adapt_row(time: datetime, window: timedelta = _NEAREST_WINDOW) -> _AdaptRow:
    """
    The public GONG-input ADAPT map nearest to a time, either side.

    Looking on both sides matters: the PFSS anchor time can sit minutes
    before a fresh ADAPT epoch (e.g. HMI at 11:59 with ADAPT at 12:00),
    and only-before selection would pick the 2-hour-older map instead.

    Returns
    -------
    tuple[datetime.datetime, str]
        The row whose start time is closest to ``time``.
    """
    time = _as_utc(time)
    return min(_adapt_rows(time - window, time + window), key=lambda row: abs(_row_time(row) - time))


def fetch_adapt_fits(requested_time: datetime, save_directory: Path) -> Path:
    """
    Download the public GONG-input ADAPT magnetogram nearest to a time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Time to find the nearest ADAPT map for, on either side. ADAPT
        publishes every 2 hours, so the offset is at most ~1 hour. Naive
        values are interpreted as UTC.
    save_directory : pathlib.Path
        Directory to save the downloaded file to.

    Returns
    -------
    pathlib.Path
        Path to the downloaded ``.fts.gz`` file. The primary HDU's data is
        a ``(12, 180, 360)`` cube, one slice per model realization; see
        `suntoday.maps.create_adapt_map`.

    Raises
    ------
    OSError
        If the file cannot be downloaded.
    """
    url = _nearest_adapt_row(requested_time)[1]
    save_directory.mkdir(parents=True, exist_ok=True)
    destination = save_directory / url.rsplit("/", 1)[-1]
    if destination.exists():
        return destination
    # A pid-unique partial file keeps overlapping runs from interleaving
    # writes; the atomic replace means the last finished download wins whole.
    partial = destination.with_name(f"{destination.name}.{os.getpid()}.part")
    try:  # ruff: ignore[too-many-statements-in-try-clause]
        if url.startswith("ftp://"):
            with urlopen(url, timeout=_TIMEOUT) as response, partial.open("wb") as file:  # ruff: ignore[suspicious-url-open-usage]
                shutil.copyfileobj(response, file)
        else:
            with requests.get(url, timeout=_TIMEOUT, stream=True) as response, partial.open("wb") as file:
                response.raise_for_status()
                shutil.copyfileobj(response.raw, file)
    except Exception as error:
        partial.unlink(missing_ok=True)
        msg = f"Failed to download {url} to {partial}: {error}"
        raise OSError(msg) from error
    actual_size = partial.stat().st_size
    try:
        expected_size = max(int(response.headers.get("Content-Length", 0)), 0)
    except (TypeError, ValueError):
        expected_size = 0
    if expected_size and actual_size != expected_size:
        partial.unlink(missing_ok=True)
        msg = f"Truncated download of {url}: got {actual_size} of {expected_size} bytes."
        raise OSError(msg)
    partial.replace(destination)
    return destination


def find_latest_adapt_time(before: datetime | None = None) -> datetime:
    """
    Find the timestamp of the newest available ADAPT map.

    Parameters
    ----------
    before : datetime.datetime, optional
        Only consider maps at or before this time. Naive values are interpreted
        as UTC. Defaults to now.

    Returns
    -------
    datetime.datetime
        Timestamp of the newest available map, as UTC.
    """
    before = before or datetime.now(UTC)
    return _row_time(_latest_adapt_row(before))


def find_nearest_adapt_time(time: datetime) -> datetime:
    """
    Find the timestamp of the ADAPT map nearest to a time, on either side.

    This is the map `fetch_adapt_fits` would download for ``time``, so the
    PFSS trigger can compare against what a run would actually render.

    Parameters
    ----------
    time : datetime.datetime
        Time to find the nearest ADAPT map for. Naive values are interpreted as
        UTC.

    Returns
    -------
    datetime.datetime
        Timestamp of the nearest available map, as UTC.
    """
    return _row_time(_nearest_adapt_row(time))
