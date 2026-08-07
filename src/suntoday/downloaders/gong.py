"""
Downloader for NOAA-hosted GONG synoptic magnetograms.
"""

import os
import shutil
from datetime import UTC, datetime, timedelta
from functools import cache
from operator import itemgetter
from pathlib import Path

import requests

from suntoday import DataNotReadyError

__all__ = ["fetch_gong_fits", "find_latest_gong_time", "find_nearest_gong_time"]

_GONG_ROOT = "https://services.swpc.noaa.gov"
_GONG_INDEX = f"{_GONG_ROOT}/products/gong/zqs_3day.json"
_NEAREST_WINDOW = timedelta(hours=4)
_TIMEOUT = 30
_GongRow = tuple[datetime, str]

_row_time = itemgetter(0)


def _as_utc(time: datetime) -> datetime:
    return time.replace(tzinfo=UTC) if time.tzinfo is None else time.astimezone(UTC)


def _clear_search_cache() -> None:
    _gong_rows.cache_clear()


@cache
def _gong_rows() -> list[_GongRow]:
    """
    Return NOAA's rolling index of zero-point-corrected GONG maps.
    """
    response = requests.get(_GONG_INDEX, timeout=_TIMEOUT)
    response.raise_for_status()
    return sorted(
        (
            datetime.fromisoformat(row["time_tag"]).astimezone(UTC),
            f"{_GONG_ROOT}{row['url']}",
        )
        for row in response.json()
    )


def _latest_gong_row(before: datetime) -> _GongRow:
    before = _as_utc(before)
    rows = [row for row in _gong_rows() if _row_time(row) <= before]
    if not rows:
        msg = f"No GONG map found at or before {before!r} in NOAA's rolling feed."
        raise DataNotReadyError(msg)
    return rows[-1]


def _nearest_gong_row(time: datetime, window: timedelta = _NEAREST_WINDOW) -> _GongRow:
    time = _as_utc(time)
    rows = [row for row in _gong_rows() if abs(_row_time(row) - time) <= window]
    if not rows:
        msg = f"No GONG map found within {window} of {time!r} in NOAA's rolling feed."
        raise DataNotReadyError(msg)
    return min(rows, key=lambda row: abs(_row_time(row) - time))


def fetch_gong_fits(requested_time: datetime, save_directory: Path) -> Path:
    """
    Download NOAA's zero-point-corrected GONG map nearest to a time.
    """
    url = _nearest_gong_row(requested_time)[1]
    save_directory.mkdir(parents=True, exist_ok=True)
    destination = save_directory / url.rsplit("/", 1)[-1]
    if destination.exists():
        return destination

    partial = destination.with_name(f"{destination.name}.{os.getpid()}.part")
    try:
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


def find_latest_gong_time(before: datetime | None = None) -> datetime:
    """
    Find the newest GONG map at or before a time.
    """
    return _row_time(_latest_gong_row(before or datetime.now(UTC)))


def find_nearest_gong_time(time: datetime) -> datetime:
    """
    Find the timestamp of the GONG map nearest to a time.
    """
    return _row_time(_nearest_gong_row(time))
