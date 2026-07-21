"""
Main module for the SunToday application.

This module contains the main entry point for the application, as well
as the scheduled jobs for creating JPEG images and timeseries data.
"""

import argparse
import datetime
import functools
import os
import time
from pathlib import Path

import schedule
import sentry_sdk
from sentry_sdk.integrations.serverless import serverless_function
from sqlalchemy.orm import Session, sessionmaker
from sunpy.time import parse_time

from suntoday import logger
from suntoday.config import Settings
from suntoday.db import create_db, get_latest_record, get_record, write_or_update_record
from suntoday.downloaders.adapt import find_nearest_adapt_time
from suntoday.downloaders.jsoc import find_latest_jsoc_times, find_latest_pfss_time
from suntoday.jpegs import create_sdo_images
from suntoday.lightcurve import create_lightcurve_figure
from suntoday.utils import sync_to_s3

if os.getenv("SUNTODAY_TEST_ENV", "False") != "True":
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
            # Blanket catch by design: a failing scheduled job must be logged
            # and swallowed, never kill the scheduler loop.
            except Exception as e:  # ruff:ignore[blind-except]
                logger.exception(f"Error occurred in job {job_func.__name__}: {e}")
                if cancel_on_failure:
                    return schedule.CancelJob

        return wrapper

    return catch_exceptions_decorator


def _build_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SunToday scheduler or one-off job.")
    parser.add_argument(
        "--date",
        "--requested-time",
        dest="requested_time",
        help="Date or datetime (YYYY-MM-DD or ISO-8601). If omitted, start the scheduler.",
    )
    parser.add_argument(
        "--root-save-directory",
        dest="root_save_directory",
        help="Override the root save directory for output.",
    )
    parser.add_argument(
        "--pfss",
        action="store_true",
        help="Run the PFSS overlay job instead of the main job (needs --date).",
    )
    return parser


def cli() -> None:
    """
    Allows one to call the code once if required.
    """
    parser = _build_args()
    args = parser.parse_args()
    root_save_directory = Path(args.root_save_directory) if args.root_save_directory else None
    if not args.requested_time:
        if args.pfss:
            parser.error("--pfss requires --date")
        scheduled()
        return
    requested_time = parse_time(args.requested_time).to_datetime(timezone=datetime.UTC)
    job = pfss_job if args.pfss else main_job
    job(requested_time=requested_time, root_save_directory=root_save_directory)
    return


@serverless_function
def create_images(
    database_session: Session,
    image_type: str,
    requested_time: datetime.datetime,
    save_directory: Path,
    hmi_time: datetime.datetime | None = None,
    *,
    adapt_epoch: datetime.datetime | None = None,
) -> list[Path]:
    """
    Create images for the requested time.

    It checks if the nearest record and the observation date are within a
    reasonable range. If not, it creates the images. The success record is
    written by the caller (`_run_job`) only after the files are published,
    so a failed upload is retried on the next run.

    Parameters
    ----------
    database_session : Session
        The SQLAlchemy session to use for database operations.
    image_type : str
        The type of images to create: "images", "timeseries" or "pfss".
    requested_time : datetime.datetime
        The date for which to create images.
    save_directory : Path
        The directory where the images will be saved.
    hmi_time : datetime.datetime, optional
        Datetime for the HMI data, which lags AIA. Only used for "images";
        defaults to ``requested_time``.
    adapt_epoch : datetime.datetime, optional
        ADAPT map timestamp for a PFSS run. A matching persisted epoch skips
        regeneration, including after a container restart.

    Returns
    -------
    list of pathlib.Path
        Created files, or an empty list when creation is skipped.

    Raises
    ------
    ValueError
        If the image_type is not "images", "timeseries" or "pfss".
    """
    if image_type not in {"images", "timeseries", "pfss"}:
        msg = f"Invalid image type: {image_type}. Must be 'images', 'timeseries' or 'pfss'."
        raise ValueError(msg)
    requested_time = requested_time.astimezone(datetime.UTC)
    if image_type == "pfss" and adapt_epoch is not None:
        latest_record = get_latest_record(database_session, image_type)
        is_current = latest_record is not None and latest_record.adapt_epoch == adapt_epoch
    else:
        latest_record = get_record(database_session, image_type, requested_time.date())
        is_current = latest_record is not None and latest_record.updated_at > requested_time - datetime.timedelta(
            minutes=10
        )
    if is_current:
        logger.info(f"{image_type} for {requested_time} are already current, skipping creation.")
        return []
    if image_type in {"images", "pfss"}:
        created_files = create_sdo_images(requested_time, save_directory, hmi_time=hmi_time, pfss=image_type == "pfss")
    else:
        created_files = create_lightcurve_figure(requested_time, save_directory)
    logger.info(f"{image_type} creation completed")
    return created_files


def _run_job(
    image_types: list[str],
    requested_time: datetime.datetime,
    root_save_directory: Path | None,
    hmi_time: datetime.datetime | None = None,
    adapt_epoch: datetime.datetime | None = None,
) -> None:
    """
    Shared job scaffolding: build the dated save directory, run the image
    creation for each type on one database session and sync to S3.

    Parameters
    ----------
    image_types : list of str
        The `create_images` types to run, in order.
    requested_time : datetime.datetime
        The time to create images for.
    root_save_directory : Path | None
        Root output directory; defaults to the configured one.
    hmi_time : datetime.datetime, optional
        Datetime for the HMI data, only used by the "images" type.
    adapt_epoch : datetime.datetime, optional
        ADAPT map timestamp to persist after a successful PFSS upload.
    """
    settings = Settings()
    requested_time = requested_time.astimezone(datetime.UTC)
    root_save_directory = Path(root_save_directory or settings.save_directory).expanduser().resolve()
    save_directory = (
        root_save_directory
        / requested_time.strftime("%Y")
        / requested_time.strftime("%m")
        / requested_time.strftime("%d")
    )
    save_directory.mkdir(parents=True, exist_ok=True)
    logger.info(f"Requested time: {requested_time}, Save directory: {save_directory}")
    engine = create_db()
    session = None
    try:
        session = sessionmaker(bind=engine)()
        created_by_type = {}
        for image_type in image_types:
            logger.info(f"Creating {image_type}")
            created = create_images(
                session,
                image_type,
                requested_time,
                save_directory,
                hmi_time=hmi_time,
                adapt_epoch=adapt_epoch,
            )
            if created:
                created_by_type[image_type] = created
        created_files = [file for files in created_by_type.values() for file in files]
        if settings.s3_bucket and created_files:
            logger.info(f"Uploading {len(created_files)} files to {settings.s3_bucket}")
            sync_to_s3(created_files, settings.s3_bucket, root_save_directory)
        # Records only after a successful upload: marking success first would
        # make the next run skip regeneration and leave S3 partially updated.
        for image_type in created_by_type:
            if image_type == "pfss":
                write_or_update_record(
                    session,
                    image_type,
                    str(requested_time.date()),
                    updated_at=str(requested_time),
                    adapt_epoch=adapt_epoch,
                )
            else:
                write_or_update_record(session, image_type, str(requested_time.date()), updated_at=str(requested_time))
    finally:
        if session is not None:
            session.close()
        engine.dispose()


def main_job(requested_time: datetime.datetime | None = None, root_save_directory: Path | None = None) -> None:
    """
    Main job to create SDO Images and lightcurve images.

    This function is scheduled to run periodically based on the cron
    frequency defined in the settings. It creates SDO Images and
    lightcurve images for the requested time, or the current time if not
    specified.
    """
    logger.info("Running main job to create SDO Images and lightcurve images")
    # Live scheduled runs use the freshest time each instrument has data
    # for; explicit backfill runs use the given time as-is for both.
    if requested_time is None:
        requested_time, hmi_time = find_latest_jsoc_times()
    else:
        requested_time = requested_time.astimezone(datetime.UTC)
        hmi_time = None
    _run_job(["images", "timeseries"], requested_time, root_save_directory, hmi_time=hmi_time)
    logger.info("Main job completed")


def pfss_job(requested_time: datetime.datetime | None = None, root_save_directory: Path | None = None) -> None:
    """
    Job to create the matched-time PFSS overlay images.

    Scheduled runs use the newest matched-data anchor; explicit runs use
    the requested time. Both persist the ADAPT epoch only after
    successful upload.
    """
    logger.info("Running PFSS job to create field line overlay images")
    requested_time = find_latest_pfss_time() if requested_time is None else requested_time.astimezone(datetime.UTC)
    adapt_epoch = find_nearest_adapt_time(requested_time)
    _run_job(["pfss"], requested_time, root_save_directory, adapt_epoch=adapt_epoch)
    logger.info("PFSS job completed")


@serverless_function
def scheduled() -> None:
    """
    Main function to start the scheduled job.
    """
    settings = Settings()
    scheduled_job = catch_exceptions(cancel_on_failure=False)(main_job)
    scheduled_pfss = catch_exceptions(cancel_on_failure=False)(pfss_job)
    logger.info(f"Starting main job with cron frequency: {settings.cron_frequency} minutes")
    schedule.every(settings.cron_frequency).minutes.do(scheduled_job)
    schedule.every(settings.cron_frequency).minutes.do(scheduled_pfss)
    logger.info("Running first job immediately")
    scheduled_job()
    scheduled_pfss()
    logger.info(f"Next job in {schedule.idle_seconds()} seconds")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    cli()
