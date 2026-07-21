import numpy as np
import sunpy.map as smap

from suntoday.maps import (
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
