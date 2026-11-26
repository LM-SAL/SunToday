"""
Parfive downloader for the JSOC FITS files.

The JSOC is addressed over plain HTTP. Its HTTPS is not dependable, so
certificate verification is deliberately off for any download that ends
up on an HTTPS host; a tampered file would therefore not be detected.
"""

from parfive import SessionConfig

__all__ = ["create_downloader", "format_download_errors"]


def format_download_errors(errors) -> str:
    """
    Format parfive errors with their path, URL, and attached exception.
    """
    return "\n".join(
        f"  [{i}] url={e.url}\n      filepath_partial={e.filepath_partial!r}\n      exception={e.exception!r}"
        for i, e in enumerate(errors, 1)
    )


def create_session(*args, **kwargs):  # ruff:ignore[unused-function-argument]
    from aiohttp import ClientSession, TCPConnector

    return ClientSession(connector=TCPConnector(ssl=False))


def create_downloader():
    """
    Creates a Parfive Downloader that does not verify TLS certificates.

    Returns
    -------
    parfive.Downloader
    """
    from parfive import Downloader

    return Downloader(
        max_conn=5, max_splits=1, progress=False, config=SessionConfig(aiohttp_session_generator=create_session)
    )
