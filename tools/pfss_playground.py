"""
Playground: run PFSS on the checked-in test synframe and overplot the field
lines on a map.

Tweak the PARAMETERS block, run, and compare ``pfss_playground.png``
(the production-style disk image) with
``pfss_playground_propagated.png`` (the same plot with SunPy solar-
surface propagation). ``pfss_playground_synframe.png`` shows the
boundary magnetogram the solver saw, with the seed points and traced
line paths on top. The unpropagated image goes through the exact
production code path.

micromamba run -n suntoday python tools/pfss_playground.py
"""

import os
import resource
from pathlib import Path

os.environ["SUNTODAY_TEST_ENV"] = "True"  # Has to be set before importing anything from SunToday

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
from sunpy.coordinates import propagate_with_solar_surface

from suntoday import pfss as pfss_module
from suntoday.data.test import get_test_filepath
from suntoday.jpegs import FIELD_LINE_KWARGS, _draw_field_lines, create_figure_from_map
from suntoday.maps import create_aia_map, create_hmi_map, create_synframe_map

# --- PARAMETERS ---------------------------------------------------------
pfss_module.SOLVE_SHAPE = [360*2, 180*2]  # boundary map resample (lon, lat)
pfss_module.N_RHO = 25  # radial grid cells of the solve
pfss_module.SOURCE_SURFACE_RADIUS = 2.5  # solar radii
pfss_module.N_SEEDS = 2000  # ~15% get dropped for grazing the boundary
pfss_module.SEED_RNG = 42  # change for a different random line set
pfss_module.SEED_RADIUS = 1.05  # solar radii; higher skips low AR loops
pfss_module.MAX_STEPS = 2000  # memory knob: tracer buffer ~ n_seeds * max_steps
pfss_module.STEP_SIZE = 0.25  # bigger = fewer dropped lines but kinked footpoints
FIELD_LINE_KWARGS["color"] = "white"
FIELD_LINE_KWARGS["linewidth"] = 0.4
FIELD_LINE_KWARGS["alpha"] = 0.9
# Background: any AIA channel or the HMI magnetogram/continuum test file,
# e.g. "20260717_221157_171.fits" for AIA 171.
BACKGROUND_FITS = get_test_filepath("20260717_221200_magnetogram.fits")
SYNFRAME_FITS = get_test_filepath("20260717_222400_synframe.fits")
OUTPUT = Path(__file__).parent / "pfss_playground.png"
PROPAGATED_OUTPUT = Path(__file__).parent / "pfss_playground_propagated.png"
SYNFRAME_OUTPUT = Path(__file__).parent / "pfss_playground_synframe.png"
OUTPUT_DPI = 150  # 300 = the full production 4096 px
# ------------------------------------------------------------------------

def peak_mb() -> float:
    """
    Peak resident memory of this process so far, in MB.
    """
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


print("Solving PFSS and tracing field lines...")
field_lines = pfss_module.trace_field_lines(create_synframe_map(SYNFRAME_FITS))
print(f"  peak memory after solve+trace: {peak_mb():.0f} MB")
print(f"Rendering over {os.path.basename(BACKGROUND_FITS)}...")
create_map = create_hmi_map if ("magnetogram" in BACKGROUND_FITS or "continuum" in BACKGROUND_FITS) else create_aia_map
background_map = create_map(BACKGROUND_FITS)
_, fig = create_figure_from_map(background_map)
_draw_field_lines(fig.axes[0], background_map, field_lines)
fig.savefig(OUTPUT, dpi=OUTPUT_DPI)
print(f"Saved {OUTPUT}")

_, propagated_fig = create_figure_from_map(background_map)
with propagate_with_solar_surface():
    _draw_field_lines(propagated_fig.axes[0], background_map, field_lines)
propagated_fig.savefig(PROPAGATED_OUTPUT, dpi=OUTPUT_DPI)
print(f"Saved {PROPAGATED_OUTPUT}")

# --- Diagnostic: the boundary map the solver saw, seeds and line paths ---
print("Rendering synframe diagnostic...")
resampled = create_synframe_map(SYNFRAME_FITS).resample(pfss_module.SOLVE_SHAPE * u.pix)
resampled._data = np.nan_to_num(resampled.data)  # NOQA: SLF001
# Same draw as trace_field_lines, so the markers are the actual seed pixels.
rng = np.random.default_rng(pfss_module.SEED_RNG)
br = np.abs(resampled.data)
seed_y, seed_x = np.unravel_index(
    rng.choice(br.size, size=pfss_module.N_SEEDS, replace=False, p=br.ravel() / br.sum()), br.shape
)
syn_fig = plt.figure(figsize=(14, 7))
ax = syn_fig.add_subplot(projection=resampled)
resampled.plot(axes=ax, cmap="RdBu_r", norm=plt.Normalize(-150, 150))
line_x, line_y = resampled.wcs.world_to_pixel(field_lines)
line_x = np.asarray(line_x, dtype=float)
line_y = np.asarray(line_y, dtype=float)
# Break the polyline where it wraps around the longitude edge.
line_x[np.abs(np.diff(line_x, prepend=line_x[0])) > br.shape[1] / 2] = np.nan
ax.plot(line_x, line_y, color="black", linewidth=0.3, alpha=0.5)
ax.scatter(seed_x, seed_y, s=3, color="lime", zorder=3, label=f"{pfss_module.N_SEEDS} seeds")
ax.legend(loc="upper right")
syn_fig.savefig(SYNFRAME_OUTPUT, dpi=OUTPUT_DPI, bbox_inches="tight")
print(f"Saved {SYNFRAME_OUTPUT}")
print(f"  peak memory overall: {peak_mb():.0f} MB")
