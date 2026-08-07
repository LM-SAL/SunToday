from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from suntoday import DataNotReadyError
from suntoday.constants import AIA_WAVELENGTHS
from suntoday.downloaders.jsoc import (
    _get_latest_record_time,
    _get_urls,
    fetch_aia_fits,
    fetch_aia_timeseries,
    find_latest_jsoc_times,
    find_latest_pfss_time,
    get_aia_urls,
    get_hmi_urls,
)


def test_get_urls_zero_count_is_data_not_ready(mocker) -> None:
    mocker.patch("suntoday.downloaders.jsoc._jsoc_auth", return_value=None)
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"count": 0, "runtime": 0.011, "status": 0}
    mocker.patch("suntoday.downloaders.jsoc.requests.get", return_value=response)

    with pytest.raises(DataNotReadyError, match="JSOC has no records yet"):
        _get_urls("lm_jps.Ic_45s[2026.07.29_08:00:00_TAI]", "T_REC", "continuum")


def test_get_urls_malformed_response_is_error(mocker) -> None:
    mocker.patch("suntoday.downloaders.jsoc._jsoc_auth", return_value=None)
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"status": 1}
    mocker.patch("suntoday.downloaders.jsoc.requests.get", return_value=response)

    with pytest.raises(ValueError, match="returned with no data"):
        _get_urls("lm_jps.Ic_45s[2026.07.29_08:00:00_TAI]", "T_REC", "continuum")


@pytest.mark.parametrize("fetch", [fetch_aia_timeseries, get_hmi_urls])
def test_timeseries_and_hmi_zero_count_are_data_not_ready(fetch, mocker) -> None:
    mocker.patch("suntoday.downloaders.jsoc._jsoc_auth", return_value=None)
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"count": 0, "runtime": 0.011, "status": 0}
    mocker.patch("suntoday.downloaders.jsoc.requests.get", return_value=response)

    with pytest.raises(DataNotReadyError, match="JSOC has no records yet"):
        fetch(datetime(2026, 7, 29, 8, tzinfo=UTC))


def test_get_latest_record_time_parses_tai_format(mocker) -> None:
    mocker.patch(
        "suntoday.downloaders.jsoc._get_urls",
        return_value={
            "keywords": [{"name": "T_REC", "values": ["2026.07.14_12:00:00_TAI"]}],
            "segments": [{"name": "magnetogram", "values": ["/a.fits"]}],
        },
    )

    latest = _get_latest_record_time("lm_jps.m45s_nrt", "T_REC", "magnetogram")

    assert latest == datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def test_get_latest_record_time_no_records(mocker) -> None:
    mocker.patch(
        "suntoday.downloaders.jsoc._get_urls",
        return_value={
            "keywords": [{"name": "T_REC", "values": []}],
            "segments": [{"name": "magnetogram", "values": []}],
        },
    )

    with pytest.raises(ValueError, match=r"No records returned for lm_jps.m45s_nrt\[\$\]"):
        _get_latest_record_time("lm_jps.m45s_nrt", "T_REC", "magnetogram")


def _aia_urls_response(wavelengths):
    return {
        "keywords": [
            {"name": "DATE-OBS", "values": [f"2026-07-15T12:00:{i:02d}Z" for i in range(len(wavelengths))]},
            {"name": "WAVELNTH", "values": wavelengths},
            {"name": "EXPTIME", "values": ["2.9"] * len(wavelengths)},
        ],
        "segments": [
            {"name": "image_lev1p5", "values": [f"/img{i}.fits" for i in range(len(wavelengths))]},
        ],
    }


def test_get_aia_urls_keeps_fits_only_and_drops_unknown(mocker) -> None:
    # 4500 is a FITS-only bonus channel: kept when present, while anything the
    # pipeline does not know is dropped instead of crashing the sort downstream.
    mocker.patch(
        "suntoday.downloaders.jsoc._get_urls",
        return_value=_aia_urls_response([*AIA_WAVELENGTHS, "4500", "9999"]),
    )

    aia_urls = get_aia_urls(datetime(2026, 7, 15, 12, 0, tzinfo=UTC))

    assert set(aia_urls["WAVELNTH"]) == {*AIA_WAVELENGTHS, "4500"}


def test_get_aia_urls_does_not_require_fits_only_channels(mocker) -> None:
    mocker.patch(
        "suntoday.downloaders.jsoc._get_urls",
        return_value=_aia_urls_response(list(AIA_WAVELENGTHS)),
    )

    aia_urls = get_aia_urls(datetime(2026, 7, 15, 12, 0, tzinfo=UTC))

    assert set(aia_urls["WAVELNTH"]) == set(AIA_WAVELENGTHS)


def test_fetch_aia_fits_uses_three_minute_window(mocker, tmp_path) -> None:
    get_aia_urls = mocker.patch("suntoday.downloaders.jsoc.get_aia_urls")
    get_aia_urls.return_value.iterrows.return_value = []
    downloader = mocker.patch("suntoday.downloaders.jsoc.create_downloader").return_value
    downloader.download.return_value.errors = []
    requested_time = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    fetch_aia_fits(requested_time, save_directory=tmp_path)

    get_aia_urls.assert_called_once_with(requested_time, time_span="180s")


def test_fetch_aia_fits_reports_parfive_error_details(mocker, tmp_path) -> None:
    get_aia_urls = mocker.patch("suntoday.downloaders.jsoc.get_aia_urls")
    get_aia_urls.return_value.iterrows.return_value = []
    downloader = mocker.patch("suntoday.downloaders.jsoc.create_downloader").return_value
    partial_path = tmp_path / "image.fits.part"
    downloader.download.return_value.errors = [
        SimpleNamespace(
            filepath_partial=str(partial_path),
            url="http://example.test/image.fits",
            exception=TimeoutError("download timed out"),
        )
    ]

    with pytest.raises(OSError, match="download timed out") as exc_info:
        fetch_aia_fits(datetime(2026, 7, 15, 12, 0, tzinfo=UTC), save_directory=tmp_path)

    message = str(exc_info.value)
    assert "http://example.test/image.fits" in message
    assert str(partial_path) in message


@pytest.mark.remote_data
def test_find_latest_jsoc_times_online() -> None:
    now = datetime.now(UTC)

    aia_time, hmi_time = find_latest_jsoc_times()

    # Sanity window: recent enough to be real NRT data, in the past, and
    # timezone-aware. A parse bug (e.g. epoch or swapped fields) lands far
    # outside this range.
    times = f"AIA: {aia_time}, HMI: {hmi_time}, now: {now}"
    for latest in (aia_time, hmi_time):
        assert latest.tzinfo is not None, times
        assert now - timedelta(hours=4) < latest < now, times


def test_find_latest_jsoc_times_per_instrument(mocker) -> None:
    # AIA carries a three minute margin so its forward query window still
    # covers all wavelengths; HMI is the older of its two series.
    aia_latest = datetime(2026, 7, 14, 12, 50, tzinfo=UTC)
    mag_latest = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    cont_latest = datetime(2026, 7, 14, 11, 55, tzinfo=UTC)
    mocker.patch(
        "suntoday.downloaders.jsoc._get_latest_record_time",
        side_effect=[aia_latest, mag_latest, cont_latest],
    )

    aia_time, hmi_time = find_latest_jsoc_times()

    assert aia_time == aia_latest - timedelta(minutes=3)
    assert hmi_time == cont_latest


def test_find_latest_pfss_time_uses_oldest_source(mocker) -> None:
    aia_time = datetime(2026, 7, 14, 11, 50, tzinfo=UTC)
    hmi_time = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    gong_time = datetime(2026, 7, 14, 12, 10, tzinfo=UTC)
    mocker.patch("suntoday.downloaders.jsoc.find_latest_jsoc_times", return_value=(aia_time, hmi_time))
    mocker.patch("suntoday.downloaders.jsoc.find_latest_gong_time", return_value=gong_time)

    assert find_latest_pfss_time() == aia_time
