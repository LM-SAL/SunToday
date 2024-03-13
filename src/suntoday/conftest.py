import os

import pandas as pd
import pytest
import sunpy.map as smap
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor
from sqlalchemy import create_engine
from sqlalchemy.orm.session import sessionmaker
from sunpy.io import read_file

from suntoday.data.test import get_test_filepath
from suntoday.db import BASE, SDOImages, TimeSeriesImages, get_session

test_db = factories.postgresql_proc(port=None, dbname="test_db")


def pytest_configure(config) -> None:  # NOQA: ARG001
    # Limit the number of threads used by each worker when pytest-xdist is in
    # use.  Lifted from https://github.com/scipy/scipy/pull/14441
    # and https://github.com/scikit-learn/scikit-learn/pull/25918
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        pass
    else:
        xdist_worker_count = os.environ.get("PYTEST_XDIST_WORKER_COUNT")
        if xdist_worker_count is not None:
            # use number of physical cores, assume hyperthreading
            max_threads = os.cpu_count() // 2
            threads_per_worker = max(max_threads // int(xdist_worker_count), 1)
            threadpool_limits(threads_per_worker)


@pytest.fixture(scope="session", autouse=True)
def _setup_test_env(request):  # NOQA: ARG001
    """
    Globally set the test environment.
    """
    os.environ["SUNTODAY_TEST_ENV"] = "True"
    yield
    del os.environ["SUNTODAY_TEST_ENV"]


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
        assert session.query(SDOImages).count() == 0  # NOQA: S101
        assert session.query(TimeSeriesImages).count() == 0  # NOQA: S101
        session.close()
        yield sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def aia_timeseries():
    aia_lightcurve = pd.read_csv(get_test_filepath("aia_timeseries.csv"), index_col=0, parse_dates=True)
    aia_lightcurve.index = pd.to_datetime(aia_lightcurve.index, format="mixed")
    return aia_lightcurve.astype({"WAVELNTH": str, "DATAMEAN": float, "EXPTIME": float})


# TODO: Handle the number of filename fixtures smarter
@pytest.fixture
def goes_secondary_timeseries():
    return pd.read_csv(get_test_filepath("goes_secondary_timeseries.csv"), index_col=0, parse_dates=True)


@pytest.fixture
def goes_primary_timeseries():
    return pd.read_csv(get_test_filepath("goes_primary_timeseries.csv"), index_col=0, parse_dates=True)


# These are in order of the files stored on my local disk
@pytest.fixture
def aia_1700_test_file():
    return get_test_filepath("20250803_235940_1700.fits")


@pytest.fixture
def aia_1600_test_file():
    return get_test_filepath("20250803_235950_1600.fits")


@pytest.fixture
def aia_131_test_file():
    return get_test_filepath("20250803_235954_131.fits")


@pytest.fixture
def aia_171_test_file():
    return get_test_filepath("20250803_235957_171.fits")


@pytest.fixture
def aia_211_test_file():
    return get_test_filepath("20250803_235957_211.fits")


@pytest.fixture
def aia_94_test_file():
    return get_test_filepath("20250803_235959_94.fits")


@pytest.fixture
def aia_335_test_file():
    return get_test_filepath("20250804_000000_335.fits")


@pytest.fixture
def hmi_cont_test_file():
    return get_test_filepath("20250804_000000_continuum.fits")


@pytest.fixture
def hmi_blos_test_file():
    return get_test_filepath("20250804_000000_magnetogram.fits")


@pytest.fixture
def aia_193_test_file():
    return get_test_filepath("20250804_000004_193.fits")


@pytest.fixture
def aia_304_test_file():
    return get_test_filepath("20250804_000005_304.fits")


@pytest.fixture
def aia_171_test_generic_map(aia_171_test_file):
    ((data, header),) = read_file(aia_171_test_file)
    # Get rid of the blank keyword to prevent some astropy fits fixing warnings
    header.pop("BLANK")
    return smap.Map((data, header))


@pytest.fixture
def hmi_test_generic_map(hmi_cont_test_file):
    ((data, header),) = read_file(hmi_cont_test_file)
    # Get rid of the blank keyword to prevent some astropy fits fixing warnings
    header.pop("BLANK")
    header.pop("CRDER1")
    header.pop("CRDER2")
    return smap.Map((data, header))
