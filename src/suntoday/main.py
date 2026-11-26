"""
The entry point: the scheduler, its two jobs, and the one-off ``--date`` run.
"""

import argparse
import contextlib
import datetime as dt
import functools
import logging
import multiprocessing
import os
import signal
import tempfile
import time
import traceback
from pathlib import Path

import schedule
import sentry_sdk
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.integrations.serverless import serverless_function
from sqlalchemy.orm import Session, sessionmaker
from sunpy.time import parse_time

from suntoday import DataNotReadyError, logger
from suntoday.config import Settings
from suntoday.db import create_db, get_latest_record, get_record, write_or_update_record
from suntoday.downloaders.jsoc import find_hmi_synoptic_time, find_latest_jsoc_times, find_latest_pfss_time
from suntoday.jpegs import create_sdo_images
from suntoday.lightcurve import create_lightcurve_figure
from suntoday.utils import sync_to_s3

_MAIN_JOB_TIMEOUT_SECONDS = 10 * 60
_PFSS_JOB_TIMEOUT_SECONDS = 75 * 60
_PROCESS_STOP_GRACE_SECONDS = 5


def _init_sentry(settings: Settings, **options) -> None:
    """
    Start Sentry with the production options; ``options`` are for tests.
    """
    sentry_sdk.init(
        dsn="https://a16063ea547141a4862651c80df74f68@o4505489018060800.ingest.sentry.io/4505489021337600",
        ignore_errors=[DataNotReadyError],
        server_name=settings.sentry_server_name,
        environment=settings.sentry_environment,
        # A job that dies abnormally is reported with logger.error, so error
        # logs must become Sentry events; the SDK only does that when asked.
        # level=None keeps it from also shipping every log line.
        integrations=[LoguruIntegration(level=None, event_level=logging.ERROR)],
        **options,
    )


settings = Settings()
# Test runs must stay out of the production Sentry.
if not settings.test_env:
    _init_sentry(settings)


def _exit_on_sigterm(signum, _frame) -> None:
    """
    Unwind on SIGTERM; its default action ends the process with no cleanup.
    """
    raise SystemExit(128 + signum)


def _job_entrypoint(job_func, error_connection, download_directory: Path) -> None:
    """
    Run one job in the child process.

    Upstream lag (`DataNotReadyError`) is not a crash: it exits with
    ``EX_TEMPFAIL`` and never reaches Sentry, and the staleness alert pages
    if it persists. Any other exception goes to Sentry, and its traceback
    to the parent.

    Raises
    ------
    SystemExit
        With ``os.EX_TEMPFAIL`` when the upstream data is not ready.
    """
    # The parent's terminate() must unwind the job so the database session
    # closes and atomic_save staging files on the NFS share are unlinked.
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        job_func(download_directory=download_directory)
    except DataNotReadyError as e:
        logger.warning(f"Job {job_func.__name__} skipped, data not ready: {e}")
        raise SystemExit(os.EX_TEMPFAIL) from None
    except Exception:
        # multiprocessing catches the re-raise before sys.excepthook fires,
        # so Sentry only sees the exception if captured here.
        sentry_sdk.capture_exception()
        sentry_sdk.flush()
        with contextlib.suppress(OSError):
            error_connection.send(traceback.format_exc())
        raise
    finally:
        error_connection.close()


def _run_job_in_subprocess(job_func, image_types: tuple[str, ...]) -> None:
    """
    Run a scheduled job in a fresh spawned process.

    CPython does not return freed heap to the OS, so a job run in the
    scheduler itself would hold its memory at the job's peak forever. A
    child gives it back on exit, and cannot take the scheduler down when it
    dies (OOM kill, segfault). Its traceback comes back over a pipe for the
    log.

    The FITS download directory belongs to this process: a killed child
    cannot clean up, and a few such leaks would fill the ``/tmp`` tmpfs for
    every later job.
    """
    timeout = _PFSS_JOB_TIMEOUT_SECONDS if image_types == ("pfss",) else _MAIN_JOB_TIMEOUT_SECONDS
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    try:  # ruff:ignore[too-many-statements-in-try-clause]
        with tempfile.TemporaryDirectory() as download_directory:
            process = context.Process(
                target=_job_entrypoint,
                args=(job_func, child_connection, Path(download_directory)),
                name=job_func.__name__,
            )
            try:
                process.start()
                deadline = time.monotonic() + timeout
                # Only the child holds the write end now, so its exit reads as
                # EOF. Receive before joining: a traceback larger than the
                # pipe buffer blocks the child's send until it is read, and
                # joining first would leave the scheduler waiting forever.
                child_connection.close()
                child_traceback = None
                if parent_connection.poll(timeout):
                    # EOFError: exited without a traceback. OSError: died mid-send.
                    with contextlib.suppress(EOFError, OSError):
                        child_traceback = parent_connection.recv()
                process.join(max(0, deadline - time.monotonic()))
                timed_out = process.is_alive()
            # Also reached when the scheduler itself is stopped (SIGTERM). An
            # orphaned job would be SIGKILLed mid-write by the container
            # teardown, leaving its staging files on the NFS share; one that
            # cannot unwind within the grace period still can.
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(_PROCESS_STOP_GRACE_SECONDS)
                    if process.is_alive():
                        process.kill()
                        process.join()
    # Blanket catch by design: a failing scheduled job must be logged
    # and swallowed, never kill the scheduler loop.
    except Exception as e:  # ruff:ignore[blind-except]
        logger.exception(f"Error occurred running job {job_func.__name__}: {e}")
        return
    finally:
        child_connection.close()
        parent_connection.close()

    if timed_out:
        logger.error(f"Job {job_func.__name__} timed out after {timeout:g} seconds and was stopped")
    elif process.exitcode == os.EX_TEMPFAIL:
        logger.warning(f"Job {job_func.__name__} skipped: data not ready")
    elif process.exitcode != 0:
        suffix = f"\nChild traceback:\n{child_traceback.rstrip()}" if child_traceback else ""
        # A received traceback means the child already sent the exception to
        # Sentry; error level (a Sentry event) is reserved for abnormal deaths
        # (OOM kill, segfault) that would otherwise go unreported.
        log = logger.warning if child_traceback else logger.error
        log(f"Job {job_func.__name__} exited with code {process.exitcode}{suffix}")
    if process.exitcode != 0:
        try:
            _alert_if_stale(image_types=image_types)
        # A failed child has no reusable session, so check from the parent.
        except Exception as e:  # ruff:ignore[blind-except]
            logger.exception(f"Error checking stale data: {e}")


def _alert_if_stale(
    session: Session | None = None,
    image_types: list[str] | tuple[str, ...] = ("images", "timeseries", "pfss"),
) -> None:
    """
    Page once per incident when the newest data is older than the threshold.

    A single "no data yet" skip stays silent, because JSOC lag heals
    itself. Data that stops updating for any reason crosses the
    threshold and alerts, so nothing has to tell "slow" from "broken" at
    run time.
    """
    owns_session = session is None
    if owns_session:
        engine = create_db()
        session = sessionmaker(bind=engine)()
    logger.info("Checking data freshness")
    settings = Settings()
    try:
        for image_type in image_types:
            record = get_latest_record(session, image_type)
            updated_at = record.updated_at if record is not None else None
            if updated_at is not None and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=dt.UTC)
            if updated_at is not None:
                age = dt.datetime.now(dt.UTC) - updated_at
                if age <= dt.timedelta(hours=settings.stale_alert_hours):
                    continue
                # Warning, not error: an error would be its own Sentry event
                # with a different message every run; the static
                # capture_message below is the single paging channel.
                logger.warning(f"Stale data: newest {image_type} record is {age.total_seconds() / 3600:.1f}h old")
            else:
                logger.warning(f"Stale data: no {image_type} record exists")
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
    Run the scheduler, or a one-off job when ``--date`` is given.

    Raises
    ------
    SystemExit
        With ``os.EX_TEMPFAIL`` when the archives have no data for the
        requested time.
    """
    # `docker stop` sends SIGTERM; unwinding on it is what lets a running job
    # be stopped cleanly (see _run_job_in_subprocess) before the process ends.
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
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
        bare_date = dt.date.fromisoformat(args.requested_time.strip())
        requested_time = dt.datetime.combine(bare_date, dt.time(23, 57), tzinfo=dt.UTC)
    except ValueError:
        requested_time = parse_time(args.requested_time).to_datetime(timezone=dt.UTC)
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


def create_images(
    database_session: Session,
    image_type: str,
    requested_time: dt.datetime,
    save_directory: Path,
    hmi_time: dt.datetime | None = None,
    *,
    boundary_epoch: dt.datetime | None = None,
    force: bool = False,
    download_directory: Path | None = None,
) -> list[Path]:
    """
    Create one type of product for a time, unless it is already current.

    The success record is written by the caller (`_run_job`) only after the
    files are published, so a failed upload is retried on the next run.

    Parameters
    ----------
    database_session : Session
        Session used to look up the last render.
    image_type : str
        "images", "timeseries" or "pfss".
    requested_time : datetime.datetime
        Time of the data to render.
    save_directory : Path
        Where the products are written.
    hmi_time : datetime.datetime, optional
        Time for the HMI data, which lags AIA. Only used for "images";
        defaults to ``requested_time``.
    boundary_epoch : datetime.datetime, optional
        Boundary-map time for a PFSS run. A record with the same epoch
        counts as current, and the same epoch pins the boundary download,
        so the lines drawn and the record always describe one HMI frame.
    force : bool, optional
        Render even if the record says the products are current.
    download_directory : pathlib.Path, optional
        FITS download directory shared by the jobs for one time, so the
        data is fetched once.

    Returns
    -------
    list of pathlib.Path
        Created files; empty when skipped.

    Raises
    ------
    ValueError
        If ``image_type`` is not one of the three types.
    """
    if image_type not in {"images", "timeseries", "pfss"}:
        msg = f"Invalid image type: {image_type}. Must be 'images', 'timeseries' or 'pfss'."
        raise ValueError(msg)
    requested_time = requested_time.astimezone(dt.UTC)
    if not force:
        # Current = already rendered from data less than one main-job
        # interval older than this request. PFSS uses it too: its own runs
        # are far further apart, so this only spares a re-render right after
        # a restart.
        cutoff = requested_time - dt.timedelta(minutes=Settings().cron_frequency)
        if image_type == "pfss" and boundary_epoch is not None:
            latest_record = get_latest_record(database_session, image_type)
            is_current = (
                latest_record is not None
                and latest_record.boundary_epoch == boundary_epoch
                and latest_record.updated_at > cutoff
            )
        else:
            latest_record = get_record(database_session, image_type, requested_time.date())
            is_current = latest_record is not None and latest_record.updated_at > cutoff
        if is_current:
            logger.info(f"{image_type} for {requested_time} are already current, skipping creation.")
            return []
    if image_type in {"images", "pfss"}:
        created_files = create_sdo_images(
            requested_time,
            save_directory,
            hmi_time=hmi_time,
            pfss=image_type == "pfss",
            boundary_time=boundary_epoch,
            download_directory=download_directory,
        )
    else:
        created_files = create_lightcurve_figure(requested_time, save_directory)
    logger.info(f"{image_type} creation completed")
    return created_files


def _run_job(
    image_types: list[str],
    requested_time: dt.datetime,
    root_save_directory: Path | None,
    hmi_time: dt.datetime | None = None,
    boundary_epoch: dt.datetime | None = None,
    *,
    force: bool = False,
    update_mostrecent: bool = True,
    download_directory: Path | None = None,
) -> None:
    """
    Render the given product types for one time, upload them, then record them.

    Parameters
    ----------
    image_types : list of str
        `create_images` types to run, in order.
    requested_time : datetime.datetime
        Time of the data to render.
    root_save_directory : Path | None
        Output root; the dated directory is created beneath it. Defaults to
        the configured one.
    hmi_time, boundary_epoch, force, download_directory
        Passed to `create_images`.
    update_mostrecent : bool, optional
        Also copy the files to the ``mostrecent/`` prefix. Off for ``--date``
        backfills, so old data never replaces the latest images on the
        webpage.
    """
    settings = Settings()
    requested_time = requested_time.astimezone(dt.UTC)
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
    session = sessionmaker(bind=engine)()
    try:
        created_by_type = {}
        for image_type in image_types:
            logger.info(f"Creating {image_type}")
            created = create_images(
                session,
                image_type,
                requested_time,
                save_directory,
                hmi_time=hmi_time,
                boundary_epoch=boundary_epoch,
                force=force,
                download_directory=download_directory,
            )
            if created:
                created_by_type[image_type] = created
        created_files = [file for files in created_by_type.values() for file in files]
        if settings.s3_bucket and created_files:
            logger.info(f"Uploading {len(created_files)} files to {settings.s3_bucket}")
            sync_to_s3(
                created_files,
                settings.s3_bucket,
                root_save_directory,
                mostrecent_root=save_directory if update_mostrecent else None,
            )
        # Records only after a successful upload: marking success first would
        # make the next run skip regeneration and leave S3 partially updated.
        for image_type in created_by_type:
            if image_type == "pfss":
                write_or_update_record(
                    session,
                    image_type,
                    requested_time.date(),
                    updated_at=requested_time,
                    boundary_epoch=boundary_epoch,
                )
            else:
                write_or_update_record(session, image_type, requested_time.date(), updated_at=requested_time)
    finally:
        try:
            _alert_if_stale(session, image_types)
        # Staleness reporting must not be able to stop the job.
        except Exception as e:  # ruff:ignore[blind-except]
            logger.exception(f"Error checking stale data: {e}")
        session.close()
        engine.dispose()


def main_job(
    requested_time: dt.datetime | None = None,
    root_save_directory: Path | None = None,
    *,
    force: bool = False,
    download_directory: Path | None = None,
) -> None:
    """
    Render the SDO image products and the lightcurve.

    A scheduled run (no ``requested_time``) uses the newest time each
    instrument has data for; an explicit time is used as given for both.
    """
    logger.info("Running main job to create SDO Images and lightcurve images")
    is_live = requested_time is None
    if requested_time is None:
        requested_time, hmi_time = find_latest_jsoc_times()
    else:
        requested_time = requested_time.astimezone(dt.UTC)
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
    requested_time: dt.datetime | None = None,
    root_save_directory: Path | None = None,
    *,
    force: bool = False,
    download_directory: Path | None = None,
) -> None:
    """
    Render the PFSS field line overlays.

    A scheduled run uses the newest time AIA and HMI both have data for;
    an explicit run uses the requested time. The HMI boundary epoch is
    recorded only after a successful upload.
    """
    logger.info("Running PFSS job to create field line overlay images")
    is_live = requested_time is None
    requested_time = find_latest_pfss_time() if requested_time is None else requested_time.astimezone(dt.UTC)
    boundary_epoch = find_hmi_synoptic_time(requested_time)
    _run_job(
        ["pfss"],
        requested_time,
        root_save_directory,
        boundary_epoch=boundary_epoch,
        force=force,
        update_mostrecent=is_live,
        download_directory=download_directory,
    )
    logger.info("PFSS job completed")


@serverless_function
def scheduled() -> None:
    """
    Run both jobs now, then on their schedules, forever.
    """
    settings = Settings()
    # Dead-man's-switch: Sentry pages when check-ins stop, i.e. when the
    # container/host/scheduler is down for any reason. The check-in comes from
    # the parent, so child job failures (already alerted) don't trip it.
    scheduled_job = sentry_sdk.monitor(
        monitor_slug="suntoday-scheduler",
        monitor_config={
            "schedule": {"type": "interval", "value": settings.cron_frequency, "unit": "minute"},
            "checkin_margin": settings.cron_frequency * 2,
            "max_runtime": 60,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
        },
    )(functools.partial(_run_job_in_subprocess, main_job, ("images", "timeseries")))
    scheduled_pfss = functools.partial(_run_job_in_subprocess, pfss_job, ("pfss",))
    logger.info(
        f"Starting jobs with cron frequency: {settings.cron_frequency} minutes "
        f"(pfss: {settings.pfss_cron_frequency} minutes)"
    )
    schedule.every(settings.cron_frequency).minutes.do(scheduled_job)
    schedule.every(settings.pfss_cron_frequency).minutes.do(scheduled_pfss)
    logger.info("Running first job immediately")
    scheduled_job()
    scheduled_pfss()
    logger.info(f"Next job in {schedule.idle_seconds()} seconds")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    cli()
