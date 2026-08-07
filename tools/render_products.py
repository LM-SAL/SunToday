"""
Render the JPEG products from the stored test FITS files, no network needed.

For eyeballing a scaling or layout change without waiting on a JSOC query:

    python tools/render_products.py

Reads ``src/suntoday/data/test`` and writes the JPEG products into
``rendered_products/`` at the repo root, exactly as ``create_sdo_images``
would: the full/small/thumb set per product, and - when the GONG test file
is present - the ``pfssnolines``/``pfss`` pair per product instead of the
plain one, matching a ``pfss=True`` run.
"""

import warnings
from pathlib import Path

from suntoday.constants import AIA_WAVELENGTHS, RGB_COMBINATIONS
from suntoday.data.test import TEST_DATA_ROOTDIR, find_test_filepath
from suntoday.jpegs import (
    _save_product,
    create_blended_figure_from_maps,
    create_figure_from_map,
    create_rgb_figure_from_maps,
)
from suntoday.maps import create_aia_map, create_gong_map, create_hmi_map
from suntoday.pfss import trace_field_lines

warnings.simplefilter("ignore")

OUTPUT_DIRECTORY = Path(__file__).resolve().parent.parent / "rendered_products"
OUTPUT_DIRECTORY.mkdir(exist_ok=True)


def find(suffix):
    # Missing files just skip that product; duplicates still raise.
    try:
        return find_test_filepath(suffix)
    except FileNotFoundError:
        return None


aia = {wavelength: path for wavelength in AIA_WAVELENGTHS if (path := find(wavelength))}
hmi = {measurement: path for measurement in ("magnetogram", "continuum") if (path := find(measurement))}
print(f"AIA {sorted(aia)} and HMI {sorted(hmi)} from {TEST_DATA_ROOTDIR}")

field_lines = None
if gong := find("gong"):
    print("tracing PFSS field lines")
    field_lines = trace_field_lines(create_gong_map(gong))
else:
    print("skipping PFSS variants - no GONG file")


def write(name_and_figure, amap):
    saved = _save_product(name_and_figure, amap, field_lines, OUTPUT_DIRECTORY)
    print("wrote", *sorted({path.name for path in saved}))


for create, paths in ((create_aia_map, aia.values()), (create_hmi_map, hmi.values())):
    for path in paths:
        amap = create(path)
        write(create_figure_from_map(amap), amap)

for combination in RGB_COMBINATIONS:
    if all(wavelength in aia for wavelength in combination):
        maps = [create_aia_map(aia[wavelength]) for wavelength in combination]
        write(create_rgb_figure_from_maps(maps), maps[0])
    else:
        print("skipping RGB", combination, "- missing channels")

# The one blend pair, hardcoded the same way create_sdo_images hardcodes it.
if "171" in aia and "magnetogram" in hmi:
    maps = [create_hmi_map(hmi["magnetogram"]), create_aia_map(aia["171"])]
    write(create_blended_figure_from_maps(maps), maps[0])
else:
    print("skipping blend - missing 171 or magnetogram")

print("wrote everything to", OUTPUT_DIRECTORY)
