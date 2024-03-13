from datetime import UTC, datetime
from pathlib import Path

import pytest

from suntoday.db import SDOImages, TimeSeriesImages
from suntoday.main import create_images


def test_create_images_invalid_type(mocker) -> None:
    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    with pytest.raises(ValueError, match="Invalid image type: invalid_type"):
        create_images("", "invalid_type", datetime.now(UTC), "")


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


def test_images_creation(db_session, mocker, tmpdir) -> None:
    session = db_session()
    assert session.query(SDOImages).count() == 0

    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    # Hardcode the datetime to ensure consistent test results
    create_images(session, "images", datetime(2025, 7, 23, 14, 0, 0, tzinfo=UTC), Path(tmpdir))

    assert session.query(SDOImages).count() == 1
    model = session.query(SDOImages).first()
    assert model.obs_date == datetime(2025, 7, 23, tzinfo=UTC).date()
    assert model.updated_at <= datetime.now(UTC)
    old_updated_at = model.updated_at

    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    create_images(session, "images", datetime(2025, 7, 23, 14, 9, 0, tzinfo=UTC), Path(tmpdir))
    assert session.query(SDOImages).count() == 1
    model = session.query(SDOImages).first()
    # No update to the existing record, its too soon
    assert model.updated_at == old_updated_at

    # Just over 10 minutes later, should update
    mocker.patch("suntoday.main.serverless_function", return_value=lambda x: x)
    create_images(session, "images", datetime(2025, 7, 23, 14, 15, 0, tzinfo=UTC), Path(tmpdir))
    assert session.query(SDOImages).count() == 1
    model = session.query(SDOImages).first()
    assert model.updated_at != old_updated_at

    session.close()
