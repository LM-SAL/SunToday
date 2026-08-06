"""
Fido-based downloader for NSO ADAPT synchronic magnetograms.

ADAPT publishes a fresh full-Sun boundary map every 2 hours, built with
an actual flux-transport model that evolves older/far-side data forward
to a common instant, rather than a JSOC-style time-composite that just
freezes older longitude strips as they rotate out of view.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sunpy.net import Fido
from sunpy.net import attrs as a
from sunpy.net.base_client import QueryResponseRow

from suntoday import DataNotReadyError
from suntoday.downloaders.downloader import format_download_errors

__all__ = ["fetch_adapt_fits", "find_latest_adapt_time", "find_nearest_adapt_time"]

_ADAPT_QUERY = (
    a.Instrument("adapt"),
    a.adapt.ADAPTFileType("4"),  # Public
    a.adapt.ADAPTLonType("0"),  # Carrington Fixed: full 0-360 longitude range
)
_NEAREST_WINDOW = timedelta(hours=4)


# Scheduled jobs run in fresh spawned processes, so one result is enough.
_search_cache: dict[str, tuple[datetime, datetime, list[QueryResponseRow]]] = {}


def _clear_search_cache() -> None:
    _search_cache.clear()


def _adapt_rows(start: datetime, end: datetime) -> list[QueryResponseRow]:
    """
    Query for the public GONG-input ADAPT maps in a time range.

    Every search fetches NSO's full year listing regardless of the window,
    so rows are reused when the requested window is inside a previous search.

    Returns
    -------
    list[sunpy.net.base_client.QueryResponseRow]
        The matching rows, oldest first.

    Raises
    ------
    suntoday.DataNotReadyError
        If no map is found in the range.
    """
    if "search" in _search_cache:
        cached_start, cached_end, cached_rows = _search_cache["search"]
        if start >= cached_start and end <= cached_end:
            rows = [row for row in cached_rows if start <= _row_time(row) <= end]
            if rows:
                return rows
            msg = f"No ADAPT map found between {start!r} and {end!r}."
            raise DataNotReadyError(msg)
    result = Fido.search(a.Time(start, end), *_ADAPT_QUERY)
    if len(result) == 0 or len(result[0]) == 0:
        msg = f"No ADAPT map found between {start!r} and {end!r}."
        raise DataNotReadyError(msg)
    rows = list(result[0])
    _search_cache["search"] = (start, end, rows)
    return rows


def _row_time(row: QueryResponseRow) -> datetime:
    return row["Start Time"].to_datetime().replace(tzinfo=UTC)


def _latest_adapt_row(before: datetime, window: timedelta = timedelta(days=7)) -> QueryResponseRow:
    """
    The newest public GONG-input ADAPT map at or before a time.

    The window is a week, not hours: ADAPT generates a map every 2 hours
    but the public archive backfills with a publication lag that has been
    observed to exceed 2 days. The search also covers the following nearest-map
    window so the scheduled job can reuse the same NSO directory scrape.

    Returns
    -------
    QueryResponseRow
        The newest matching row.

    Raises
    ------
    suntoday.DataNotReadyError
        If no map is found at or before the requested time.
    """
    rows = [row for row in _adapt_rows(before - window, before + _NEAREST_WINDOW) if _row_time(row) <= before]
    if not rows:
        msg = f"No ADAPT map found between {before - window!r} and {before!r}."
        raise DataNotReadyError(msg)
    return rows[-1]


def _nearest_adapt_row(time: datetime, window: timedelta = _NEAREST_WINDOW) -> QueryResponseRow:
    """
    The public GONG-input ADAPT map nearest to a time, either side.

    Looking on both sides matters: the PFSS anchor time can sit minutes
    before a fresh ADAPT epoch (e.g. HMI at 11:59 with ADAPT at 12:00),
    and only-before selection would pick the 2-hour-older map instead.

    Returns
    -------
    QueryResponseRow
        The row whose start time is closest to ``time``.
    """
    return min(_adapt_rows(time - window, time + window), key=lambda row: abs(_row_time(row) - time))


def fetch_adapt_fits(requested_time: datetime, save_directory: Path) -> Path:
    """
    Download the public GONG-input ADAPT magnetogram nearest to a time.

    Parameters
    ----------
    requested_time : datetime.datetime
        Time to find the nearest ADAPT map for, on either side. ADAPT
        publishes every 2 hours, so the offset is at most ~1 hour.
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
        If parfive fails to download the file.
    """
    files = Fido.fetch(_nearest_adapt_row(requested_time), path=str(save_directory / "{file}"), max_splits=1)
    if files.errors:
        msg = f"Failed to download:\n{format_download_errors(files.errors)}"
        raise OSError(msg)
    return Path(files[0])


def find_latest_adapt_time(before: datetime | None = None) -> datetime:
    """
    Find the timestamp of the newest available ADAPT map.

    Parameters
    ----------
    before : datetime.datetime, optional
        Only consider maps at or before this time. Defaults to now.

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
        Time to find the nearest ADAPT map for.

    Returns
    -------
    datetime.datetime
        Timestamp of the nearest available map, as UTC.
    """
    return _row_time(_nearest_adapt_row(time))
