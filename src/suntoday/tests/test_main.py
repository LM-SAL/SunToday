from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suntoday.db import SDOImages, TimeSeriesImages
from suntoday.main import create_images, main_job


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
    session.commit()
    session.close()


def test_create_images_invalid_type(mocker) -> None:
    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    with pytest.raises(ValueError, match="Invalid image type: invalid_type"):
        create_images("", "invalid_type", datetime.now(UTC), "")


def test_main_job_uploads_only_created_files_and_propagates_failure(tmp_path, mocker) -> None:
    settings = mocker.patch("suntoday.main.Settings").return_value
    settings.s3_bucket = "my-bucket"
    engine = mocker.patch("suntoday.main.create_db").return_value
    session = mocker.patch("suntoday.main.sessionmaker").return_value.return_value
    created_file = tmp_path / "2026" / "07" / "13" / "f171.jpg"
    mocker.patch("suntoday.main.create_images", side_effect=[[created_file], []])
    upload = mocker.patch("suntoday.main.sync_to_s3", side_effect=RuntimeError("upload failed"))

    with pytest.raises(RuntimeError, match="upload failed"):
        main_job(datetime(2026, 7, 13, tzinfo=UTC), tmp_path)

    upload.assert_called_once_with([created_file], "my-bucket", tmp_path.resolve())
    session.close.assert_called_once()
    engine.dispose.assert_called_once()


@pytest.mark.remote_data
@pytest.mark.usefixtures("_clean_image_tables")
def test_timeseries_creation(db_session, mocker, tmpdir) -> None:
    session = db_session()
    assert session.query(TimeSeriesImages).count() == 0

    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    create_images(session, "timeseries", datetime.now(UTC), Path(tmpdir))

    assert session.query(TimeSeriesImages).count() == 1
    model = session.query(TimeSeriesImages).first()
    assert model.obs_date == datetime.now(UTC).date()
    assert model.updated_at <= datetime.now(UTC)
    old_updated_at = model.updated_at

    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    create_images(session, "timeseries", datetime.now(UTC), Path(tmpdir))
    assert session.query(TimeSeriesImages).count() == 1
    model = session.query(TimeSeriesImages).first()
    # No update to the existing record, its too soon
    assert model.updated_at == old_updated_at

    session.close()


@pytest.mark.remote_data
@pytest.mark.usefixtures("_clean_image_tables")
def test_images_creation(db_session, mocker, tmpdir) -> None:
    session = db_session()
    assert session.query(SDOImages).count() == 0

    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    # Hardcode the datetime to ensure consistent test results
    date = datetime.now(UTC) - timedelta(days=2)
    create_images(session, "images", date, Path(tmpdir))

    assert session.query(SDOImages).count() == 1
    model = session.query(SDOImages).first()
    assert model.obs_date == date.date()
    assert model.updated_at <= datetime.now(UTC)
    old_updated_at = model.updated_at

    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    # No update to the existing record, its too soon, frequency of updates is 10 minutes
    create_images(session, "images", date + timedelta(minutes=5), Path(tmpdir))
    assert session.query(SDOImages).count() == 1
    model = session.query(SDOImages).first()
    assert model.updated_at == old_updated_at

    # Over 10 minutes later, should update
    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    create_images(session, "images", date + timedelta(minutes=20), Path(tmpdir))
    assert session.query(SDOImages).count() == 1
    model = session.query(SDOImages).first()
    assert model.updated_at != old_updated_at

    session.close()
