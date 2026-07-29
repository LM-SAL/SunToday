from datetime import UTC, datetime, timedelta

import pytest
import sentry_sdk

from suntoday import DataNotReadyError, logger
from suntoday.db import PFSSImages, SDOImages, TimeSeriesImages, write_or_update_record
from suntoday.main import _alert_if_stale, _run_job_in_subprocess, cli, create_images, main_job, pfss_job


def test_sentry_disabled_during_tests() -> None:
    assert not sentry_sdk.get_client().is_active()


@pytest.fixture
def _clean_image_tables(db_session):
    """
    Clear the record tables so each test starts from an empty database.

    The ``db_session`` fixture is session-scoped, so rows written by
    earlier tests (e.g. in ``test_db``) would otherwise leak into these
    tests.
    """
    session = db_session()
    session.query(SDOImages).delete()
    session.query(TimeSeriesImages).delete()
    session.query(PFSSImages).delete()
    session.commit()
    session.close()


def test_create_images_invalid_type(mocker) -> None:
    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    with pytest.raises(ValueError, match="Invalid image type: invalid_type"):
        create_images("", "invalid_type", datetime.now(UTC), "")


@pytest.mark.usefixtures("_clean_image_tables")
def test_pfss_creation_skips_persisted_adapt_epoch(db_session, mocker, tmp_path) -> None:
    session = db_session()
    anchor = datetime(2026, 7, 20, 11, tzinfo=UTC)
    adapt_epoch = datetime(2026, 7, 20, 12, tzinfo=UTC)
    write_or_update_record(session, "pfss", str(anchor.date()), updated_at=str(anchor), adapt_epoch=adapt_epoch)
    create = mocker.patch("suntoday.main.create_sdo_images")

    assert create_images(session, "pfss", anchor, tmp_path, adapt_epoch=adapt_epoch) == []
    create.assert_not_called()
    session.close()


def test_cli_pfss_requires_date(mocker) -> None:
    mocker.patch("sys.argv", ["suntoday", "--pfss"])
    scheduled_mock = mocker.patch("suntoday.main.scheduled")

    with pytest.raises(SystemExit):
        cli()

    # Must not silently fall through to the scheduler.
    scheduled_mock.assert_not_called()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # A bare date anchors to the end of that day (23:57 keeps the
        # 3-minute forward AIA fetch window inside the day).
        ("2026-02-04", datetime(2026, 2, 4, 23, 57, tzinfo=UTC)),
        ("2026-02-04T12:30:00Z", datetime(2026, 2, 4, 12, 30, tzinfo=UTC)),
    ],
)
def test_cli_date_formats(value, expected, mocker) -> None:
    mocker.patch("sys.argv", ["suntoday", "--date", value])
    main_job_mock = mocker.patch("suntoday.main.main_job")

    cli()

    main_job_mock.assert_called_once_with(
        requested_time=expected, root_save_directory=None, force=False, download_directory=mocker.ANY
    )


@pytest.mark.parametrize("with_pfss", [False, True])
def test_cli_force_wires_through_to_jobs(with_pfss, mocker) -> None:
    argv = ["suntoday", "--date", "2026-02-04", "--force"]
    if with_pfss:
        argv.append("--pfss")
    mocker.patch("sys.argv", argv)
    main_mock = mocker.patch("suntoday.main.main_job")
    pfss_mock = mocker.patch("suntoday.main.pfss_job")

    cli()

    expected = {
        "requested_time": datetime(2026, 2, 4, 23, 57, tzinfo=UTC),
        "root_save_directory": None,
        "force": True,
        "download_directory": mocker.ANY,
    }
    main_mock.assert_called_once_with(**expected)
    # --pfss runs the PFSS job in addition to the main job, not instead,
    # and shares the download directory so the FITS files fetch once.
    if with_pfss:
        pfss_mock.assert_called_once_with(**expected)
        assert pfss_mock.call_args.kwargs["download_directory"] == main_mock.call_args.kwargs["download_directory"]
    else:
        pfss_mock.assert_not_called()


def test_cli_force_requires_date(mocker, capsys) -> None:
    mocker.patch("sys.argv", ["suntoday", "--force"])
    scheduled_mock = mocker.patch("suntoday.main.scheduled")

    with pytest.raises(SystemExit):
        cli()

    # parser.error exits with the message on stderr, not in the exception.
    assert "--force requires --date" in capsys.readouterr().err
    scheduled_mock.assert_not_called()


def _child_job_ok() -> None:
    pass


def _child_job_fails() -> None:
    raise SystemExit(3)


def _child_job_not_ready() -> None:
    msg = "JSOC still exporting"
    raise DataNotReadyError(msg)


def test_run_job_in_subprocess_isolates_child_exit(mocker) -> None:
    mocker.patch("suntoday.main._alert_if_stale")
    messages = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        # A dying child must not raise in the scheduler process, only log.
        _run_job_in_subprocess(_child_job_fails)
        _run_job_in_subprocess(_child_job_ok)
        # Data-not-ready is a warning-level skip, never an error.
        _run_job_in_subprocess(_child_job_not_ready)
    finally:
        logger.remove(sink_id)
    assert any("_child_job_fails exited with code 3" in message for message in messages)
    assert not any("_child_job_ok" in message for message in messages)
    assert any("_child_job_not_ready skipped: data not ready" in message for message in messages)
    assert not any("_child_job_not_ready exited" in message for message in messages)


def test_alert_if_stale_pages_only_beyond_threshold(mocker) -> None:
    mocker.patch("suntoday.main.create_db")
    mocker.patch("suntoday.main.sessionmaker")
    fresh = mocker.Mock(updated_at=datetime.now(UTC) - timedelta(hours=1))
    stale = mocker.Mock(updated_at=datetime.now(UTC) - timedelta(hours=7))
    # images fresh, timeseries stale, pfss has no record at all.
    mocker.patch("suntoday.main.get_latest_record", side_effect=[fresh, stale, None])
    capture = mocker.patch("suntoday.main.sentry_sdk.capture_message")

    _alert_if_stale()

    assert capture.call_args_list == [
        mocker.call("SunToday timeseries data is stale", level="error"),
        mocker.call("SunToday pfss data is stale", level="error"),
    ]


def test_main_job_uploads_only_created_files_and_propagates_failure(tmp_path, mocker) -> None:
    settings = mocker.patch("suntoday.main.Settings").return_value
    settings.s3_bucket = "my-bucket"
    engine = mocker.patch("suntoday.main.create_db").return_value
    session = mocker.patch("suntoday.main.sessionmaker").return_value.return_value
    created_file = tmp_path / "2026" / "07" / "13" / "f171.jpg"
    mocker.patch("suntoday.main.create_images", side_effect=[[created_file], []])
    record = mocker.patch("suntoday.main.write_or_update_record")
    upload = mocker.patch("suntoday.main.sync_to_s3", side_effect=RuntimeError("upload failed"))

    with pytest.raises(RuntimeError, match="upload failed"):
        main_job(datetime(2026, 7, 13, tzinfo=UTC), tmp_path)

    upload.assert_called_once_with([created_file], "my-bucket", tmp_path.resolve())
    # No success record on a failed upload: the next run must regenerate.
    record.assert_not_called()
    session.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_main_job_records_created_types_after_upload(tmp_path, mocker) -> None:
    settings = mocker.patch("suntoday.main.Settings").return_value
    settings.s3_bucket = "my-bucket"
    mocker.patch("suntoday.main.create_db")
    session = mocker.patch("suntoday.main.sessionmaker").return_value.return_value
    created_file = tmp_path / "2026" / "07" / "13" / "f171.jpg"
    mocker.patch("suntoday.main.create_images", side_effect=[[created_file], []])
    record = mocker.patch("suntoday.main.write_or_update_record")
    upload = mocker.patch("suntoday.main.sync_to_s3")

    requested_time = datetime(2026, 7, 13, tzinfo=UTC)
    main_job(requested_time, tmp_path)

    # An explicit --date backfill must not overwrite mostrecent/.
    assert upload.mock_calls == [
        mocker.call([created_file], "my-bucket", tmp_path.resolve()),
    ]
    # Only the type that created files gets a record, and only after upload.
    record.assert_called_once_with(session, "images", "2026-07-13", updated_at=str(requested_time))


def test_main_job_live_run_mirrors_mostrecent(tmp_path, mocker) -> None:
    settings = mocker.patch("suntoday.main.Settings").return_value
    settings.s3_bucket = "my-bucket"
    mocker.patch("suntoday.main.create_db")
    mocker.patch("suntoday.main.sessionmaker")
    created_file = tmp_path / "2026" / "07" / "13" / "f171.jpg"
    mocker.patch("suntoday.main.create_images", side_effect=[[created_file], []])
    mocker.patch("suntoday.main.write_or_update_record")
    upload = mocker.patch("suntoday.main.sync_to_s3")
    requested_time = datetime(2026, 7, 13, tzinfo=UTC)
    mocker.patch("suntoday.main.find_latest_jsoc_times", return_value=(requested_time, requested_time))

    main_job(root_save_directory=tmp_path)

    assert upload.mock_calls == [
        mocker.call([created_file], "my-bucket", tmp_path.resolve()),
        mocker.call([created_file], "my-bucket/mostrecent", tmp_path.resolve() / "2026" / "07" / "13"),
    ]


def test_pfss_job_records_adapt_epoch_after_upload(tmp_path, mocker) -> None:
    settings = mocker.patch("suntoday.main.Settings").return_value
    settings.s3_bucket = "my-bucket"
    mocker.patch("suntoday.main.create_db")
    session = mocker.patch("suntoday.main.sessionmaker").return_value.return_value
    created_file = tmp_path / "2026" / "07" / "13" / "f171pfss.jpg"
    mocker.patch("suntoday.main.create_images", return_value=[created_file])
    record = mocker.patch("suntoday.main.write_or_update_record")
    mocker.patch("suntoday.main.sync_to_s3")
    adapt_epoch = datetime(2026, 7, 13, 12, tzinfo=UTC)
    mocker.patch("suntoday.main.find_nearest_adapt_time", return_value=adapt_epoch)
    requested_time = datetime(2026, 7, 13, 11, tzinfo=UTC)
    mocker.patch("suntoday.main.find_latest_pfss_time", return_value=requested_time)

    pfss_job(root_save_directory=tmp_path)

    record.assert_called_once_with(
        session,
        "pfss",
        "2026-07-13",
        updated_at=str(requested_time),
        adapt_epoch=adapt_epoch,
    )


def test_create_images_dispatches_by_type(mocker, tmp_path) -> None:
    requested_time = datetime(2026, 7, 13, tzinfo=UTC)
    hmi_time = requested_time - timedelta(hours=1)
    image_file = tmp_path / "f171.jpg"
    lightcurve_file = tmp_path / "aia_light_curves.gif"
    mocker.patch("suntoday.main.get_record", return_value=None)
    create_sdo = mocker.patch("suntoday.main.create_sdo_images", return_value=[image_file])
    create_lightcurve = mocker.patch("suntoday.main.create_lightcurve_figure", return_value=[lightcurve_file])

    assert create_images(mocker.sentinel.session, "images", requested_time, tmp_path, hmi_time) == [image_file]
    assert create_images(mocker.sentinel.session, "timeseries", requested_time, tmp_path) == [lightcurve_file]
    create_sdo.assert_called_once_with(requested_time, tmp_path, hmi_time=hmi_time, pfss=False, download_directory=None)
    create_lightcurve.assert_called_once_with(requested_time, tmp_path)


def test_create_images_skips_recent_record(mocker, tmp_path) -> None:
    requested_time = datetime(2026, 7, 13, 12, tzinfo=UTC)
    recent_record = mocker.Mock(updated_at=requested_time - timedelta(minutes=5))
    mocker.patch("suntoday.main.get_record", return_value=recent_record)
    create_sdo = mocker.patch("suntoday.main.create_sdo_images")

    assert create_images(mocker.sentinel.session, "images", requested_time, tmp_path) == []
    create_sdo.assert_not_called()


def test_create_images_force_overrides_recent_record(mocker, tmp_path) -> None:
    requested_time = datetime(2026, 7, 13, 12, tzinfo=UTC)
    recent_record = mocker.Mock(updated_at=requested_time - timedelta(minutes=5))
    get_record = mocker.patch("suntoday.main.get_record", return_value=recent_record)
    image_file = tmp_path / "f171.jpg"
    create_sdo = mocker.patch("suntoday.main.create_sdo_images", return_value=[image_file])

    assert create_images(mocker.sentinel.session, "images", requested_time, tmp_path, force=True) == [image_file]
    create_sdo.assert_called_once()
    # force short-circuits the currency check entirely, no database query.
    get_record.assert_not_called()
