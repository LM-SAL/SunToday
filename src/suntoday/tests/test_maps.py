import numpy as np
import pytest
import sunpy.map as smap

from suntoday.constants import AIA_SINGLE_NORMS
from suntoday.data.test import find_test_filepath
from suntoday.maps import (
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
    assert aia_map.data.dtype == np.int32
    assert aia_map.data.min() >= 0


def test_aia_193_idl_norm() -> None:
    norm = AIA_SINGLE_NORMS["193"]()
    assert norm(norm.vmin) == 0
    assert norm(norm.vmax) == 1
    # clip=True: out-of-range pixels saturate instead of coming back masked.
    assert norm(np.array([norm.vmin / 10, norm.vmax * 10])).tolist() == [0, 1]
    # LogNorm: the geometric mean of the limits sits at mid-grey.
    assert norm(np.sqrt(65.5 * 3021.0)) == pytest.approx(0.5)


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
