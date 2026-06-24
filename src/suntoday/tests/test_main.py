from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suntoday.db import SDOImages, TimeSeriesImages
from suntoday.main import create_images


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
