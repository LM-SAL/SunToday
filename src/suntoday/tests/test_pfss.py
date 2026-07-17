import numpy as np

from suntoday.maps import create_synframe_map
from suntoday.pfss import N_SEEDS, trace_field_lines


def test_trace_field_lines(synframe_test_file) -> None:
    field_lines = trace_field_lines(create_synframe_map(synframe_test_file))
    assert field_lines.frame.name == "heliographic_carrington"
    radii = field_lines.spherical.distance.to_value("km")
    # One NaN separator per kept line; boundary-grazing lines are dropped
    n_lines = np.isnan(radii).sum()
    assert 0 < n_lines <= N_SEEDS
    solar_radius_km = 696000
    finite = radii[np.isfinite(radii)]
    assert len(finite) > n_lines  # every line has actual points
    assert finite.min() >= solar_radius_km * 0.99
    assert finite.max() <= solar_radius_km * 2.6


def test_trace_field_lines_deterministic(synframe_test_file) -> None:
    first = trace_field_lines(create_synframe_map(synframe_test_file))
    second = trace_field_lines(create_synframe_map(synframe_test_file))
    np.testing.assert_array_equal(
        first.spherical.lon.deg,
        second.spherical.lon.deg,
    )
