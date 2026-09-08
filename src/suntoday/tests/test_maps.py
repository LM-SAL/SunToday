import astropy.units as u
import numpy as np
import pytest
import sunpy.map as smap
from astropy.io import fits
from scipy.ndimage import map_coordinates
from sunpy.coordinates import propagate_with_solar_surface
from sunpy.map import all_coordinates_from_map, coordinate_is_on_solar_disk

from suntoday.constants import AIA_SINGLE_NORMS
from suntoday.data.test import find_test_filepath
from suntoday.maps import (
    create_aia_map,
    create_hmi_map,
    create_hmi_synoptic_map,
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


def test_hmi_synoptic_coordinates_and_disk_alignment(hmi_synoptic_test_file, hmi_blos_test_file) -> None:
    boundary = create_hmi_synoptic_map(hmi_synoptic_test_file)
    np.testing.assert_array_equal(boundary.data, fits.getdata(hmi_synoptic_test_file))
    assert boundary.date.utc.isot == "2026-07-17T20:59:31.000"
    assert boundary.reference_date == boundary.date
    assert boundary.reference_pixel.x.value == pytest.approx((boundary.data.shape[1] - 1) / 2)
    assert boundary.reference_coordinate.lon.deg == pytest.approx(326.750003)
    assert boundary.scale.axis1.value == pytest.approx(0.1)
    assert boundary.scale.axis2.value == pytest.approx(180 / np.pi * 2 / boundary.data.shape[0], rel=1e-4)

    # Compare independent disk observations with the corrected boundary.
    # A sign error or a 180-degree shift decorrelates the active regions.
    with fits.open(hmi_blos_test_file) as hdul:
        disk = smap.Map(hdul[1].data, hdul[1].header).resample([512, 512] * u.pix)
    y, x = np.indices(disk.data.shape)
    world = disk.pixel_to_world(x * u.pix, y * u.pix)
    central_disk = np.hypot(world.Tx, world.Ty) < disk.rsun_obs * 0.7
    with propagate_with_solar_surface():
        carrington = world[central_disk].transform_to(boundary.coordinate_frame)
    bx, by = boundary.wcs.world_to_pixel(carrington)
    sampled = map_coordinates(boundary.data, [by, bx], order=1, mode="grid-wrap")
    observed = disk.data[central_disk]
    valid = np.isfinite(sampled) & np.isfinite(observed)
    assert np.corrcoef(sampled[valid], observed[valid])[0, 1] > 0.5


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


def test_hmi_row_mask_matches_full_map(hmi_blos_test_file) -> None:
    with fits.open(hmi_blos_test_file, memmap=False) as hdul:
        expected = smap.Map(hdul[1].data, hdul[1].header).rotate()
    expected.data[~coordinate_is_on_solar_disk(all_coordinates_from_map(expected))] = np.nan

    actual = create_hmi_map(hmi_blos_test_file)

    np.testing.assert_equal(actual.data, expected.data)


def test_find_test_filepath_missing() -> None:
    with pytest.raises(FileNotFoundError, match="No test FITS file"):
        find_test_filepath("9999")


def test_find_test_filepath_ambiguous(mocker, tmp_path) -> None:
    (tmp_path / "a_171.fits").touch()
    (tmp_path / "b_171.fits").touch()
    mocker.patch("suntoday.data.test.TEST_DATA_ROOTDIR", tmp_path)
    with pytest.raises(ValueError, match="Multiple test FITS files"):
        find_test_filepath("171")
