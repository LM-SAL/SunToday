"""
Main module for the SunToday application.

This module contains the main entry point for the application, as well
as the scheduled jobs for creating JPEG images and timeseries data.
"""

import datetime
import functools
import time
from pathlib import Path

import schedule
import sentry_sdk
from sentry_sdk.integrations.serverless import serverless_function
from sqlalchemy.orm import Session, sessionmaker

from suntoday import logger
from suntoday.config import Settings
from suntoday.db import create_db, get_record, write_or_update_record
from suntoday.jpegs import create_sdo_images
from suntoday.lightcurve import create_lightcurve_figure

sentry_sdk.init(
    dsn="https://a16063ea547141a4862651c80df74f68@o4505489018060800.ingest.sentry.io/4505489021337600",
)


def catch_exceptions(*, cancel_on_failure=False):
    """
    Stolen from https://github.com/schedule/schedule

    Parameters
    ----------
    cancel_on_failure : bool, optional
        If True, the job will be canceled on failure, by default False

    Returns
    -------
    function
        A decorator that wraps the job function to catch exceptions.
    """

    def catch_exceptions_decorator(job_func):
        @functools.wraps(job_func)
        def wrapper(*args, **kwargs):
            try:
                return job_func(*args, **kwargs)
            except Exception as e:  # NOQA : BLE001
                logger.exception(f"Error occurred in job {job_func.__name__}: {e}")
                if cancel_on_failure:
                    return schedule.CancelJob

        return wrapper

    return catch_exceptions_decorator


@serverless_function
def create_images(
    database_session: Session, image_type: str, requested_time: datetime.datetime, save_directory: Path
) -> None:
    """
    Create images for the requested time. It checks if the nearest record and
    the observation date are within a reasonable range. If not, it creates SDO
    images and updates the record in the database.

    Parameters
    ----------
    database_session : Session
        The SQLAlchemy session to use for database operations.
    image_type : str
        The type of images to create, either "images" or "timeseries".
    requested_time : datetime.datetime
        The date for which to create images.
    save_directory : Path
        The directory where the images will be saved.

    Raises
    ------
    ValueError
        If the image_type is not "images" or "timeseries".
    """
    if image_type not in {"images", "timeseries"}:
        msg = f"Invalid image type: {image_type}. Must be 'images' or 'timeseries'."
        raise ValueError(msg)
    requested_time = requested_time.astimezone(datetime.UTC)
    nearest_record = get_record(database_session, image_type, requested_time.date())
    if nearest_record is not None and nearest_record.updated_at > requested_time - datetime.timedelta(minutes=10):
        logger.info(f"{image_type} for {requested_time} are too new, skipping creation.")
        return
    logger.info(f"Creating {image_type} for {requested_time} in {save_directory}")
    if image_type == "images":
        create_sdo_images(requested_time, save_directory)
    if image_type == "timeseries":
        create_lightcurve_figure(requested_time, save_directory)
    logger.info(f"Updating {image_type} record for {requested_time} in the database.")
    write_or_update_record(
        database_session,
        image_type,
        requested_time.date(),
        updated_at=requested_time,
    )
    logger.info(f"{image_type} creation and record update completed")


@catch_exceptions(cancel_on_failure=True)
def main_job(requested_time: datetime.datetime | None = None, root_save_directory: Path | None = None) -> None:
    """
    Main job to create SDO Images and lightcurve images.

    This function is scheduled to run periodically based on the cron
    frequency defined in the settings. It creates SDO Images and
    lightcurve images for the requested time, or the current time if not
    specified.
    """
    logger.info("Running main job to create SDO Images and lightcurve images")
    settings = Settings()
    if requested_time is None:
        requested_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=settings.jsoc_delay)
    else:
        requested_time = requested_time.astimezone(datetime.UTC)
    root_save_directory = root_save_directory or settings.save_directory
    root_save_directory = Path(root_save_directory).expanduser().resolve()
    logger.info(f"Root save directory: {root_save_directory}")
    save_directory = (
        root_save_directory
        / requested_time.strftime("%Y")
        / requested_time.strftime("%m")
        / requested_time.strftime("%d")
    )
    save_directory.mkdir(parents=True, exist_ok=True)
    logger.info(f"Requested time: {requested_time}, Save directory: {save_directory}")
    logger.info("Checking and creating database if necessary")
    engine = create_db()
    try:
        session = sessionmaker(bind=engine)()
        logger.info("Creating SDO Images")
        create_images(session, "images", requested_time, save_directory)
        logger.info("Creating lightcurve images")
        create_images(session, "timeseries", requested_time, save_directory)
    except Exception as e:  # NOQA : BLE001
        logger.exception(f"Error occurred: {e}")
    finally:
        session.close()
        engine.dispose()
    logger.info("Main job completed")


@serverless_function
def main() -> None:
    """
    Main function to start the scheduled job.
    """
    settings = Settings()
    logger.info(f"Starting main job with cron frequency: {settings.cron_frequency} minutes")
    schedule.every(settings.cron_frequency).minutes.do(main_job)
    logger.info("Running first job immediately")
    main_job()
    logger.info(f"Next job in {schedule.idle_seconds()} seconds")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    logger.info("Starting main job")
    main()
