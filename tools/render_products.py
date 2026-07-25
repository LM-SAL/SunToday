"""
Render the JPEG products from the stored test FITS files, no network needed.

For eyeballing a scaling or layout change without waiting on a JSOC query:

    python tools/render_products.py

Reads ``src/suntoday/data/test`` and writes the full/small/thumb JPEG set into
``rendered_products/`` at the repo root, exactly as ``create_sdo_images`` would.
"""

import warnings
from pathlib import Path

import matplotlib as mpl

mpl.use("module://mplcairo.base")

from astropy.io import fits

from suntoday.constants import RGB_COMBINATIONS
from suntoday.jpegs import (
    create_blended_figure_from_maps,
    create_figure_from_map,
    create_rgb_figure_from_maps,
    save_figures,
)
from suntoday.maps import create_aia_map, create_hmi_map

warnings.simplefilter("ignore")

ROOT = Path(__file__).resolve().parent.parent
FITS_DIRECTORY = ROOT / "src" / "suntoday" / "data" / "test"
OUTPUT_DIRECTORY = ROOT / "rendered_products"
OUTPUT_DIRECTORY.mkdir(exist_ok=True)

aia_files, hmi_files = {}, {}
for path in sorted(FITS_DIRECTORY.glob("*.fits")):
    with fits.open(path) as hdul:
        header = next((hdu.header for hdu in hdul if hdu.data is not None), None)
    if header is None:
        continue
    instrument = str(header.get("INSTRUME", "")).upper()
    if "AIA" in instrument:
        aia_files[f"{float(header['WAVELNTH']):.0f}"] = path
    elif "HMI" in instrument:
        measurement = "magnetogram" if "MAGNETOGRAM" in str(header.get("CONTENT", "")).upper() else "continuum"
        hmi_files[measurement] = path
print(f"AIA {sorted(aia_files)} and HMI {sorted(hmi_files)} from {FITS_DIRECTORY}")

for create, files in ((create_aia_map, aia_files), (create_hmi_map, hmi_files)):
    for path in files.values():
        name, fig = create_figure_from_map(create(path))
        save_figures([(name, fig)], OUTPUT_DIRECTORY)
        print("wrote", name)

for combination in RGB_COMBINATIONS:
    if not all(wavelength in aia_files for wavelength in combination):
        print("skipping RGB", combination, "- missing channels")
        continue
    name, fig = create_rgb_figure_from_maps([create_aia_map(aia_files[w]) for w in combination])
    save_figures([(name, fig)], OUTPUT_DIRECTORY)
    print("wrote", name)

# The one blend pair, hardcoded the same way create_sdo_images hardcodes it.
if "171" in aia_files and "magnetogram" in hmi_files:
    name, fig = create_blended_figure_from_maps(
        [create_hmi_map(hmi_files["magnetogram"]), create_aia_map(aia_files["171"])]
    )
    save_figures([(name, fig)], OUTPUT_DIRECTORY)
    print("wrote", name)
else:
    print("skipping blend - missing 171 or magnetogram")

print("wrote everything to", OUTPUT_DIRECTORY)
