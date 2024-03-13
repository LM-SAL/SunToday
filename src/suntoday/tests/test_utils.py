import numpy as np

from suntoday.utils import apply_gamma_correction, normalize_image_percentiles


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
