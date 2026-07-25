"""
Render the JPEG products from the stored test FITS files, no network needed.

For eyeballing a scaling or layout change without waiting on a JSOC query:

    python tools/render_products.py

Reads ``src/suntoday/data/test`` and writes the full/small/thumb JPEG set into
``rendered_products/`` at the repo root, exactly as ``create_sdo_images`` would.
"""

import warnings
from pathlib import Path

from suntoday.constants import AIA_WAVELENGTHS, RGB_COMBINATIONS
from suntoday.data.test import TEST_DATA_ROOTDIR
from suntoday.jpegs import (
    create_blended_figure_from_maps,
    create_figure_from_map,
    create_rgb_figure_from_maps,
    save_figures,
)
from suntoday.maps import create_aia_map, create_hmi_map

warnings.simplefilter("ignore")

OUTPUT_DIRECTORY = Path(__file__).resolve().parent.parent / "rendered_products"
OUTPUT_DIRECTORY.mkdir(exist_ok=True)


def write(name_and_figure):
    name, figure = name_and_figure
    save_figures([(name, figure)], OUTPUT_DIRECTORY)
    print("wrote", name)


def find(suffix):
    return next(TEST_DATA_ROOTDIR.glob(f"*_{suffix}.fits"), None)


aia = {wavelength: path for wavelength in AIA_WAVELENGTHS if (path := find(wavelength))}
hmi = {measurement: path for measurement in ("magnetogram", "continuum") if (path := find(measurement))}
print(f"AIA {sorted(aia)} and HMI {sorted(hmi)} from {TEST_DATA_ROOTDIR}")

for create, paths in ((create_aia_map, aia.values()), (create_hmi_map, hmi.values())):
    for path in paths:
        write(create_figure_from_map(create(path)))

for combination in RGB_COMBINATIONS:
    if all(wavelength in aia for wavelength in combination):
        write(create_rgb_figure_from_maps([create_aia_map(aia[wavelength]) for wavelength in combination]))
    else:
        print("skipping RGB", combination, "- missing channels")

# The one blend pair, hardcoded the same way create_sdo_images hardcodes it.
if "171" in aia and "magnetogram" in hmi:
    write(create_blended_figure_from_maps([create_hmi_map(hmi["magnetogram"]), create_aia_map(aia["171"])]))
else:
    print("skipping blend - missing 171 or magnetogram")

print("wrote everything to", OUTPUT_DIRECTORY)
