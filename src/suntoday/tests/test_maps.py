import numpy as np
import pytest
import sunpy.map as smap

from suntoday.constants import AIA_SCALING
from suntoday.maps import (
    aia_norm,
    create_adapt_map,
    create_aia_map,
    create_hmi_map,
)


def test_create_aia_171_map(aia_171_test_file) -> None:
    aia_map = create_aia_map(aia_171_test_file)
    assert isinstance(aia_map, smap.GenericMap)
    assert aia_map.meta["wavelnth"] == 171
    assert aia_map.meta["exptime"] == 1.0  # ruff:ignore[float-equality-comparison]
    assert aia_map.meta["bunit"] == "ct / s"
    # Rounding to integers or zeroing everything below 1 DN/s wipes out most of
    # the disk in the faint channels, so the data has to stay floating point.
    assert aia_map.data.dtype == np.float32
    assert aia_map.plot_settings["norm"].vmin == AIA_SCALING["171"][2]


@pytest.mark.parametrize("wavelength", AIA_SCALING)
def test_aia_norm_endpoints_and_clipping(wavelength) -> None:
    _, _, vmin, vmax = AIA_SCALING[wavelength]
    norm = aia_norm(wavelength)
    assert norm(vmin) == 0
    assert norm(vmax) == 1
    # clip=True: out-of-range pixels saturate instead of coming back masked.
    assert norm(np.array([vmin / 10, vmax * 10])).tolist() == [0, 1]


def test_aia_norm_curve_shape() -> None:
    # LogNorm: the geometric mean of the limits sits at mid-grey.
    assert aia_norm("193")(np.sqrt(65.5 * 3021.0)) == pytest.approx(0.5)
    # PowerNorm(0.5): a quarter of the way up the range does.
    assert aia_norm("171")(5.9 + 0.25 * (1255.0 - 5.9)) == pytest.approx(0.5)
    assert aia_norm("4500") is None


@pytest.mark.parametrize(
    ("scaling", "match"),
    [(("asinh", 0.01, 1.0, 2.0), "unknown kind"), (("power", None, 1.0, 2.0), "positive exponent")],
)
def test_aia_norm_rejects_bad_scaling(monkeypatch, scaling, match) -> None:
    # An entry that does not name a curve this builds must not quietly fall
    # through to one that does: that renders the channel through the wrong
    # curve, which looks plausible and is how the contrast broke before.
    monkeypatch.setitem(AIA_SCALING, "193", scaling)
    with pytest.raises(ValueError, match=match):
        aia_norm("193")


def test_create_aia_faint_channel_keeps_low_signal(aia_94_test_file) -> None:
    # 94 spans roughly 0.3-10 DN/s, so any integer cast collapses it.
    aia_map = create_aia_map(aia_94_test_file)
    assert aia_map.data.min() >= 0
    on_disk = aia_map.data[aia_map.data > 0]
    assert np.count_nonzero(on_disk < 1) > 0
    assert len(np.unique(on_disk[:1000])) > 100


def test_create_adapt_map(adapt_test_file) -> None:
    adapt_map = create_adapt_map(adapt_test_file)
    assert isinstance(adapt_map, smap.GenericMap)
    assert adapt_map.coordinate_frame.name == "heliographic_carrington"
    assert adapt_map.wcs.wcs.ctype[0] == "CRLN-CEA"
    assert adapt_map.wcs.wcs.ctype[1] == "CRLT-CEA"
    # Picking a different realization should give different (but same-shape) data.
    other_realization = create_adapt_map(adapt_test_file, realization=1)
    assert other_realization.data.shape == adapt_map.data.shape
    assert not np.allclose(other_realization.data, adapt_map.data)


def test_create_hmi_cont_map(hmi_cont_test_file) -> None:
    hmi_map = create_hmi_map(hmi_cont_test_file)
    assert isinstance(hmi_map, smap.GenericMap)
    assert hmi_map.plot_settings["cmap"] == "gray"
    np.testing.assert_allclose(
        hmi_map.rotation_matrix,
        np.array([[1, 0], [0, 1]]),
    )


def test_create_hmi_blos_map(hmi_blos_test_file) -> None:
    hmi_map = create_hmi_map(hmi_blos_test_file)
    assert hmi_map.plot_settings["cmap"].name == "gray"
    assert isinstance(hmi_map, smap.GenericMap)
    np.testing.assert_allclose(
        hmi_map.rotation_matrix,
        np.array([[1, 0], [0, 1]]),
    )
