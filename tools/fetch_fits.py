"""
Refresh the stored FITS test data from the JSOC, in place.

Writes straight into ``src/suntoday/data/test`` and removes the previous set on
success, so the directory always holds one temporally matched set. Needs the
test-series credentials (``SUNTODAY_JSOC_USER`` / ``SUNTODAY_JSOC_PASSWORD``).

    python tools/fetch_fits.py

After running you must:

1. Update the file names in the fixtures in ``src/suntoday/conftest.py``.
2. Regenerate the figure baselines (``tox -e py-figure-generate``).
"""

import os

os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from SunToday

from pathlib import Path

from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS
from suntoday.downloaders.adapt import fetch_adapt_fits
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits, find_latest_pfss_time

TEST_DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "src" / "suntoday" / "data" / "test"

# The PFSS anchor is the time every series (AIA, HMI m45s and ADAPT) has
# data for, so one timestamp gives a temporally matched test data set.
timestamp = find_latest_pfss_time()
previous = set(TEST_DATA_DIRECTORY.glob("*.fits"))

print(f"Fetching AIA FITS files {timestamp}...")
# No time_span: the default window is the one sized to catch 1600 and 1700,
# which have a longer cadence than the rest and are otherwise missing.
fetched = {Path(file) for file in fetch_aia_fits(timestamp, save_directory=TEST_DATA_DIRECTORY)}

print(f"Fetching HMI FITS files {timestamp}...")
fetched |= {Path(file) for file in fetch_hmi_fits(timestamp, save_directory=TEST_DATA_DIRECTORY)}

print(f"Fetching ADAPT FITS file {timestamp}...")
fetched.add(fetch_adapt_fits(timestamp, save_directory=TEST_DATA_DIRECTORY))

for path in sorted(fetched):
    if path.stem.rsplit("_", 1)[-1] in AIA_FITS_ONLY_WAVELENGTHS:
        path.unlink()
        fetched.discard(path)
        print("dropped unused", path.name)

for path in sorted(previous - fetched):
    path.unlink()
    print("removed previous", path.name)

print("\nTest data now:")
for path in sorted(TEST_DATA_DIRECTORY.glob("*.fits")):
    print(" ", path.name)
