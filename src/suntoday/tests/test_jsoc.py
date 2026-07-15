from datetime import UTC, datetime, timedelta

import pytest

from suntoday.constants import AIA_WAVELENGTHS
from suntoday.downloaders.jsoc import _get_latest_record_time, find_latest_jsoc_times, get_aia_urls


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
    # AIA carries a one minute margin so its forward query window still
    # covers all wavelengths; HMI is the older of its two series.
    aia_latest = datetime(2026, 7, 14, 12, 50, tzinfo=UTC)
    mag_latest = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    cont_latest = datetime(2026, 7, 14, 11, 55, tzinfo=UTC)
    mocker.patch(
        "suntoday.downloaders.jsoc._get_latest_record_time",
        side_effect=[aia_latest, mag_latest, cont_latest],
    )

    aia_time, hmi_time = find_latest_jsoc_times()

    assert aia_time == aia_latest - timedelta(minutes=1)
    assert hmi_time == cont_latest
