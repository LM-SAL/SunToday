import os
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from astropy.io import fits

from suntoday import DataNotReadyError
from suntoday.downloaders import gong
from suntoday.downloaders.gong import fetch_gong_fits, find_latest_gong_time
from suntoday.maps import create_gong_map


def _download_response(mocker, body: bytes, content_length: int | str):
    response = mocker.MagicMock(raw=BytesIO(body), headers={"Content-Length": str(content_length)})
    response.__enter__.return_value = response
    return response


@pytest.mark.remote_data
def test_fetch_gong_fits(tmp_path) -> None:
    latest = find_latest_gong_time()
    file = fetch_gong_fits(latest, save_directory=tmp_path)
    with fits.open(file) as hdul:
        assert hdul[0].data.shape == (180, 360)
    gong_map = create_gong_map(file)
    assert list(gong_map.wcs.wcs.ctype) == ["CRLN-CEA", "CRLT-CEA"]
    assert datetime.now(UTC) - timedelta(days=7) < latest < datetime.now(UTC)


def test_fetch_gong_fits_selects_downloads_and_caches(mocker, tmp_path) -> None:
    filename = "mrzqs260720t1204c2313_112.fits.gz"
    index = mocker.Mock()
    index.json.return_value = [
        {"url": "/products/gong/zqs/mrzqs260720t1004c2313_113.fits.gz", "time_tag": "2026-07-20T10:04:00Z"},
        {"url": f"/products/gong/zqs/{filename}", "time_tag": "2026-07-20T12:04:00Z"},
    ]
    download = _download_response(mocker, b"data", "invalid")
    get = mocker.patch.object(gong.requests, "get", side_effect=[index, download])
    save_directory = tmp_path / "not-yet-created"

    file = fetch_gong_fits(
        datetime(2026, 7, 20, 12),  # ruff:ignore[call-datetime-without-tzinfo]
        save_directory=save_directory,
    )

    assert file == save_directory / filename
    assert file.read_bytes() == b"data"
    assert find_latest_gong_time(datetime(2026, 7, 20, 13, tzinfo=UTC)) == datetime(2026, 7, 20, 12, 4, tzinfo=UTC)
    assert fetch_gong_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=save_directory) == file
    assert get.call_count == 2
    assert not list(save_directory.glob(f"{filename}.*.part"))


def test_fetch_gong_fits_raises_on_download_error(mocker, tmp_path) -> None:
    url = "https://example.test/gong.fits.gz"
    mocker.patch.object(gong, "_nearest_gong_row", return_value=(datetime(2026, 7, 20, 12, tzinfo=UTC), url))
    mocker.patch.object(gong.requests, "get", side_effect=ConnectionError("connection reset"))

    with pytest.raises(OSError, match="connection reset") as exc_info:
        fetch_gong_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=tmp_path)
    assert url in str(exc_info.value)
    assert f"gong.fits.gz.{os.getpid()}.part" in str(exc_info.value)
    assert list(tmp_path.iterdir()) == []


def test_fetch_gong_fits_rejects_truncated_download(mocker, tmp_path) -> None:
    url = "https://example.test/gong.fits.gz"
    mocker.patch.object(gong, "_nearest_gong_row", return_value=(datetime(2026, 7, 20, 12, tzinfo=UTC), url))
    mocker.patch.object(gong.requests, "get", return_value=_download_response(mocker, b"data", 10))

    with pytest.raises(OSError, match="got 4 of 10 bytes"):
        fetch_gong_fits(datetime(2026, 7, 20, 12, tzinfo=UTC), save_directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_find_nearest_gong_time_raises_when_feed_is_empty(mocker) -> None:
    response = mocker.patch.object(gong.requests, "get").return_value
    response.json.return_value = []

    with pytest.raises(DataNotReadyError, match="No GONG map found"):
        gong.find_nearest_gong_time(datetime(2026, 7, 20, 12, tzinfo=UTC))
