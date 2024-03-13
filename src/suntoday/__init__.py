import os
import sys

from loguru import logger

__all__ = ["change_logging_level", "logger"]


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
