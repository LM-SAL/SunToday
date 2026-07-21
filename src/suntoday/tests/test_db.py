from datetime import UTC, date, datetime

import pytest
from sqlalchemy import inspect

from suntoday.db import get_latest_record, get_record, write_or_update_record


def test_db_creation(db_session) -> None:
    session = db_session()
    inspector = inspect(session.bind)
    assert sorted(inspector.get_table_names()) == ["PFSSImages", "SDOImages", "TimeSeriesImages"]
    assert "adapt_epoch" in {column["name"] for column in inspector.get_columns("PFSSImages")}

    session.close()


def test_get_record_not_found(db_session) -> None:
    session = db_session()
    assert get_record(session, "images", "2021-01-01") is None

    session.close()


def test_write_and_get_record(db_session) -> None:
    session = db_session()
    write_or_update_record(
        session,
        "images",
        "2021-01-01+00:00",
        updated_at="2024-01-01+00:00",
    )
    sdo_image_db = get_record(session, "images", "2021-01-01+00:00")
    assert sdo_image_db == get_latest_record(session, "images")
    assert sdo_image_db.obs_date == date(2021, 1, 1)
    assert sdo_image_db.updated_at == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    session.close()


def test_update_record(db_session) -> None:
    session = db_session()
    write_or_update_record(
        session,
        "images",
        "2021-01-01+00:00",
        updated_at="2024-01-01+00:00",
    )
    write_or_update_record(
        session,
        "images",
        "2021-01-01+00:00",
        updated_at="2024-06-01+00:00",
    )
    session.expire_all()
    sdo_image_db = get_record(session, "images", "2021-01-01+00:00")
    assert sdo_image_db.updated_at == datetime(2024, 6, 1, 0, 0, tzinfo=UTC)

    session.close()


def test_write_or_update_record_invalid_model(db_session) -> None:
    session = db_session()
    with pytest.raises(ValueError, match="not allowed"):
        write_or_update_record(session, "invalid_model", "2021-01-01", updated_at="2024-01-01+00:00")

    session.close()
