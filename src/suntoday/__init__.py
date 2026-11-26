import os
import sys

import matplotlib as mpl
from loguru import logger

__all__ = ["DataNotReadyError", "change_logging_level", "logger"]


class DataNotReadyError(Exception):
    """
    The upstream archive has no data for the requested time yet.

    Raised on paths where an empty result means normal processing lag
    (JSOC still exporting, HMI boundary map not published) rather than a
    bug. Scheduled jobs treat it as "skip this run and retry later"; the
    staleness alert pages if it keeps happening.
    """


def change_logging_level(level: str) -> None:
    """
    Change the logging level of the logger.

    Parameters
    ----------
    level : str
        The level to change the logger to. Must be one of the following:
        "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"
    """
    logger.remove()
    logger.add(sys.stdout, level=level)


change_logging_level(os.environ.get("SUNTODAY_LOG_LEVEL", "info").upper())
# Every figure renders with mplcairo (the blend product needs its screen
# operator). Selected once here, so no module depends on its import order.
mpl.use("module://mplcairo.base")
