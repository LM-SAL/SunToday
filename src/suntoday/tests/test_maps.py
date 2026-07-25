import numpy as np
import pytest
import sunpy.map as smap

from suntoday.constants import AIA_SCALING
from suntoday.data.test import find_test_filepath
from suntoday.maps import (
    aia_norm,
    create_adapt_map,
    create_aia_map,
    create_hmi_map,
)


def test_create_aia_171_map() -> None:
    aia_map = create_aia_map(find_test_filepath("171"))
    assert isinstance(aia_map, smap.GenericMap)
    assert aia_map.meta["wavelnth"] == 171
    assert aia_map.meta["exptime"] == 1.0  # ruff:ignore[float-equality-comparison]
    assert aia_map.meta["bunit"] == "ct / s"
    # Rounding to integers or zeroing everything below 1 DN/s wipes out most of
    # the disk in the faint channels, so the data has to stay floating point.
    assert aia_map.data.dtype == np.float32
    assert aia_map.plot_settings["norm"].vmin == AIA_SCALING["171"]().vmin


@pytest.mark.parametrize("wavelength", AIA_SCALING)
def test_aia_norm_endpoints_and_clipping(wavelength) -> None:
    norm = aia_norm(wavelength)
    assert norm(norm.vmin) == 0
    assert norm(norm.vmax) == 1
    # clip=True: out-of-range pixels saturate instead of coming back masked.
    assert norm(np.array([norm.vmin / 10, norm.vmax * 10])).tolist() == [0, 1]


def test_aia_norm_curve_shape() -> None:
    # LogNorm: the geometric mean of the limits sits at mid-grey.
    assert aia_norm("193")(np.sqrt(65.5 * 3021.0)) == pytest.approx(0.5)
    # PowerNorm(0.5): a quarter of the way up the range does.
    assert aia_norm("171")(5.9 + 0.25 * (1255.0 - 5.9)) == pytest.approx(0.5)
    assert aia_norm("4500") is None


def test_create_aia_faint_channel_keeps_low_signal() -> None:
    # 94 spans roughly 0.3-10 DN/s, so any integer cast collapses it.
    aia_map = create_aia_map(find_test_filepath("94"))
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


def test_find_test_filepath_missing() -> None:
    with pytest.raises(FileNotFoundError, match="No test FITS file"):
        find_test_filepath("9999")


def test_find_test_filepath_ambiguous(mocker, tmp_path) -> None:
    (tmp_path / "a_171.fits").touch()
    (tmp_path / "b_171.fits").touch()
    mocker.patch("suntoday.data.test.TEST_DATA_ROOTDIR", tmp_path)
    with pytest.raises(ValueError, match="Multiple test FITS files"):
        find_test_filepath("171")
