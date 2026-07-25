from datetime import UTC, datetime, timedelta

import pytest
from astropy.time import Time

from suntoday.downloaders import adapt
from suntoday.downloaders.adapt import fetch_adapt_fits, find_latest_adapt_time


@pytest.mark.remote_data
def test_fetch_adapt_fits(tmp_path) -> None:
    file = fetch_adapt_fits(datetime.now(UTC) - timedelta(days=2), save_directory=tmp_path)
    assert file.exists()


@pytest.mark.remote_data
def test_find_latest_adapt_time_online() -> None:
    latest = find_latest_adapt_time()

    now = datetime.now(UTC)
    assert latest.tzinfo is not None
    assert now - timedelta(days=7) < latest < now


def test_fetch_adapt_fits_raises_on_download_error(mocker, tmp_path) -> None:
    mocker.patch.object(adapt, "_nearest_adapt_row", return_value={"Start Time": Time("2026-07-20T12:00:00")})
    mocker.patch.object(adapt.Fido, "fetch", return_value=mocker.Mock(errors=["connection reset"]))

    with pytest.raises(OSError, match="Failed to download"):
        fetch_adapt_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=tmp_path)


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
    with pytest.raises(ValueError, match="No ADAPT map found"):
        adapt._nearest_adapt_row(datetime(2026, 7, 20, 11, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]
