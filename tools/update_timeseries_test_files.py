"""
Refresh the stored timeseries test CSVs from the JSOC and SWPC, in place.

Needs the test-series credentials (``SUNTODAY_JSOC_USER`` /
``SUNTODAY_JSOC_PASSWORD``).
"""

import os

os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from suntoday

from pathlib import Path
from datetime import UTC, datetime
from suntoday.downloaders.jsoc import fetch_aia_timeseries
from suntoday.downloaders.goes import fetch_goes_timeseries


aia_timeseries = fetch_aia_timeseries(datetime.now(UTC))
goes_primary_timeseries = fetch_goes_timeseries(datetime.now(UTC))

aia_timeseries.to_csv(Path(__file__).parent.parent / "src/suntoday/data/test/aia_timeseries.csv",na_rep='NULL')
goes_primary_timeseries.to_csv(Path(__file__).parent.parent / "src/suntoday/data/test/goes_primary_timeseries.csv", na_rep='NULL')
