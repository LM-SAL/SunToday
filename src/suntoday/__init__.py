import os
import sys

import matplotlib as mpl
from loguru import logger

__all__ = ["DataNotReadyError", "change_logging_level", "logger"]


class DataNotReadyError(Exception):
    """
    The upstream archive has no data for the requested time yet.

    This is normal processing lag (JSOC still exporting, boundary map
    not yet published), not a bug. Scheduled jobs skip the run and
    retry, and the staleness alert pages if it persists.
    """


def change_logging_level(level: str) -> None:
    """
    Send the log to stdout at ``level``, any loguru level name such as "INFO".
    """
    logger.remove()
    logger.add(sys.stdout, level=level)


change_logging_level(os.environ.get("SUNTODAY_LOG_LEVEL", "info").upper())
# Every figure renders with mplcairo (the blend product needs its screen
# operator). Selected once here, so no module depends on its import order.
mpl.use("module://mplcairo.base")
