from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from astropy.time import Time

from suntoday import DataNotReadyError
from suntoday.conftest import latest_or_skip
from suntoday.downloaders import adapt
from suntoday.downloaders.adapt import fetch_adapt_fits, find_latest_adapt_time


@pytest.mark.remote_data
def test_fetch_adapt_fits(tmp_path) -> None:
    latest = latest_or_skip(find_latest_adapt_time)
    file = fetch_adapt_fits(latest, save_directory=tmp_path)
    assert file.exists()


@pytest.mark.remote_data
def test_find_latest_adapt_time_online() -> None:
    latest = latest_or_skip(find_latest_adapt_time)

    now = datetime.now(UTC)
    assert latest.tzinfo is not None
    assert now - timedelta(days=7) < latest < now


def test_fetch_adapt_fits_raises_on_download_error(mocker, tmp_path) -> None:
    mocker.patch.object(adapt, "_nearest_adapt_row", return_value={"Start Time": Time("2026-07-20T12:00:00")})
    partial_path = tmp_path / "adapt.fts.gz.part"
    error = SimpleNamespace(
        filepath_partial=str(partial_path),
        url="http://example.test/adapt.fts.gz",
        exception=ConnectionError("connection reset"),
    )
    mocker.patch.object(adapt.Fido, "fetch", return_value=mocker.Mock(errors=[error]))

    with pytest.raises(OSError, match="connection reset") as exc_info:
        fetch_adapt_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=tmp_path)
    assert "http://example.test/adapt.fts.gz" in str(exc_info.value)
    assert str(partial_path) in str(exc_info.value)


def test_nearest_adapt_row_prefers_map_just_after_anchor(mocker) -> None:
    # HMI-limited anchor at 11:59 with ADAPT epochs at 10:00 and 12:00:
    # only-before selection would pick the 2-hour-older map.
    rows = [
        {"Start Time": Time("2026-07-20T10:00:00")},
        {"Start Time": Time("2026-07-20T12:00:00")},
    ]
    mocker.patch.object(adapt.Fido, "search", return_value=[rows])

    row = adapt._nearest_adapt_row(datetime(2026, 7, 20, 11, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]

    assert row["Start Time"] == Time("2026-07-20T12:00:00")


def test_nearest_adapt_row_raises_when_empty(mocker) -> None:
    mocker.patch.object(adapt.Fido, "search", return_value=[])
    with pytest.raises(DataNotReadyError, match="No ADAPT map found"):
        adapt._nearest_adapt_row(datetime(2026, 7, 20, 11, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]


def test_adapt_rows_reuses_first_search(mocker) -> None:
    rows = [
        {"Start Time": Time("2026-07-20T10:00:00")},
        {"Start Time": Time("2026-07-20T12:00:00")},
        {"Start Time": Time("2026-07-20T14:00:00")},
    ]
    search = mocker.patch.object(adapt.Fido, "search", return_value=[rows])
    anchor = datetime(2026, 7, 20, 13, 50, tzinfo=UTC)

    # The wide latest-style search scrapes once; the nearest-style windows
    # inside it (including the download's) reuse that listing.
    latest = adapt._latest_adapt_row(datetime(2026, 7, 20, 13, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]
    nearest = adapt._nearest_adapt_row(anchor)  # ruff:ignore[private-member-access]
    adapt._nearest_adapt_row(anchor)  # ruff:ignore[private-member-access]
    assert search.call_count == 1
    assert latest["Start Time"] == Time("2026-07-20T12:00:00")
    assert nearest["Start Time"] == Time("2026-07-20T14:00:00")

    # A window outside the cached one forces a fresh search.
    adapt._nearest_adapt_row(datetime(2026, 7, 10, 12, tzinfo=UTC))  # ruff:ignore[private-member-access]
    assert search.call_count == 2
