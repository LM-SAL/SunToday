from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, call

import pandas as pd
import pytest
import requests

from suntoday import DataNotReadyError
from suntoday.downloaders import goes


def _raw_json_frame(times: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "time_tag": times.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "satellite": 19,
        "flux": 1e-6,
        "observed_flux": 1e-6,
        "electron_correction": 0.0,
        "electron_contaminaton": False,
        "energy": "0.1-0.8nm",
    })


def _assert_goes_frame(goes_df: pd.DataFrame, end_time: datetime) -> None:
    assert isinstance(goes_df, pd.DataFrame)
    assert len(goes_df) > 0
    assert sorted(goes_df.columns.tolist()) == sorted(["satellite", "flux", "energy"])
    assert goes_df["satellite"].unique()[0] in {16, 17, 18, 19}
    assert goes_df["flux"].dtype == "float64"
    assert str(goes_df["energy"].dtype) == "str"
    assert sorted(goes_df["energy"].unique().tolist()) == sorted(["0.05-0.4nm", "0.1-0.8nm"])
    assert goes_df.index.min() > pd.Timestamp(end_time - timedelta(days=1))
    assert goes_df.index.max() <= pd.Timestamp(end_time)


def test_read_goes_json_retries_after_timeout(monkeypatch) -> None:
    response = Mock()
    response.json.return_value = [{"flux": 1.0}]
    get = Mock(side_effect=[requests.Timeout("temporary"), response])
    sleep = Mock()
    monkeypatch.setattr(goes.requests, "get", get)
    monkeypatch.setattr(goes.time, "sleep", sleep)

    assert goes._read_goes_json("url").to_dict("records") == [{"flux": 1.0}]  # ruff:ignore[private-member-access]
    assert get.call_args_list == [call("url", timeout=goes.GOES_TIMEOUT)] * 2
    assert sleep.call_args_list == [call(goes.GOES_RETRY_DELAY)]


def test_read_goes_json_raises_after_all_retries(monkeypatch) -> None:
    get = Mock(side_effect=requests.Timeout("down"))
    sleep = Mock()
    monkeypatch.setattr(goes.requests, "get", get)
    monkeypatch.setattr(goes.time, "sleep", sleep)

    with pytest.raises(RuntimeError, match="Failed to fetch GOES XRS data from url"):
        goes._read_goes_json("url")  # ruff:ignore[private-member-access]
    assert get.call_count == goes.GOES_RETRIES + 1
    assert sleep.call_args_list == [call(goes.GOES_RETRY_DELAY)] * goes.GOES_RETRIES


def test_fetch_goes_timeseries_windows_nrt_for_recent_times(monkeypatch) -> None:
    end_time = datetime.now(UTC)
    times = pd.date_range(end_time - timedelta(days=7), end_time, freq="h", tz="UTC")
    monkeypatch.setattr(goes, "_read_goes_json", lambda _url: _raw_json_frame(times))
    monkeypatch.setattr(
        goes, "_fetch_archive_goes_timeseries", Mock(side_effect=AssertionError("archive used for recent time"))
    )

    goes_df = goes.fetch_goes_timeseries(end_time)
    # Only the 24 hourly points inside (end_time - 1 day, end_time] survive.
    assert len(goes_df) == 24
    assert goes_df.index.min() > pd.Timestamp(end_time - timedelta(days=1))
    assert goes_df.index.max() <= pd.Timestamp(end_time)


def test_fetch_goes_timeseries_uses_archive_for_old_times(monkeypatch) -> None:
    end_time = datetime(2022, 3, 31, tzinfo=UTC)
    times = pd.date_range(end_time - timedelta(days=1), end_time, freq="h", tz="UTC", inclusive="right")
    archive_frame = pd.DataFrame({"satellite": 16, "flux": 1e-6, "energy": "0.1-0.8nm"}, index=times)
    archive = Mock(return_value=archive_frame)
    monkeypatch.setattr(goes, "_fetch_archive_goes_timeseries", archive)
    monkeypatch.setattr(goes, "_read_goes_json", Mock(side_effect=AssertionError("NRT JSON used for old time")))

    goes_df = goes.fetch_goes_timeseries(end_time)
    assert archive.call_args == call(end_time - timedelta(days=1), end_time)
    assert len(goes_df) == 24


def test_fetch_goes_timeseries_rejects_naive_end_time() -> None:
    with pytest.raises(ValueError, match="end_time must be timezone-aware"):
        goes.fetch_goes_timeseries(datetime(2022, 3, 31))  # ruff:ignore[call-datetime-without-tzinfo]


def test_fetch_goes_timeseries_raises_when_window_is_empty(monkeypatch) -> None:
    end_time = datetime.now(UTC)
    monkeypatch.setattr(
        goes, "_read_goes_json", lambda _url: _raw_json_frame(pd.DatetimeIndex([end_time - timedelta(days=2)]))
    )

    with pytest.raises(DataNotReadyError, match="No GOES XRS data found"):
        goes.fetch_goes_timeseries(end_time)


def test_fetch_archive_goes_timeseries_raises_when_no_files(monkeypatch) -> None:
    import sunpy.net
    from astropy.table import Table

    fido = Mock()
    fido.search.return_value = [Table({"SatelliteNumber": [18]})]
    fido.fetch.return_value = []
    monkeypatch.setattr(sunpy.net, "Fido", fido)

    with pytest.raises(DataNotReadyError, match="No GOES XRS archive data found"):
        goes._fetch_archive_goes_timeseries(  # ruff:ignore[private-member-access]
            datetime(2022, 3, 30, tzinfo=UTC), datetime(2022, 3, 31, tzinfo=UTC)
        )
    fido.fetch.assert_called_once()


def test_fetch_archive_goes_timeseries_omits_unsupported_satellite_filter(monkeypatch) -> None:
    import sunpy.net
    from astropy.table import Table
    from sunpy.net import attrs as a

    fido = Mock()
    fido.search.return_value = [Table({"SatelliteNumber": [18]})]
    fido.fetch.return_value = []
    monkeypatch.setattr(sunpy.net, "Fido", fido)

    with pytest.raises(DataNotReadyError):
        goes._fetch_archive_goes_timeseries(  # ruff:ignore[private-member-access]
            datetime(2026, 7, 13, tzinfo=UTC), datetime(2026, 7, 14, tzinfo=UTC)
        )

    assert not any(isinstance(attr, a.goes.SatelliteNumber) for attr in fido.search.call_args.args)


def test_fetch_archive_goes_timeseries_selects_latest_satellite(monkeypatch) -> None:
    import sunpy.net
    from astropy.table import Table

    fido = Mock()
    fido.search.return_value = [Table({"SatelliteNumber": [16, 18]})]
    fido.fetch.return_value = []
    monkeypatch.setattr(sunpy.net, "Fido", fido)

    with pytest.raises(DataNotReadyError):
        goes._fetch_archive_goes_timeseries(  # ruff:ignore[private-member-access]
            datetime(2022, 3, 30, tzinfo=UTC), datetime(2022, 3, 31, tzinfo=UTC)
        )

    assert list(fido.fetch.call_args.args[0]["SatelliteNumber"]) == [18]


@pytest.mark.remote_data
def test_fetch_goes_timeseries_nrt() -> None:
    end_time = datetime.now(UTC)
    _assert_goes_frame(goes.fetch_goes_timeseries(end_time), end_time)


@pytest.mark.remote_data
def test_fetch_goes_timeseries_archive() -> None:
    end_time = datetime(2022, 3, 31, tzinfo=UTC)
    goes_df = goes.fetch_goes_timeseries(end_time)
    _assert_goes_frame(goes_df, end_time)
    assert goes_df["satellite"].unique()[0] == 16
