from datetime import UTC, date, datetime

import pytest
from sqlalchemy import inspect

from suntoday.db import SDOImages, TimeSeriesImages, get_latest_record, get_record, write_or_update_record


def test_db_creation(db_session) -> None:
    session = db_session()
    inspector = inspect(session.bind)
    assert inspector.get_table_names() == ["SDOImages", "TimeSeriesImages"]

    session.close()


def test_get_record_not_found(db_session) -> None:
    session = db_session()
    sdo_image_db = get_record(session, "images", "2021-01-01")
    time_series_db = get_record(session, "timeseries", "2023-01-01")

    assert sdo_image_db is None
    assert time_series_db is None

    session.close()


def test_write_and_get_record(db_session) -> None:
    session = db_session()
    write_or_update_record(
        session,
        "images",
        "2021-01-01+00:00",
        updated_at="2024-01-01+00:00",
    )
    write_or_update_record(session, "timeseries", "2023-01-01+00:00", updated_at="2026-01-01+00:00")

    sdo_image_db = get_record(session, "images", "2021-01-01+00:00")
    assert sdo_image_db == get_latest_record(session, "images")
    assert sdo_image_db.obs_date == date(2021, 1, 1)
    assert sdo_image_db.updated_at == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    timeseries_db = get_record(session, "timeseries", "2023-01-01+00:00")
    assert timeseries_db == get_latest_record(session, "timeseries")
    assert timeseries_db.obs_date == date(2023, 1, 1)
    assert timeseries_db.updated_at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    # Direct Tests - Just as insurance
    assert session.query(SDOImages).count() == 1
    assert session.query(TimeSeriesImages).count() == 1
    assert session.query(SDOImages).first().updated_at == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert session.query(TimeSeriesImages).first().obs_date == date(2023, 1, 1)

    session.close()


def test_update_record(db_session) -> None:
    session = db_session()
    write_or_update_record(
        session,
        "images",
        "2021-01-01+00:00",
        updated_at="2024-01-01+00:00",
    )
    sdo_image_db = get_record(session, "images", "2021-01-01+00:00")
    assert sdo_image_db.obs_date == date(2021, 1, 1)
    assert sdo_image_db.updated_at == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    write_or_update_record(
        session,
        "images",
        "2021-01-01+00:00",
        updated_at="2024-06-01+00:00",
    )
    sdo_image_db = get_record(session, "images", "2021-01-01+00:00")
    assert sdo_image_db.obs_date == date(2021, 1, 1)
    # This is a string as the test is not using a real database, so the type is not converted
    # to datetime automatically. I hope
    assert sdo_image_db.updated_at == "2024-06-01+00:00"

    session.close()


def test_write_or_update_record_invalid_model(db_session) -> None:
    session = db_session()
    with pytest.raises(ValueError, match="not allowed"):
        write_or_update_record(session, "invalid_model", "2021-01-01", updated_at="2024-01-01+00:00")

    session.close()
