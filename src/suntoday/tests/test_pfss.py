import numpy as np

from suntoday.maps import create_gong_map
from suntoday.pfss import N_SEEDS, trace_field_lines


def test_trace_field_lines(gong_test_file) -> None:
    field_lines = trace_field_lines(create_gong_map(gong_test_file))
    assert field_lines.frame.name == "heliographic_carrington"
    radii = field_lines.spherical.distance.to_value("km")
    is_open = field_lines.info.meta["is_open"]
    assert field_lines.info.meta["boundary_source"] == "GONG"
    assert is_open.shape == radii.shape
    # One NaN separator per kept line; boundary-grazing lines are dropped
    n_lines = np.isnan(radii).sum()
    assert 0 < n_lines <= N_SEEDS
    solar_radius_km = 696000
    finite = radii[np.isfinite(radii)]
    assert len(finite) > n_lines  # every line has actual points
    assert finite.min() >= solar_radius_km * 0.99
    assert finite.max() <= solar_radius_km * 2.6
    # PFSS invariant: every kept line terminates at the photosphere (closed,
    # both ends) or the source surface (open, one end) - never mid-corona.
    nan_indices = np.flatnonzero(np.isnan(radii))
    starts = np.concatenate(([0], nan_indices[:-1] + 1))
    ends = nan_indices - 1
    endpoint_radii = np.concatenate((radii[starts], radii[ends])) / solar_radius_km
    assert np.all((endpoint_radii < 1.05) | (endpoint_radii > 2.4))
    # Both populations exist: some closed and some open lines.
    assert (endpoint_radii < 1.05).any()
    assert (endpoint_radii > 2.4).any()
    assert is_open[nan_indices].any()
    assert (~is_open[nan_indices]).any()
