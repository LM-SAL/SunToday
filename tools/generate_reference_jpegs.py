"""
Generate reference JPEGs from the checked-in test FITS files.

These mirror what the production pipeline outputs (full-size f*.jpg
only, regular and PFSS variants). Run after any change to the image look
to eyeball the result; output lands in ./reference_jpegs and is not
committed.
"""

import os

os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from SunToday

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from suntoday.data.test import get_test_filepath
from suntoday.jpegs import create_sdo_images

AIA_FILES = [
    get_test_filepath(name)
    for name in [
        "20260717_221154_131.fits",
        "20260717_221150_1600.fits",
        "20260717_221204_1700.fits",
        "20260717_221157_171.fits",
        "20260717_221204_193.fits",
        "20260717_221157_211.fits",
        "20260717_221205_304.fits",
        "20260717_221200_335.fits",
        "20260717_221159_94.fits",
    ]
]
HMI_FILES = [
    get_test_filepath("20260717_221200_magnetogram.fits"),
    get_test_filepath("20260717_221200_continuum.fits"),
]
SYNFRAME_FILE = get_test_filepath("20260717_222400_synframe.fits")
REFERENCE_DIR = Path("./reference_jpegs")
REFERENCE_DIR.mkdir(exist_ok=True)

with tempfile.TemporaryDirectory() as temp_dir:
    output_dir = Path(temp_dir)
    with (
        mock.patch("suntoday.jpegs.fetch_aia_fits", return_value=AIA_FILES),
        mock.patch("suntoday.jpegs.fetch_hmi_fits", return_value=HMI_FILES),
        mock.patch("suntoday.jpegs.fetch_synframe_fits", return_value=SYNFRAME_FILE),
    ):
        timestamp = datetime(2026, 1, 27, 17, 19, tzinfo=UTC)
        print("Creating regular products...")
        create_sdo_images(timestamp, output_dir)
        print("Creating PFSS products...")
        create_sdo_images(timestamp, output_dir, pfss=True)
    for jpeg in sorted(output_dir.glob("f*.jpg")):
        shutil.copy2(jpeg, REFERENCE_DIR / jpeg.name)
        print(f"Updated {jpeg.name}")
