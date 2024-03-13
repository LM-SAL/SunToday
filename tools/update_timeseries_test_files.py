import os

os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from suntoday

from pathlib import Path
from datetime import UTC, datetime
from suntoday.conftest import aia_timeseries
from suntoday.downloaders.jsoc import fetch_aia_timeseries
from suntoday.downloaders.goes import fetch_goes_timeseries


aia_timeseries = fetch_aia_timeseries(datetime.now(UTC))
goes_primary_timeseries, goes_secondary_timeseries = fetch_goes_timeseries()

aia_timeseries.to_csv(Path(__file__).parent.parent / "src/suntoday/data/test/aia_timeseries.csv",na_rep='NULL')
goes_primary_timeseries.to_csv(Path(__file__).parent.parent / "src/suntoday/data/test/goes_primary_timeseries.csv", na_rep='NULL')
goes_secondary_timeseries.to_csv(Path(__file__).parent.parent / "src/suntoday/data/test/goes_secondary_timeseries.csv", na_rep='NULL')
