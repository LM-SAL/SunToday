import numpy as np
import sunpy.map as smap
from astropy.io import fits

from suntoday.maps import (
    create_aia_map,
    create_hmi_map,
    create_synframe_map,
)


def test_create_aia_171_map(aia_171_test_file) -> None:
    aia_map = create_aia_map(aia_171_test_file)
    assert isinstance(aia_map, smap.GenericMap)
    assert aia_map.meta["wavelnth"] == 171
    assert aia_map.meta["exptime"] == 1.0  # ruff:ignore[float-equality-comparison]
    assert aia_map.meta["bunit"] == "ct / s"


def test_create_synframe_map(synframe_test_file) -> None:
    synframe_map = create_synframe_map(synframe_test_file)
    assert isinstance(synframe_map, smap.GenericMap)
    assert synframe_map.coordinate_frame.name == "heliographic_carrington"
    assert synframe_map.data.shape == (1440, 3600)
    assert synframe_map.scale.axis1.value > 0
    assert str(synframe_map.spatial_units[1]) == "deg"
    raw = fits.getdata(synframe_test_file)
    row, column = np.unravel_index(np.nanargmax(np.abs(raw)), raw.shape)
    assert synframe_map.data[row, column] == raw[row, column]


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
    assert hmi_map.plot_settings["cmap"].name == "hmimag"
    assert isinstance(hmi_map, smap.GenericMap)
    np.testing.assert_allclose(
        hmi_map.rotation_matrix,
        np.array([[1, 0], [0, 1]]),
    )
