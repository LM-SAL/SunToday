from pathlib import Path

from astropy.utils.data import get_pkg_data_filename

from suntoday.data import DATA_ROOTDIR

__all__ = [
    "TEST_DATA_ROOTDIR",
    "find_test_filepath",
    "get_test_filepath",
]

TEST_DATA_ROOTDIR = DATA_ROOTDIR / "test"


def find_test_filepath(suffix):
    """
    Return the full path to the stored test FITS file ending in a suffix.

    Globbed rather than named so refreshing the test data with
    ``tools/fetch_fits.py`` does not need every call site updated.

    Parameters
    ----------
    suffix : `str`
        Final underscore-separated part of the file name, e.g. an AIA
        wavelength (``"171"``) or ``"magnetogram"``, ``"continuum"``,
        ``"gong"``.

    Returns
    -------
    filepath : `pathlib.Path`
        The full path to the file.

    Raises
    ------
    FileNotFoundError
        If no file matches.
    ValueError
        If more than one file matches (e.g. a stale file survived a refresh).
    """
    matches = sorted(TEST_DATA_ROOTDIR.glob(f"*_{suffix}.fits"))
    if not matches:
        msg = f"No test FITS file matching '*_{suffix}.fits' in {TEST_DATA_ROOTDIR}."
        raise FileNotFoundError(msg)
    if len(matches) > 1:
        msg = f"Multiple test FITS files for {suffix!r}: {[path.name for path in matches]}."
        raise ValueError(msg)
    return matches[0]


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
