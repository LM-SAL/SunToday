from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from suntoday.jpegs import (
    create_blended_figure_from_maps,
    create_figure_from_map,
    create_rgb_figure_from_maps,
    create_sdo_images,
    save_figures,
)
from suntoday.maps import create_aia_map, create_hmi_map


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_1700(aia_1700_test_file):
    aia_map = create_aia_map(aia_1700_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_1600(aia_1600_test_file):
    aia_map = create_aia_map(aia_1600_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_335(aia_335_test_file):
    aia_map = create_aia_map(aia_335_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_304(aia_304_test_file):
    aia_map = create_aia_map(aia_304_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_211(aia_211_test_file):
    aia_map = create_aia_map(aia_211_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_193(aia_193_test_file):
    aia_map = create_aia_map(aia_193_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_171(aia_171_test_file):
    aia_map = create_aia_map(aia_171_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_aia_94(aia_94_test_file):
    aia_map = create_aia_map(aia_94_test_file)
    _, fig = create_figure_from_map(aia_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_hmi_blos(hmi_blos_test_file):
    hmi_map = create_hmi_map(hmi_blos_test_file)
    _, fig = create_figure_from_map(hmi_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_figure_from_map_hmi_cont(hmi_cont_test_file):
    hmi_map = create_hmi_map(hmi_cont_test_file)
    _, fig = create_figure_from_map(hmi_map)
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_blended_figure_from_maps(aia_171_test_file, hmi_blos_test_file):
    aia_171_map = create_aia_map(aia_171_test_file)
    hmi_blos_map = create_hmi_map(hmi_blos_test_file)
    _, fig = create_blended_figure_from_maps([hmi_blos_map, aia_171_map])
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_rgb_figure_from_maps_1(aia_94_test_file, aia_335_test_file, aia_193_test_file):
    aia_94_map = create_aia_map(aia_94_test_file)
    aia_335_map = create_aia_map(aia_335_test_file)
    aia_193_map = create_aia_map(aia_193_test_file)
    _, fig = create_rgb_figure_from_maps([aia_94_map, aia_335_map, aia_193_map])
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_rgb_figure_from_maps_2(aia_211_test_file, aia_193_test_file, aia_171_test_file):
    aia_211_map = create_aia_map(aia_211_test_file)
    aia_193_map = create_aia_map(aia_193_test_file)
    aia_171_map = create_aia_map(aia_171_test_file)
    _, fig = create_rgb_figure_from_maps([aia_211_map, aia_193_map, aia_171_map])
    return fig


@pytest.mark.mpl_image_compare(savefig_kwargs={"format": "png"}, style="default")
def test_create_rgb_figure_from_maps_3(aia_304_test_file, aia_211_test_file, aia_171_test_file):
    aia_304_map = create_aia_map(aia_304_test_file)
    aia_211_map = create_aia_map(aia_211_test_file)
    aia_171_map = create_aia_map(aia_171_test_file)
    _, fig = create_rgb_figure_from_maps([aia_304_map, aia_211_map, aia_171_map])
    return fig


def test_save_figures_from_maps_aia(aia_304_test_file, aia_211_test_file, aia_171_test_file, tmpdir) -> None:
    aia_304_map = create_aia_map(aia_304_test_file)
    aia_211_map = create_aia_map(aia_211_test_file)
    aia_171_map = create_aia_map(aia_171_test_file)
    wavelength, fig = create_rgb_figure_from_maps([aia_304_map, aia_211_map, aia_171_map])
    save_figures([(wavelength, fig)], tmpdir)
    assert len(tmpdir.listdir()) == 2
    assert (tmpdir / "f_304_211_171.jpg").exists()
    with Image.open(str(tmpdir / "f_304_211_171.jpg")) as img:
        assert img.size == (4096, 4096)
    assert (tmpdir / "l_304_211_171.jpg").exists()
    with Image.open(str(tmpdir / "l_304_211_171.jpg")) as img:
        assert img.size == (1024, 1024)


def test_save_figures_from_maps_hmi_blend(aia_171_test_file, hmi_blos_test_file, tmpdir) -> None:
    aia_171_map = create_aia_map(aia_171_test_file)
    hmi_blos_map = create_hmi_map(hmi_blos_test_file)
    wavelength, fig = create_blended_figure_from_maps([hmi_blos_map, aia_171_map])
    save_figures([(wavelength, fig)], tmpdir)
    assert len(tmpdir.listdir()) == 2
    assert (tmpdir / "f_HMImag_171.jpg").exists()
    with Image.open(str(tmpdir / "f_HMImag_171.jpg")) as img:
        assert img.size == (4096, 4096)
    assert (tmpdir / "l_HMImag_171.jpg").exists()
    with Image.open(str(tmpdir / "l_HMImag_171.jpg")) as img:
        assert img.size == (1024, 1024)


def test_save_figures_from_maps_hmi_blos(hmi_blos_test_file, tmpdir) -> None:
    hmi_blos_map = create_hmi_map(hmi_blos_test_file)
    wavelength, fig = create_figure_from_map(hmi_blos_map)
    save_figures([(wavelength, fig)], tmpdir)
    assert len(tmpdir.listdir()) == 2
    assert (tmpdir / "f_HMImag.jpg").exists()
    with Image.open(str(tmpdir / "f_HMImag.jpg")) as img:
        assert img.size == (4096, 4096)
    assert (tmpdir / "l_HMImag.jpg").exists()
    with Image.open(str(tmpdir / "l_HMImag.jpg")) as img:
        assert img.size == (1024, 1024)


def test_save_figures_from_maps_hmi_cont(hmi_cont_test_file, tmpdir) -> None:
    hmi_cont_map = create_hmi_map(hmi_cont_test_file)
    wavelength, fig = create_figure_from_map(hmi_cont_map)
    save_figures([(wavelength, fig)], tmpdir)
    assert len(tmpdir.listdir()) == 2
    assert (tmpdir / "f_HMI_cont_aiascale.jpg").exists()
    with Image.open(str(tmpdir / "f_HMI_cont_aiascale.jpg")) as img:
        assert img.size == (4096, 4096)
    assert (tmpdir / "l_HMI_cont_aiascale.jpg").exists()
    with Image.open(str(tmpdir / "l_HMI_cont_aiascale.jpg")) as img:
        assert img.size == (1024, 1024)


def test_create_sdo_images_offline(  # NOQA: PLR0917
    mocker,
    tmpdir,
    aia_1700_test_file,
    aia_1600_test_file,
    aia_171_test_file,
    aia_193_test_file,
    aia_211_test_file,
    aia_304_test_file,
    aia_131_test_file,
    aia_335_test_file,
    aia_94_test_file,
    hmi_blos_test_file,
    hmi_cont_test_file,
) -> None:
    assert len(tmpdir.listdir()) == 0
    mocker.patch(
        "suntoday.jpegs.fetch_aia_fits",
        return_value=[
            aia_131_test_file,
            aia_1600_test_file,
            aia_1700_test_file,
            aia_171_test_file,
            aia_193_test_file,
            aia_211_test_file,
            aia_304_test_file,
            aia_335_test_file,
            aia_94_test_file,
        ],
    )
    mocker.patch(
        "suntoday.jpegs.fetch_hmi_fits",
        return_value=[
            hmi_blos_test_file,
            hmi_cont_test_file,
        ],
    )
    create_sdo_images(datetime.now(UTC) - timedelta(hours=2), tmpdir)
    # These are the names of the files that exist on suntoday
    # and I had no desire to change them.
    canonical_filelist = [
        # Blended images
        "f_094_335_193.jpg",
        "f_211_193_171.jpg",
        "f_304_211_171.jpg",
        "l_094_335_193.jpg",
        "l_211_193_171.jpg",
        "l_304_211_171.jpg",
        # HMI/AIA blended images
        "f_HMImag_171.jpg",
        "l_HMImag_171.jpg",
        # HMI images
        "f_HMI_cont_aiascale.jpg",
        "f_HMImag.jpg",
        "l_HMI_cont_aiascale.jpg",
        "l_HMImag.jpg",
        # AIA images
        "f0094.jpg",
        "f0131.jpg",
        "f0171.jpg",
        "f0193.jpg",
        "f0211.jpg",
        "f0304.jpg",
        "f0335.jpg",
        "f1600.jpg",
        "f1700.jpg",
        "l0094.jpg",
        "l0131.jpg",
        "l0171.jpg",
        "l0193.jpg",
        "l0211.jpg",
        "l0304.jpg",
        "l0335.jpg",
        "l1600.jpg",
        "l1700.jpg",
        # Planning FITS files
        "f0094.fits",
        "f0131.fits",
        "f0171.fits",
        "f0193.fits",
        "f0211.fits",
        "f0304.fits",
        "f0335.fits",
        "f1600.fits",
        "f1700.fits",
        "fblos.fits",
    ]
    assert len(tmpdir.listdir()) == len(canonical_filelist)
    for file in tmpdir.listdir():
        assert file.basename in canonical_filelist


def test_create_sdo_images_online(tmpdir) -> None:
    assert len(tmpdir.listdir()) == 0
    create_sdo_images(datetime.now(UTC) - timedelta(hours=2), tmpdir)
    # These are the names of the files that exist on suntoday
    # and I had no desire to change them.
    canonical_filelist = [
        # Blended images
        "f_094_335_193.jpg",
        "f_211_193_171.jpg",
        "f_304_211_171.jpg",
        "l_094_335_193.jpg",
        "l_211_193_171.jpg",
        "l_304_211_171.jpg",
        # HMI/AIA blended images
        "f_HMImag_171.jpg",
        "l_HMImag_171.jpg",
        # HMI images
        "f_HMI_cont_aiascale.jpg",
        "f_HMImag.jpg",
        "l_HMI_cont_aiascale.jpg",
        "l_HMImag.jpg",
        # AIA images
        "f0094.jpg",
        "f0131.jpg",
        "f0171.jpg",
        "f0193.jpg",
        "f0211.jpg",
        "f0304.jpg",
        "f0335.jpg",
        "f1600.jpg",
        "f1700.jpg",
        "l0094.jpg",
        "l0131.jpg",
        "l0171.jpg",
        "l0193.jpg",
        "l0211.jpg",
        "l0304.jpg",
        "l0335.jpg",
        "l1600.jpg",
        "l1700.jpg",
        # Planning FITS files
        "f0094.fits",
        "f0131.fits",
        "f0171.fits",
        "f0193.fits",
        "f0211.fits",
        "f0304.fits",
        "f0335.fits",
        "f1600.fits",
        "f1700.fits",
        "fblos.fits",
    ]
    assert len(tmpdir.listdir()) == len(canonical_filelist)
    for file in tmpdir.listdir():
        assert file.basename in canonical_filelist
