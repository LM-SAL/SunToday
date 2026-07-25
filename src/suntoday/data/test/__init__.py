from pathlib import Path

from astropy.utils.data import get_pkg_data_filename

from suntoday.data import DATA_ROOTDIR

__all__ = [
    "TEST_DATA_ROOTDIR",
    "get_aia_test_filepath",
    "get_test_filepath",
]

TEST_DATA_ROOTDIR = DATA_ROOTDIR / "test"


def get_aia_test_filepath(wavelength):
    """
    Return the full path to the stored AIA test FITS file for a wavelength.

    Globbed rather than named so refreshing the test data with
    ``tools/fetch_fits.py`` does not need every call site updated.

    Parameters
    ----------
    wavelength : `str`
        Channel as it appears in the file name, e.g. ``"171"``.

    Returns
    -------
    filepath : `pathlib.Path`
        The full path to the file.
    """
    return next(TEST_DATA_ROOTDIR.glob(f"*_{wavelength}.fits"))


def get_test_filepath(filename, **kwargs):
    """
    Return the full path to a test file in the ``tests/data`` directory.

    Parameters
    ----------
    filename : `str`
        The name of the file inside the ``tests/data`` directory.

    Returns
    -------
    filepath : `str`
        The full path to the file.

    Notes
    -----
    This is a wrapper around `astropy.utils.data.get_pkg_data_filename` which
    sets the ``package`` kwarg to be ``suntoday.data.test``.
    """
    if isinstance(filename, Path):
        # NOTE: get_pkg_data_filename does not accept Path objects
        filename = filename.as_posix()
    return get_pkg_data_filename(filename, package="suntoday.data.test", **kwargs)
