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

__all__ = ["fetch_adapt_fits", "find_latest_adapt_time", "find_nearest_adapt_time"]

_ADAPT_QUERY = (
    a.Instrument("adapt"),
    a.adapt.ADAPTFileType("4"),  # Public
    a.adapt.ADAPTLonType("0"),  # Carrington Fixed: full 0-360 longitude range
)


def _adapt_rows(start: datetime, end: datetime):
    """
    Query for the public GONG-input ADAPT maps in a time range.

    Returns
    -------
    sunpy.net.base_client.QueryResponseTable
        The matching rows, oldest first.

    Raises
    ------
    ValueError
        If no map is found in the range.
    """
    result = Fido.search(a.Time(start, end), *_ADAPT_QUERY)
    if len(result) == 0 or len(result[0]) == 0:
        msg = f"No ADAPT map found between {start!r} and {end!r}."
        raise ValueError(msg)
    return result[0]


def _row_time(row: QueryResponseRow) -> datetime:
    return row["Start Time"].to_datetime().replace(tzinfo=UTC)


def _latest_adapt_row(before: datetime, window: timedelta = timedelta(days=7)) -> QueryResponseRow:
    """
    The newest public GONG-input ADAPT map at or before a time.

    The window is a week, not hours: ADAPT generates a map every 2 hours
    but the public archive backfills with a publication lag that has been
    observed to exceed 2 days.

    Returns
    -------
    QueryResponseRow
        The newest matching row.
    """
    return _adapt_rows(before - window, before)[-1]


def _nearest_adapt_row(time: datetime, window: timedelta = timedelta(hours=4)) -> QueryResponseRow:
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
        msg = f"Failed to download {files.errors}."
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
