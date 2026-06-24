import pandas as pd
import pytest

from suntoday.downloaders.goes import fetch_goes_timeseries


@pytest.mark.remote_data
def test_fetch_goes_timeseries() -> None:
    goes_16, goes_18 = fetch_goes_timeseries()
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
