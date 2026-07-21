"""
Simple script to fetch FITS files from the JSOC.

Useful for getting updated test data.

Downloads into the current working directory. The files will need to be
moved to the test data directory manually.
"""

import os
os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from SunToday

from suntoday.downloaders.adapt import fetch_adapt_fits
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits, find_latest_pfss_time

# The PFSS anchor is the time every series (AIA, HMI m45s and ADAPT) has
# data for, so one timestamp gives a temporally matched test data set.
timestamp = find_latest_pfss_time()

print(f"Fetching AIA FITS files {timestamp}...")
results = fetch_aia_fits(timestamp, time_span="45s")

print(f"Fetching HMI FITS files {timestamp}...")
results = fetch_hmi_fits(timestamp)

print(f"Fetching ADAPT FITS file {timestamp}...")
fetch_adapt_fits(timestamp)
