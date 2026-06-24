"""
Parfive downloader for the JSOC FITS files.

All JSOC endpoints are plain HTTP, so there is no TLS to configure here.
"""

from parfive import SessionConfig

__all__ = ["create_downloader"]


def create_session(*args, **kwargs):  # NOQA: ARG001
    from aiohttp import ClientSession, TCPConnector

    return ClientSession(connector=TCPConnector(ssl=False))


def create_downloader():
    """
    Creates a simple SSL disabled Parfive Downloader.

    Returns
    -------
    parfive.Downloader
    """
    from parfive import Downloader

    return Downloader(
        max_conn=5, max_splits=1, progress=False, config=SessionConfig(aiohttp_session_generator=create_session)
    )
