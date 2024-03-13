"""
Simple script to fetch FITS files from the JSOC.

Useful for getting updated test data.

Downloads into the current working directory. The files will need to be
moved to the test data directory manually.
"""
import os
os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from suntoday

from datetime import datetime
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits

timestamp = datetime.fromisoformat("2025-08-04T00:00:00")
print(f"Fetching AIA FITS files {timestamp}...")
results = fetch_aia_fits(timestamp, time_span="45s")

print(f"Fetching HMI FITS files {timestamp}...")
results = fetch_hmi_fits(timestamp)
