"""
PFSS extrapolation and magnetic field line tracing.
"""

import warnings

import astropy.units as u
import numpy as np
import sunpy.map as smap
from astropy.constants import R_sun
from astropy.coordinates import SkyCoord
from sunkit_magex import pfss as magex_pfss
from sunkit_magex.pfss import tracing

__all__ = ["trace_field_lines"]

# Solve grid: the synframe is resampled down to this before the spherical
# harmonic solve.
SOLVE_SHAPE = [720, 360]  # pixels (lon, lat)
N_RHO = 35
SOURCE_SURFACE_RADIUS = 2.5  # solar radii
# Seeds are drawn flux-weighted (probability ~ |Br|) so lines bundle at
# active regions like the historical LMSAL rendering. Fixed RNG seed keeps
# the output reproducible for the figure tests. ~15% of the traces are
# dropped for grazing the boundary (see below), so seed a surplus.
N_SEEDS = 2000
SEED_RNG = 42
# Start just above the photosphere so the low active region loops are
# caught: from higher seeds the traces skip over the compact loops of the
# strong regions. At this height the boundary-grazing drops are spread
# evenly in field strength instead of clustering in active regions.
SEED_RADIUS = 1.01  # solar radii
# The tracer preallocates n_seeds * max_steps points per direction, so this
# is the main memory knob (~190 MB at 2000 seeds / 2000 steps). Legitimate
# lines finish in under ~700 steps; only the boundary-grazing lines dropped
# below run long.
MAX_STEPS = 2000
STEP_SIZE = 0.5


def trace_field_lines(synframe_map: smap.GenericMap) -> SkyCoord:
    """
    Run a PFSS extrapolation and trace field lines from flux-weighted seeds.

    Parameters
    ----------
    synframe_map : `sunpy.map.GenericMap`
        Full-Sun Carrington magnetogram from
        `suntoday.maps.create_synframe_map`.

    Returns
    -------
    `astropy.coordinates.SkyCoord`
        All traced field lines as a single Carrington polyline, with a
        NaN-valued point separating consecutive lines so it can be drawn
        with one matplotlib call.
    """
    synframe_map = synframe_map.resample(SOLVE_SHAPE * u.pix)
    synframe_map._data = np.nan_to_num(synframe_map.data)  # ruff:ignore[private-member-access]
    output = magex_pfss.pfss(magex_pfss.Input(synframe_map, N_RHO, SOURCE_SURFACE_RADIUS))
    rng = np.random.default_rng(SEED_RNG)
    br = np.abs(synframe_map.data)
    pixel_y, pixel_x = np.unravel_index(
        rng.choice(br.size, size=N_SEEDS, replace=False, p=br.ravel() / br.sum()), br.shape
    )
    world = synframe_map.wcs.pixel_to_world(pixel_x, pixel_y)
    seeds = SkyCoord(world.lon, world.lat, SEED_RADIUS * R_sun, frame=synframe_map.coordinate_frame)
    tracer = tracing.PerformanceTracer(max_steps=MAX_STEPS, step_size=STEP_SIZE)
    with warnings.catch_warnings():
        # Some lines graze the lower boundary and orbit until the step limit;
        # they render as scribbles, so they are dropped below instead of
        # traced further.
        warnings.filterwarnings("ignore", message="At least one field line ran out of steps")
        field_lines = tracer.trace(seeds, output)
    ran_out = (np.asarray(tracer.tracer.ROT) == 1).reshape(len(field_lines), -1).any(axis=1)
    longitudes, latitudes, radii = [], [], []
    for field_line, dropped in zip(field_lines, ran_out, strict=True):
        if dropped:
            continue
        spherical = field_line.coords.spherical
        longitudes.append(np.append(spherical.lon.to_value(u.deg), np.nan))
        latitudes.append(np.append(spherical.lat.to_value(u.deg), np.nan))
        radii.append(np.append(spherical.distance.to_value(u.km), np.nan))
    return SkyCoord(
        np.concatenate(longitudes) * u.deg,
        np.concatenate(latitudes) * u.deg,
        np.concatenate(radii) * u.km,
        frame=field_lines[0].coords.frame.replicate_without_data(),
    )
