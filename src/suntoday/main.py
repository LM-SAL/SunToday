"""
Main module for the SunToday application.

This module contains the main entry point for the application, as well
as the scheduled jobs for creating JPEG images and timeseries data.
"""

import argparse
import contextlib
import datetime
import functools
import multiprocessing
import os
import tempfile
import time
import traceback
from pathlib import Path

import schedule
import sentry_sdk
from sentry_sdk.integrations.serverless import serverless_function
from sqlalchemy.orm import Session, sessionmaker
from sunpy.time import parse_time

from suntoday import DataNotReadyError, logger
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
        ignore_errors=[DataNotReadyError],
    )


def _job_entrypoint(job_func, error_connection) -> None:
    """
    Child-process wrapper: normal processing lag exits with ``EX_TEMPFAIL``
    instead of crashing, so it never reaches Sentry; the staleness alert pages
    if the lag persists.

    Raises
    ------
    SystemExit
        With ``os.EX_TEMPFAIL`` when the upstream data is not ready.
    """
    try:
        job_func()
    except DataNotReadyError as e:
        logger.warning(f"Job {job_func.__name__} skipped, data not ready: {e}")
        raise SystemExit(os.EX_TEMPFAIL) from None
    except Exception:
        with contextlib.suppress(OSError):
            error_connection.send(traceback.format_exc())
        raise
    finally:
        error_connection.close()


def _run_job_in_subprocess(job_func) -> None:
    """
    Run a scheduled job in a fresh spawned process.

    CPython does not return freed heap to the OS, so running the heavy
    jobs in the scheduler process ratchets its RSS up to the job peak
    forever; a child process hands the memory back when it exits. A
    dying job (OOM kill, segfault) also cannot take the scheduler loop
    down. Tracebacks from ordinary child exceptions are sent back over a
    pipe so the parent can include them in the scheduled-job log.
    """
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    try:
        process = context.Process(target=_job_entrypoint, args=(job_func, child_connection), name=job_func.__name__)
        process.start()
        process.join()
        child_traceback = parent_connection.recv() if parent_connection.poll() else None
    # Blanket catch by design: a failing scheduled job must be logged
    # and swallowed, never kill the scheduler loop.
    except Exception as e:  # ruff:ignore[blind-except]
        logger.exception(f"Error occurred running job {job_func.__name__}: {e}")
        return
    finally:
        child_connection.close()
        parent_connection.close()

    if process.exitcode == os.EX_TEMPFAIL:
        logger.warning(f"Job {job_func.__name__} skipped: data not ready")
    elif process.exitcode != 0:
        suffix = f"\nChild traceback:\n{child_traceback.rstrip()}" if child_traceback else ""
        logger.error(f"Job {job_func.__name__} exited with code {process.exitcode}{suffix}")
    if process.exitcode != 0:
        try:
            _alert_if_stale()
        # A failed child has no reusable session, so check from the parent.
        except Exception as e:  # ruff:ignore[blind-except]
            logger.exception(f"Error checking stale data: {e}")


def _alert_if_stale(session: Session | None = None) -> None:
    """
    Page once per incident when the newest data is older than the threshold.

    Per-run "no data yet" skips stay silent because transient JSOC/ADAPT
    lag self-heals; data that stops updating for any reason eventually
    breaches the threshold and alerts, so nothing has to distinguish
    "slow" from "broken" at run time.
    """
    owns_session = session is None
    if owns_session:
        engine = create_db()
        session = sessionmaker(bind=engine)()
    logger.info("Checking data freshness")
    settings = Settings()
    try:
        for image_type in ("images", "timeseries", "pfss"):
            record = get_latest_record(session, image_type)
            updated_at = record.updated_at if record is not None else None
            if updated_at is not None and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=datetime.UTC)
            if updated_at is not None:
                age = datetime.datetime.now(datetime.UTC) - updated_at
                if age <= datetime.timedelta(hours=settings.stale_alert_hours):
                    continue
                logger.error(f"Stale data: newest {image_type} record is {age.total_seconds() / 3600:.1f}h old")
            else:
                logger.error(f"Stale data: no {image_type} record exists")
            # Static message so Sentry groups every occurrence into one issue
            # and alerts once per incident, not once per run.
            sentry_sdk.capture_message(f"SunToday {image_type} data is stale", level="error")
        logger.info("Data freshness check completed")
    finally:
        if owns_session:
            session.close()
            engine.dispose()


def _build_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SunToday scheduler or one-off job.")
    parser.add_argument(
        "--date",
        "--requested-time",
        dest="requested_time",
        help=(
            "Date or datetime (YYYY-MM-DD or ISO-8601). A bare date uses the last "
            "images of that day. If omitted, start the scheduler."
        ),
    )
    parser.add_argument(
        "--root-save-directory",
        dest="root_save_directory",
        help="Override the root save directory for output.",
    )
    parser.add_argument(
        "--pfss",
        action="store_true",
        help="Also run the PFSS overlay job after the main job (needs --date).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if the database says the images are already current (needs --date).",
    )
    return parser


def cli() -> None:
    """
    Parse the CLI arguments: run a one-off main job when ``--date`` is given
    (plus the PFSS job with ``--pfss``), otherwise start the scheduler.

    Raises
    ------
    SystemExit
        With ``os.EX_TEMPFAIL`` when the archives have no data for the
        requested time.
    """
    parser = _build_args()
    args = parser.parse_args()
    root_save_directory = Path(args.root_save_directory) if args.root_save_directory else None
    if not args.requested_time:
        if args.pfss:
            parser.error("--pfss requires --date")
        if args.force:
            parser.error("--force requires --date")
        scheduled()
        return
    try:
        # A bare date means the end state of that day: anchor to 23:57 so the
        # 3-minute forward AIA fetch window stays inside the day and the
        # 24-hour lightcurve covers the requested day, not the one before.
        # Detected by parsing, not zeroed time components, so an explicit
        # midnight datetime still means midnight.
        bare_date = datetime.date.fromisoformat(args.requested_time.strip())
        requested_time = datetime.datetime.combine(bare_date, datetime.time(23, 57), tzinfo=datetime.UTC)
    except ValueError:
        requested_time = parse_time(args.requested_time).to_datetime(timezone=datetime.UTC)
    # One download directory across both jobs: the PFSS pass reuses the
    # AIA/HMI FITS files the main job already fetched for the same time.
    with tempfile.TemporaryDirectory() as shared_downloads:
        download_directory = Path(shared_downloads)
        try:
            main_job(
                requested_time=requested_time,
                root_save_directory=root_save_directory,
                force=args.force,
                download_directory=download_directory,
            )
            if args.pfss:
                pfss_job(
                    requested_time=requested_time,
                    root_save_directory=root_save_directory,
                    force=args.force,
                    download_directory=download_directory,
                )
        # A one-off backfill of a time the archives have no data for is not
        # a bug worth a Sentry event; report it on the exit code instead.
        except DataNotReadyError as e:
            logger.warning(f"Data not ready: {e}")
            raise SystemExit(os.EX_TEMPFAIL) from None
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
    force: bool = False,
    download_directory: Path | None = None,
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
    force : bool, optional
        Regenerate even when the database record says the images are
        already current.
    download_directory : pathlib.Path, optional
        Shared FITS download directory, passed through to
        `~suntoday.jpegs.create_sdo_images` so consecutive jobs for the
        same time fetch the data once.

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
    if not force:
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
        created_files = create_sdo_images(
            requested_time,
            save_directory,
            hmi_time=hmi_time,
            pfss=image_type == "pfss",
            download_directory=download_directory,
        )
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
    *,
    force: bool = False,
    update_mostrecent: bool = True,
    download_directory: Path | None = None,
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
    force : bool, optional
        Regenerate even when the database record says the images are
        already current.
    update_mostrecent : bool, optional
        Also mirror the files to the ``mostrecent/`` prefix. Disabled for
        explicit ``--date`` backfills so old data never replaces the
        latest images on the webpage.
    download_directory : pathlib.Path, optional
        Shared FITS download directory for `create_images`.
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
                force=force,
                download_directory=download_directory,
            )
            if created:
                created_by_type[image_type] = created
        created_files = [file for files in created_by_type.values() for file in files]
        if settings.s3_bucket and created_files:
            logger.info(f"Uploading {len(created_files)} files to {settings.s3_bucket}")
            sync_to_s3(created_files, settings.s3_bucket, root_save_directory)
            if update_mostrecent:
                # Mirror to a fixed mostrecent/ prefix so the webpage has stable URLs
                # for the latest images. Keys are bare filenames (root is the dated
                # directory), so each run overwrites the previous set.
                sync_to_s3(created_files, f"{settings.s3_bucket.rstrip('/')}/mostrecent", save_directory)
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
            try:
                _alert_if_stale(session)
            # Staleness reporting must not be able to stop the job.
            except Exception as e:  # ruff:ignore[blind-except]
                logger.exception(f"Error checking stale data: {e}")
        if session is not None:
            session.close()
        engine.dispose()


def main_job(
    requested_time: datetime.datetime | None = None,
    root_save_directory: Path | None = None,
    *,
    force: bool = False,
    download_directory: Path | None = None,
) -> None:
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
    is_live = requested_time is None
    if requested_time is None:
        requested_time, hmi_time = find_latest_jsoc_times()
    else:
        requested_time = requested_time.astimezone(datetime.UTC)
        hmi_time = None
    _run_job(
        ["images", "timeseries"],
        requested_time,
        root_save_directory,
        hmi_time=hmi_time,
        force=force,
        update_mostrecent=is_live,
        download_directory=download_directory,
    )
    logger.info("Main job completed")


def pfss_job(
    requested_time: datetime.datetime | None = None,
    root_save_directory: Path | None = None,
    *,
    force: bool = False,
    download_directory: Path | None = None,
) -> None:
    """
    Job to create the matched-time PFSS overlay images.

    Scheduled runs use the newest matched-data anchor; explicit runs use
    the requested time. Both persist the ADAPT epoch only after
    successful upload.
    """
    logger.info("Running PFSS job to create field line overlay images")
    is_live = requested_time is None
    requested_time = find_latest_pfss_time() if requested_time is None else requested_time.astimezone(datetime.UTC)
    adapt_epoch = find_nearest_adapt_time(requested_time)
    _run_job(
        ["pfss"],
        requested_time,
        root_save_directory,
        adapt_epoch=adapt_epoch,
        force=force,
        update_mostrecent=is_live,
        download_directory=download_directory,
    )
    logger.info("PFSS job completed")


@serverless_function
def scheduled() -> None:
    """
    Main function to start the scheduled job.
    """
    settings = Settings()
    scheduled_job = functools.partial(_run_job_in_subprocess, main_job)
    scheduled_pfss = functools.partial(_run_job_in_subprocess, pfss_job)
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
