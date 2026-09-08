"""
Refresh the stored FITS test data from the JSOC, in place.

Writes straight into ``src/suntoday/data/test`` and removes the previous
set on success, so the directory always holds one temporally matched
set. Needs the test-series credentials (``SUNTODAY_JSOC_USER`` /
``SUNTODAY_JSOC_PASSWORD``).

python tools/fetch_fits.py

The test fixtures find every file by its suffix (wavelength,
``magnetogram``, ``continuum``, ``synoptic``), so no conftest updates
are needed; figure tests asserting on-image timestamps still change.
"""

import os

os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from SunToday

from pathlib import Path

from suntoday.constants import AIA_FITS_ONLY_WAVELENGTHS
from suntoday.downloaders.jsoc import fetch_aia_fits, fetch_hmi_fits, fetch_hmi_synoptic_fits, find_latest_pfss_time

TEST_DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "src" / "suntoday" / "data" / "test"

# The SDO images share an anchor; use the preceding HMI synoptic frame.
timestamp = find_latest_pfss_time()
previous = set(TEST_DATA_DIRECTORY.glob("*.fits"))

print(f"Fetching AIA FITS files {timestamp}...")
# No time_span: the default window is the one sized to catch 1600 and 1700,
# which have a longer cadence than the rest and are otherwise missing.
fetched = {Path(file) for file in fetch_aia_fits(timestamp, save_directory=TEST_DATA_DIRECTORY)}

print(f"Fetching HMI FITS files {timestamp}...")
fetched |= {Path(file) for file in fetch_hmi_fits(timestamp, save_directory=TEST_DATA_DIRECTORY)}

print(f"Fetching HMI synoptic FITS file {timestamp}...")
fetched.add(fetch_hmi_synoptic_fits(timestamp, save_directory=TEST_DATA_DIRECTORY))

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
