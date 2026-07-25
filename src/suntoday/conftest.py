import os

import pandas as pd
import pytest
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor
from sqlalchemy import create_engine
from sqlalchemy.orm.session import sessionmaker

from suntoday.data.test import get_test_filepath
from suntoday.db import BASE, SDOImages, TimeSeriesImages, get_session

os.environ["SUNTODAY_TEST_ENV"] = "True"

test_db = factories.postgresql_proc(port=None, dbname="test_db")


@pytest.fixture(scope="session")
def db_session(test_db):
    pg_host = test_db.host
    pg_port = test_db.port
    pg_user = test_db.user
    pg_password = test_db.password
    pg_db = test_db.dbname
    with DatabaseJanitor(
        user=pg_user, host=pg_host, port=pg_port, dbname=pg_db, version=test_db.version, password=pg_password
    ):
        connection_str = f"postgresql+psycopg2://{pg_user}:@{pg_host}:{pg_port}/{pg_db}"
        engine = create_engine(connection_str, echo=False, connect_args={"options": "-c timezone=utc"})
        BASE.metadata.create_all(engine)
        session = get_session(connection_str)
        assert session.query(SDOImages).count() == 0  # ruff:ignore[assert]
        assert session.query(TimeSeriesImages).count() == 0  # ruff:ignore[assert]
        session.close()
        yield sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def aia_timeseries():
    times = pd.date_range("2026-07-20", periods=25, freq="h", tz="UTC")
    frames = []
    for index, wavelength in enumerate(["94", "131", "171", "193", "211", "304", "335", "1600", "1700"]):
        baseline = 20.0 * (index + 1)
        frames.append(
            pd.DataFrame(
                {
                    "WAVELNTH": wavelength,
                    "DATAMEAN": [baseline + step for step in range(len(times))],
                    "QUALITY": "0x40000000",
                    "EXPTIME": 2.0,
                },
                index=times,
            )
        )
    return pd.concat(frames)


@pytest.fixture
def goes_primary_timeseries():
    times = pd.date_range("2026-07-20", periods=25, freq="h", tz="UTC")
    frames = []
    for energy, baseline in [("0.05-0.4nm", 1e-7), ("0.1-0.8nm", 1e-6)]:
        frames.append(
            pd.DataFrame(
                {
                    "satellite": 18,
                    "flux": [baseline * (1 + step / 100) for step in range(len(times))],
                    "energy": energy,
                },
                index=times,
            )
        )
    return pd.concat(frames)


@pytest.fixture
def real_aia_timeseries():
    timeseries = pd.read_csv(get_test_filepath("20260126_aia_timeseries.csv"), index_col=0, parse_dates=True)
    timeseries.index = pd.to_datetime(timeseries.index, format="mixed")
    return timeseries.astype({"WAVELNTH": str, "DATAMEAN": float, "EXPTIME": float})


@pytest.fixture
def real_goes_primary_timeseries():
    return pd.read_csv(get_test_filepath("20260126_goes_primary_timeseries.csv"), index_col=0, parse_dates=True)


@pytest.fixture(scope="session")
def adapt_test_file():
    return get_test_filepath("20260717_220000_adapt.fits")


@pytest.fixture
def hmi_cont_test_file():
    return get_test_filepath("20260717_221200_continuum.fits")


@pytest.fixture
def hmi_blos_test_file():
    return get_test_filepath("20260717_221200_magnetogram.fits")
