import warnings

import pytest
from astropy.io import fits
from astropy.io.fits.verify import VerifyWarning

from suntoday.data.test import find_test_filepath
from suntoday.maps import create_aia_map
from suntoday.utils import save_fits, sync_to_s3


def test_sync_to_s3(tmp_path, mocker) -> None:
    s3_client = mocker.patch("suntoday.utils.boto3.client").return_value
    day_directory = tmp_path / "2026" / "07" / "13"
    day_directory.mkdir(parents=True)
    (day_directory / "f171.jpg").write_bytes(b"jpeg")
    (day_directory / "aia171.fits").write_bytes(b"fits")
    (day_directory / "aia_light_curves.gif").write_bytes(b"png")

    sync_to_s3(
        list(day_directory.iterdir()),
        "s3://my-bucket/base",
        tmp_path,
        mostrecent_root=day_directory,
    )

    calls = {call.args[2]: call for call in s3_client.upload_file.call_args_list}
    assert set(calls) == {
        "base/2026/07/13/f171.jpg",
        "base/2026/07/13/aia171.fits",
        "base/2026/07/13/aia_light_curves.gif",
    }
    assert calls["base/2026/07/13/f171.jpg"].kwargs["ExtraArgs"] == {
        "ContentType": "image/jpeg",
        "CacheControl": "max-age=300, must-revalidate",
    }
    assert calls["base/2026/07/13/aia171.fits"].kwargs["ExtraArgs"] == {"ContentType": "image/fits"}
    assert calls["base/2026/07/13/aia_light_curves.gif"].kwargs["ExtraArgs"] == {
        "ContentType": "image/png",
        "CacheControl": "max-age=300, must-revalidate",
    }
    assert calls["base/2026/07/13/f171.jpg"].args[1] == "my-bucket"
    copies = {call.kwargs["Key"]: call for call in s3_client.copy_object.call_args_list}
    assert set(copies) == {
        "base/mostrecent/f171.jpg",
        "base/mostrecent/aia171.fits",
        "base/mostrecent/aia_light_curves.gif",
    }
    assert copies["base/mostrecent/f171.jpg"].kwargs == {
        "Bucket": "my-bucket",
        "CopySource": {"Bucket": "my-bucket", "Key": "base/2026/07/13/f171.jpg"},
        "Key": "base/mostrecent/f171.jpg",
        "MetadataDirective": "COPY",
    }


def test_sync_to_s3_url_without_prefix(tmp_path, mocker) -> None:
    s3_client = mocker.patch("suntoday.utils.boto3.client").return_value
    file = tmp_path / "2026" / "07" / "13" / "f171.jpg"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"jpeg")

    sync_to_s3([file], "s3://my-bucket", tmp_path)

    call = s3_client.upload_file.call_args
    assert call.args[1] == "my-bucket"
    assert call.args[2] == "2026/07/13/f171.jpg"


def test_sync_to_s3_rejects_files_outside_root(tmp_path, mocker) -> None:
    s3_client = mocker.patch("suntoday.utils.boto3.client").return_value
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside.jpg"
    outside = tmp_path / "outside.jpg"
    inside.write_bytes(b"jpeg")
    outside.write_bytes(b"jpeg")

    with pytest.raises(ValueError, match="file is outside root directory"):
        sync_to_s3([inside, outside], "my-bucket", root)

    s3_client.upload_file.assert_not_called()


def test_save_fits_removes_blank(tmp_path) -> None:
    amap = create_aia_map(find_test_filepath("171"))
    amap.meta["blank"] = 0

    with warnings.catch_warnings():
        warnings.simplefilter("error", VerifyWarning)
        path = save_fits(amap, tmp_path, "f0171.fits")
        with fits.open(path) as hdus:
            assert "BLANK" not in hdus[1].header
