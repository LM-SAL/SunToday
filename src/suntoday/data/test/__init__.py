from pathlib import Path

from astropy.utils.data import get_pkg_data_filename

from suntoday.data import DATA_ROOTDIR

__all__ = [
    "TEST_DATA_ROOTDIR",
    "get_test_filepath",
]

TEST_DATA_ROOTDIR = DATA_ROOTDIR / "test"


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
