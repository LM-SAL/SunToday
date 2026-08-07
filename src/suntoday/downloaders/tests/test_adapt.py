import os
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO

import pytest
from astropy.io import fits

from suntoday import DataNotReadyError
from suntoday.downloaders import adapt
from suntoday.downloaders.adapt import fetch_adapt_fits, find_latest_adapt_time


def _download_response(mocker, body: bytes, content_length: int):
    response = mocker.MagicMock(raw=BytesIO(body), headers={"Content-Length": str(content_length)})
    response.__enter__.return_value = response
    return response


@pytest.mark.remote_data
def test_fetch_adapt_fits(tmp_path) -> None:
    latest = find_latest_adapt_time()
    file = fetch_adapt_fits(latest, save_directory=tmp_path)
    with fits.open(file) as hdul:
        assert hdul[0].data.shape == (12, 180, 360)
    now = datetime.now(UTC)
    assert latest.tzinfo is not None
    assert now - timedelta(days=7) < latest < now


def test_fetch_adapt_fits_falls_back_to_ftp_and_caches(mocker, tmp_path) -> None:
    filename = "adapt40311_044012_202607201200_i00005600n1.fts.gz"
    listing = BytesIO(f"-rw-rw-r-- 1 500 500 4 Jul 20 12:00 {filename}\n".encode())
    download = BytesIO(b"data")
    download.headers = {"Content-Length": "invalid"}
    get = mocker.patch.object(adapt.requests, "get", side_effect=adapt.requests.ConnectTimeout("timed out"))
    ftp = mocker.patch.object(adapt, "urlopen", side_effect=[listing, download])
    save_directory = tmp_path / "not-yet-created"

    file = fetch_adapt_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=save_directory)

    assert file == save_directory / filename
    assert file.read_bytes() == b"data"
    # A second call reuses the existing file without touching the network.
    assert fetch_adapt_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=save_directory) == file
    assert get.call_count == 1
    assert ftp.call_count == 2
    assert not list(save_directory.glob(f"{filename}.*.part"))


def test_fetch_adapt_fits_raises_on_download_error(mocker, tmp_path) -> None:
    url = "https://example.test/adapt.fts.gz"
    mocker.patch.object(adapt, "_nearest_adapt_row", return_value=(datetime(2026, 7, 20, 12, tzinfo=UTC), url))
    mocker.patch.object(adapt.requests, "get", side_effect=ConnectionError("connection reset"))

    with pytest.raises(OSError, match="connection reset") as exc_info:
        fetch_adapt_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=tmp_path)
    assert url in str(exc_info.value)
    assert f"adapt.fts.gz.{os.getpid()}.part" in str(exc_info.value)
    assert list(tmp_path.iterdir()) == []


def test_fetch_adapt_fits_rejects_truncated_download(mocker, tmp_path) -> None:
    url = "https://example.test/adapt.fts.gz"
    mocker.patch.object(adapt, "_nearest_adapt_row", return_value=(datetime(2026, 7, 20, 12, tzinfo=UTC), url))
    mocker.patch.object(adapt.requests, "get", return_value=_download_response(mocker, b"data", 10))

    with pytest.raises(OSError, match="got 4 of 10 bytes"):
        fetch_adapt_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_nearest_adapt_row_prefers_map_just_after_anchor(mocker) -> None:
    # HMI-limited anchor at 11:59 with ADAPT epochs at 10:00 and 12:00:
    # only-before selection would pick the 2-hour-older map.
    rows = [
        (datetime(2026, 7, 20, 10, tzinfo=UTC), "https://example.test/10.fts.gz"),
        (datetime(2026, 7, 20, 12, tzinfo=UTC), "https://example.test/12.fts.gz"),
    ]
    mocker.patch.object(adapt, "_adapt_rows", return_value=rows)

    row = adapt._nearest_adapt_row(datetime(2026, 7, 20, 11, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]

    assert row == rows[1]


def test_nearest_adapt_row_treats_naive_time_as_utc(mocker) -> None:
    time = datetime(2026, 7, 20, 12)  # ruff:ignore[call-datetime-without-tzinfo]
    row = (time.replace(tzinfo=UTC), "https://example.test/12.fts.gz")
    rows = mocker.patch.object(adapt, "_adapt_rows", return_value=[row])

    assert adapt._nearest_adapt_row(time) == row  # ruff:ignore[private-member-access]
    rows.assert_called_once_with(
        time.replace(tzinfo=UTC) - timedelta(hours=4), time.replace(tzinfo=UTC) + timedelta(hours=4)
    )


def test_nearest_adapt_row_raises_when_empty(mocker) -> None:
    mocker.patch.object(adapt.requests, "get", return_value=mocker.Mock(status_code=200, text="<html></html>"))
    with pytest.raises(DataNotReadyError, match="No ADAPT map found"):
        adapt._nearest_adapt_row(datetime(2026, 7, 20, 11, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]


def test_adapt_rows_reuses_first_search(mocker) -> None:
    listing = """<html>
        <a href="adapt40311_044012_202607101200_i00005600n1.fts.gz">old</a>
        <a href="adapt40311_044012_202607201000_i00005600n1.fts.gz">10</a>
        <a href="adapt40311_044012_202607201200_i00005600n1.fts.gz">12</a>
        <a href="adapt40311_044012_202607201400_i00005600n1.fts.gz">14</a>
    </html>"""
    search = mocker.patch.object(adapt.requests, "get", return_value=mocker.Mock(status_code=200, text=listing))
    anchor = datetime(2026, 7, 20, 13, 50, tzinfo=UTC)

    # The wide latest-style search scrapes July once; every other window in
    # the same month (including the download's) reuses that listing.
    latest = adapt._latest_adapt_row(datetime(2026, 7, 20, 13, 59, tzinfo=UTC))  # ruff:ignore[private-member-access]
    nearest = adapt._nearest_adapt_row(anchor)  # ruff:ignore[private-member-access]
    adapt._nearest_adapt_row(anchor)  # ruff:ignore[private-member-access]
    adapt._nearest_adapt_row(datetime(2026, 7, 10, 12, tzinfo=UTC))  # ruff:ignore[private-member-access]
    assert search.call_count == 1
    assert search.call_args.kwargs == {"timeout": 30}
    assert "P=adapt40%2A_202607%2A.fts.gz" in search.call_args.args[0]
    assert latest[0] == datetime(2026, 7, 20, 12, tzinfo=UTC)
    assert nearest[0] == datetime(2026, 7, 20, 14, tzinfo=UTC)


def test_adapt_rows_spans_months_and_skips_missing_year(mocker) -> None:
    december = '<a href="adapt40311_044012_202612312000_i00005600n1.fts.gz">dec</a>'

    def fake_get(url, timeout):  # ruff:ignore[unused-function-argument]
        if "/2027/" in url:
            return mocker.Mock(status_code=404)
        assert "P=adapt40%2A_202612%2A.fts.gz" in url
        return mocker.Mock(status_code=200, text=december)

    search = mocker.patch.object(adapt.requests, "get", side_effect=fake_get)

    # Dec 31 22:00 + 4h crosses into a 2027 directory NSO has not created yet:
    # the December map must still be found instead of a 404 crash.
    row = adapt._nearest_adapt_row(datetime(2026, 12, 31, 22, tzinfo=UTC))  # ruff:ignore[private-member-access]

    assert row[0] == datetime(2026, 12, 31, 20, tzinfo=UTC)
    assert search.call_count == 2


def test_adapt_rows_converts_search_window_to_utc(mocker) -> None:
    listing = '<a href="adapt40311_044012_202612312000_i00005600n1.fts.gz">dec</a>'
    search = mocker.patch.object(adapt.requests, "get", return_value=mocker.Mock(status_code=200, text=listing))

    # Jan 1 01:00 +05:00 is Dec 31 20:00 UTC, so only December needs scraping.
    end = datetime(2027, 1, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    rows = adapt._adapt_rows(end - timedelta(hours=4), end)  # ruff:ignore[private-member-access]

    assert search.call_count == 1
    assert "P=adapt40%2A_202612%2A.fts.gz" in search.call_args.args[0]
    assert [adapt._row_time(row) for row in rows] == [datetime(2026, 12, 31, 20, tzinfo=UTC)]  # ruff:ignore[private-member-access]
