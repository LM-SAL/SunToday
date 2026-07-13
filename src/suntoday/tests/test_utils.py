import numpy as np

from suntoday.utils import apply_gamma_correction, normalize_image_percentiles, sync_to_s3


def test_normalize_image_percentiles() -> None:
    image = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    normalized_image = normalize_image_percentiles(image)
    expected_result = np.array([[0, 31, 63], [95, 127, 159], [191, 223, 255]], dtype=np.uint8)
    assert np.array_equal(normalized_image, expected_result)


def test_apply_gamma_correction() -> None:
    image = np.array([[100, 150, 200], [50, 75, 100]])
    expected_result = np.array([[159, 195, 225], [112, 138, 159]])
    assert np.array_equal(apply_gamma_correction(image, gamma=0.5), expected_result)

    image = np.array([[100, 150, 200], [50, 75, 100]])
    expected_result = np.array([[100, 150, 200], [50, 75, 100]])
    assert np.array_equal(apply_gamma_correction(image, gamma=1.0), expected_result)

    image = np.array([[100, 150, 200], [50, 75, 100]])
    expected_result = np.array([[39, 88, 156], [9, 22, 39]])
    assert np.array_equal(apply_gamma_correction(image, gamma=2.0), expected_result)


def test_sync_to_s3(tmp_path, mocker) -> None:
    s3_client = mocker.patch("suntoday.utils.boto3.client").return_value
    day_directory = tmp_path / "2026" / "07" / "13"
    day_directory.mkdir(parents=True)
    (day_directory / "f171.jpg").write_bytes(b"jpeg")
    (day_directory / "aia171.fits").write_bytes(b"fits")

    sync_to_s3(list(day_directory.iterdir()), "my-bucket", tmp_path)

    calls = {call.args[2]: call for call in s3_client.upload_file.call_args_list}
    assert set(calls) == {"2026/07/13/f171.jpg", "2026/07/13/aia171.fits"}
    assert calls["2026/07/13/f171.jpg"].kwargs["ExtraArgs"] == {"ContentType": "image/jpeg"}
    assert calls["2026/07/13/f171.jpg"].args[1] == "my-bucket"


def test_sync_to_s3_with_prefix(tmp_path, mocker) -> None:
    s3_client = mocker.patch("suntoday.utils.boto3.client").return_value
    day_directory = tmp_path / "2026" / "07" / "13"
    day_directory.mkdir(parents=True)
    (day_directory / "f171.jpg").write_bytes(b"jpeg")

    sync_to_s3([day_directory / "f171.jpg"], "s3://suntoday.lmsal.com/sdomedia/SunInTime/", tmp_path)

    call = s3_client.upload_file.call_args
    assert call.args[1] == "suntoday.lmsal.com"
    assert call.args[2] == "sdomedia/SunInTime/2026/07/13/f171.jpg"
