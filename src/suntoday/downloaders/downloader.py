"""
Contains SSL disabled downloaders due to the local proxy.

This won't be needed in production but it doesn't matter anyway.
"""

import ssl

from parfive import SessionConfig

__all__ = ["create_downloader"]

ssl._create_default_https_context = ssl._create_unverified_context  # NOQA: SLF001 S323


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
