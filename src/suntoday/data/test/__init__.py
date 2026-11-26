from suntoday.data import DATA_ROOTDIR

__all__ = ["TEST_DATA_ROOTDIR", "find_test_filepath"]

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
        ``"synoptic"``.

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
