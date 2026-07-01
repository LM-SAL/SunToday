from unittest.mock import Mock, call

import pandas as pd
import pytest
import requests

from suntoday.downloaders import goes


def test_read_goes_json_retries_after_timeout(monkeypatch) -> None:
    response = Mock()
    response.json.return_value = [{"flux": 1.0}]
    get = Mock(side_effect=[requests.Timeout("temporary"), response])
    monkeypatch.setattr(goes.requests, "get", get)
    monkeypatch.setattr(goes.time, "sleep", Mock())

    assert goes._read_goes_json("url").to_dict("records") == [{"flux": 1.0}]  # NOQA: SLF001
    assert get.call_args_list == [call("url", timeout=goes.GOES_TIMEOUT)] * 2


def test_read_goes_json_raises_after_all_retries(monkeypatch) -> None:
    get = Mock(side_effect=requests.Timeout("down"))
    monkeypatch.setattr(goes.requests, "get", get)
    monkeypatch.setattr(goes.time, "sleep", Mock())

    with pytest.raises(RuntimeError, match="Failed to fetch GOES XRS data from url"):
        goes._read_goes_json("url")  # NOQA: SLF001
    assert get.call_count == goes.GOES_RETRIES + 1


@pytest.mark.remote_data
def test_fetch_goes_timeseries() -> None:
    goes_16, goes_18 = goes.fetch_goes_timeseries()
    for dataframe in [goes_16, goes_18]:
        assert isinstance(dataframe, pd.DataFrame)
        assert str(dataframe.index.dtype) == "datetime64[us, UTC]"
        assert len(dataframe) > 0
        assert len(dataframe.columns) == 3
        assert sorted(dataframe.columns.tolist()) == sorted(
            ["satellite", "flux", "energy"],
        )
        assert dataframe["satellite"].unique()[0] in {16, 18, 17, 19}
        assert dataframe["flux"].dtype == "float64"
        assert str(dataframe["energy"].dtype) == "str"
        assert sorted(dataframe["energy"].unique().tolist()) == sorted(["0.05-0.4nm", "0.1-0.8nm"])
