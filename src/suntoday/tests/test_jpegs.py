from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import call

import pytest
from PIL import Image

from suntoday.constants import AIA_WAVELENGTHS
from suntoday.downloaders.jsoc import find_latest_pfss_time
from suntoday.jpegs import (
    _draw_field_lines,
    _save_product,
    create_blended_figure_from_maps,
    create_figure_from_map,
    create_rgb_figure_from_maps,
    create_sdo_images,
    save_figures,
)
from suntoday.maps import create_adapt_map, create_aia_map, create_hmi_map
from suntoday.pfss import trace_field_lines
from suntoday.tests.conftest import mpl_svg_compare


@pytest.fixture(scope="module")
def pfss_field_lines(adapt_test_file):
    return trace_field_lines(create_adapt_map(adapt_test_file))


@pytest.mark.parametrize("wavelength", AIA_WAVELENGTHS)
@mpl_svg_compare
def test_create_figure_from_map_aia(request, wavelength):
    aia_map = create_aia_map(request.getfixturevalue(f"aia_{wavelength}_test_file"))
    filename, fig = create_figure_from_map(aia_map)
    assert filename == wavelength.zfill(4)
    return fig


@mpl_svg_compare
def test_create_figure_from_map_hmi_blos(hmi_blos_test_file):
    hmi_map = create_hmi_map(hmi_blos_test_file)
    wavelength, fig = create_figure_from_map(hmi_map)
    assert wavelength == "_HMImag"
    return fig


@mpl_svg_compare
def test_create_figure_from_map_hmi_continuum(hmi_cont_test_file):
    hmi_map = create_hmi_map(hmi_cont_test_file)
    wavelength, fig = create_figure_from_map(hmi_map)
    assert wavelength == "_HMI_cont_aiascale"
    return fig


@pytest.mark.mpl_image_compare
def test_create_blended_figure_from_maps(aia_171_test_file, hmi_blos_test_file):
    aia_171_map = create_aia_map(aia_171_test_file)
    hmi_blos_map = create_hmi_map(hmi_blos_test_file)
    wavelength, fig = create_blended_figure_from_maps([hmi_blos_map, aia_171_map])
    assert wavelength == "_HMImag_171"
    return fig


@mpl_svg_compare
def test_create_rgb_figure_from_maps_1(aia_94_test_file, aia_335_test_file, aia_193_test_file):
    aia_94_map = create_aia_map(aia_94_test_file)
    aia_335_map = create_aia_map(aia_335_test_file)
    aia_193_map = create_aia_map(aia_193_test_file)
    wavelength, fig = create_rgb_figure_from_maps([aia_94_map, aia_335_map, aia_193_map])
    assert wavelength == "_094_335_193"
    return fig


@mpl_svg_compare
def test_create_rgb_figure_from_maps_2(aia_211_test_file, aia_193_test_file, aia_171_test_file):
    aia_211_map = create_aia_map(aia_211_test_file)
    aia_193_map = create_aia_map(aia_193_test_file)
    aia_171_map = create_aia_map(aia_171_test_file)
    wavelength, fig = create_rgb_figure_from_maps([aia_211_map, aia_193_map, aia_171_map])
    assert wavelength == "_211_193_171"
    return fig


@mpl_svg_compare
def test_create_rgb_figure_from_maps_3(aia_304_test_file, aia_211_test_file, aia_171_test_file):
    aia_304_map = create_aia_map(aia_304_test_file)
    aia_211_map = create_aia_map(aia_211_test_file)
    aia_171_map = create_aia_map(aia_171_test_file)
    _, fig = create_rgb_figure_from_maps([aia_304_map, aia_211_map, aia_171_map])
    return fig


@pytest.mark.mpl_image_compare
def test_create_pfss_figure_from_map_hmi_blos(hmi_blos_test_file, pfss_field_lines):
    hmi_map = create_hmi_map(hmi_blos_test_file)
    _, fig = create_figure_from_map(hmi_map)
    _draw_field_lines(fig.axes[0], hmi_map, pfss_field_lines)
    assert fig.axes[0].texts[-1].get_text() == "PFSS ADAPT         - 2026-07-17 22:00:00"
    return fig


def test_save_figures_from_maps_aia(aia_304_test_file, aia_211_test_file, aia_171_test_file, tmpdir) -> None:
    aia_304_map = create_aia_map(aia_304_test_file)
    aia_211_map = create_aia_map(aia_211_test_file)
    aia_171_map = create_aia_map(aia_171_test_file)
    wavelength, fig = create_rgb_figure_from_maps([aia_304_map, aia_211_map, aia_171_map])
    saved_paths = save_figures([(wavelength, fig)], tmpdir)
    assert set(saved_paths) == {
        tmpdir / "f_304_211_171.jpg",
        tmpdir / "l_304_211_171.jpg",
        tmpdir / "t_304_211_171.jpg",
    }
    assert len(tmpdir.listdir()) == 3
    assert (tmpdir / "f_304_211_171.jpg").exists()
    with Image.open(str(tmpdir / "f_304_211_171.jpg")) as img:
        assert img.size == (4096, 4096)
    assert (tmpdir / "l_304_211_171.jpg").exists()
    with Image.open(str(tmpdir / "l_304_211_171.jpg")) as img:
        assert img.size == (1024, 1024)
    assert (tmpdir / "t_304_211_171.jpg").exists()
    with Image.open(str(tmpdir / "t_304_211_171.jpg")) as img:
        assert img.size == (256, 256)


@pytest.mark.remote_data
def test_create_sdo_images_live_smoke(mocker, tmp_path) -> None:
    for module in ["suntoday.jpegs", "suntoday.downloaders.jsoc"]:
        mocker.patch(f"{module}.AIA_WAVELENGTHS", ["304", "211", "171"])
        mocker.patch(f"{module}.AIA_FITS_ONLY_WAVELENGTHS", [])
    mocker.patch("suntoday.jpegs.RGB_COMBINATIONS", [("304", "211", "171")])

    files = create_sdo_images(datetime.now(UTC) - timedelta(days=2), tmp_path)

    assert len([file for file in files if file.suffix == ".jpg"]) == 21
    assert len([file for file in files if file.suffix == ".fits"]) == 5
    assert all(file.exists() and file.stat().st_size > 0 for file in files)


@pytest.mark.remote_data
def test_create_sdo_images_pfss_live_smoke(mocker, tmp_path) -> None:
    for module in ["suntoday.jpegs", "suntoday.downloaders.jsoc"]:
        mocker.patch(f"{module}.AIA_WAVELENGTHS", ["171"])
        mocker.patch(f"{module}.AIA_FITS_ONLY_WAVELENGTHS", [])
    mocker.patch("suntoday.jpegs.RGB_COMBINATIONS", [])

    files = create_sdo_images(find_latest_pfss_time(), tmp_path, pfss=True)

    assert len(files) == 24
    assert len([file for file in files if "pfssnolines" in file.name]) == 12
    assert not [file for file in files if file.suffix == ".fits"]
    assert all(file.exists() and file.stat().st_size > 0 for file in files)


def test_create_sdo_images_orchestrates_products(mocker, tmp_path) -> None:
    aia_files = [tmp_path / wavelength for wavelength in ["94", "335", "193", "171"]]
    hmi_files = [tmp_path / measurement for measurement in ["magnetogram", "continuum"]]
    mocker.patch("suntoday.jpegs.AIA_WAVELENGTHS", ["94", "335", "193", "171"])
    mocker.patch("suntoday.jpegs.AIA_FITS_ONLY_WAVELENGTHS", [])
    mocker.patch("suntoday.jpegs.RGB_COMBINATIONS", [["94", "335", "193"]])
    mocker.patch("suntoday.jpegs.fetch_aia_fits", return_value=aia_files)
    mocker.patch("suntoday.jpegs.fetch_hmi_fits", return_value=hmi_files)
    mocker.patch(
        "suntoday.jpegs.create_aia_map",
        side_effect=lambda path: SimpleNamespace(
            label=path.stem,
            wavelength=SimpleNamespace(value=int(path.stem)),
        ),
    )
    mocker.patch(
        "suntoday.jpegs.create_hmi_map",
        side_effect=lambda path: SimpleNamespace(label=path.stem, measurement=path.stem),
    )
    mocker.patch(
        "suntoday.jpegs.create_figure_from_map",
        side_effect=lambda amap: (amap.label, mocker.sentinel.figure),
    )
    create_rgb = mocker.patch(
        "suntoday.jpegs.create_rgb_figure_from_maps",
        return_value=("rgb", mocker.sentinel.figure),
    )
    create_blend = mocker.patch(
        "suntoday.jpegs.create_blended_figure_from_maps",
        return_value=("blend", mocker.sentinel.figure),
    )
    mocker.patch("suntoday.jpegs.save_fits", side_effect=lambda _map, directory, name: directory / name)
    save_product = mocker.patch(
        "suntoday.jpegs._save_product",
        side_effect=lambda figure, _map, _lines, directory: [directory / f"{figure[0]}.jpg"],
    )

    files = create_sdo_images(datetime(2026, 7, 13, tzinfo=UTC), tmp_path)

    assert {path.name for path in files} == {
        "f0094.fits",
        "f0171.fits",
        "f0193.fits",
        "f0335.fits",
        "fblos.fits",
        "fcontinuum.fits",
        "94.jpg",
        "171.jpg",
        "193.jpg",
        "335.jpg",
        "magnetogram.jpg",
        "continuum.jpg",
        "rgb.jpg",
        "blend.jpg",
    }
    assert [amap.label for amap in create_rgb.call_args.args[0]] == ["94", "335", "193"]
    assert [amap.label for amap in create_blend.call_args.args[0]] == ["magnetogram", "171"]
    assert all(product.args[2] is None for product in save_product.call_args_list)


def test_save_product_pfss(mocker, tmp_path) -> None:
    fig = mocker.Mock(axes=[mocker.sentinel.axes])
    amap = mocker.sentinel.map
    field_lines = mocker.sentinel.field_lines
    base = tmp_path / "base.jpg"
    overlay = tmp_path / "overlay.jpg"
    save = mocker.patch("suntoday.jpegs.save_figures", side_effect=[[base], [overlay]])
    draw = mocker.patch("suntoday.jpegs._draw_field_lines")

    assert _save_product(("0171", fig), amap, field_lines, tmp_path) == [base, overlay]
    assert save.call_args_list == [
        call([("0171pfssnolines", fig)], tmp_path, close=False),
        call([("0171pfss", fig)], tmp_path),
    ]
    draw.assert_called_once_with(mocker.sentinel.axes, amap, field_lines)


def test_create_pfss_images_uses_field_lines(
    mocker,
    tmp_path,
) -> None:
    aia_file = tmp_path / "171"
    hmi_file = tmp_path / "magnetogram"
    adapt_file = tmp_path / "adapt"
    aia_map = mocker.sentinel.aia_map
    hmi_map = mocker.Mock(measurement="magnetogram")
    field_lines = mocker.sentinel.field_lines
    mocker.patch("suntoday.jpegs.AIA_WAVELENGTHS", ["171"])
    mocker.patch("suntoday.jpegs.AIA_FITS_ONLY_WAVELENGTHS", [])
    mocker.patch("suntoday.jpegs.RGB_COMBINATIONS", [])
    mocker.patch("suntoday.jpegs.fetch_aia_fits", return_value=[aia_file])
    mocker.patch("suntoday.jpegs.fetch_hmi_fits", return_value=[hmi_file])
    mocker.patch("suntoday.jpegs.fetch_adapt_fits", return_value=adapt_file)
    boundary = mocker.patch("suntoday.jpegs.create_adapt_map").return_value
    trace = mocker.patch("suntoday.jpegs.trace_field_lines", return_value=field_lines)
    mocker.patch("suntoday.jpegs.create_aia_map", return_value=aia_map)
    mocker.patch("suntoday.jpegs.create_hmi_map", return_value=hmi_map)
    mocker.patch("suntoday.jpegs.create_figure_from_map", return_value=("single", mocker.sentinel.figure))
    mocker.patch("suntoday.jpegs.create_blended_figure_from_maps", return_value=("blend", mocker.sentinel.figure))
    save_fits = mocker.patch("suntoday.jpegs.save_fits")
    save_product = mocker.patch("suntoday.jpegs._save_product", return_value=[])

    assert create_sdo_images(datetime.now(UTC), tmp_path, pfss=True) == []
    trace.assert_called_once_with(boundary)
    save_fits.assert_not_called()
    assert save_product.call_count == 3
    assert all(product.args[2] is field_lines for product in save_product.call_args_list)
