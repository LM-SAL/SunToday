from datetime import UTC, datetime, timedelta

import pytest

from suntoday.downloaders.jsoc import _get_latest_record_time, find_latest_jsoc_times


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
