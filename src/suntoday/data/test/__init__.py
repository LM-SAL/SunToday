from suntoday.data import DATA_ROOTDIR

__all__ = ["TEST_DATA_ROOTDIR", "find_test_filepath"]

TEST_DATA_ROOTDIR = DATA_ROOTDIR / "test"


def find_test_filepath(suffix):
    """
    Return the stored test FITS file whose name ends in ``_<suffix>.fits``.

    Found by suffix (an AIA wavelength such as ``"171"``, or
    ``"magnetogram"``, ``"continuum"``, ``"synoptic"``), so refreshing the
    data with ``tools/fetch_fits.py`` changes no call site.

    Returns
    -------
    pathlib.Path
        The file.

    Raises
    ------
    FileNotFoundError
        If no file matches.
    ValueError
        If several match, e.g. a stale file survived a refresh.
    """
    matches = sorted(TEST_DATA_ROOTDIR.glob(f"*_{suffix}.fits"))
    if not matches:
        msg = f"No test FITS file matching '*_{suffix}.fits' in {TEST_DATA_ROOTDIR}."
        raise FileNotFoundError(msg)
    if len(matches) > 1:
        msg = f"Multiple test FITS files for {suffix!r}: {[path.name for path in matches]}."
        raise ValueError(msg)
    return matches[0]
