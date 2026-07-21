import pandas as pd
import pytest
import sunpy.map as smap
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor
from sqlalchemy import create_engine
from sqlalchemy.orm.session import sessionmaker
from sunpy.io._file_tools import read_file  # ruff:ignore[import-private-name]

from suntoday.data.test import get_test_filepath
from suntoday.db import BASE, SDOImages, TimeSeriesImages, get_session

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
def hmi_cont_test_file():
    return get_test_filepath("20260717_221200_continuum.fits")


@pytest.fixture
def hmi_blos_test_file():
    return get_test_filepath("20260717_221200_magnetogram.fits")


@pytest.fixture
def aia_1700_test_file():
    return get_test_filepath("20260717_221204_1700.fits")


@pytest.fixture
def aia_131_test_file():
    return get_test_filepath("20260717_221154_131.fits")


@pytest.fixture
def aia_171_test_file():
    return get_test_filepath("20260717_221157_171.fits")


@pytest.fixture
def aia_211_test_file():
    return get_test_filepath("20260717_221157_211.fits")


@pytest.fixture
def aia_94_test_file():
    return get_test_filepath("20260717_221159_94.fits")


@pytest.fixture
def aia_335_test_file():
    return get_test_filepath("20260717_221200_335.fits")


@pytest.fixture
def aia_1600_test_file():
    return get_test_filepath("20260717_221150_1600.fits")


@pytest.fixture
def aia_193_test_file():
    return get_test_filepath("20260717_221204_193.fits")


@pytest.fixture
def aia_304_test_file():
    return get_test_filepath("20260717_221205_304.fits")


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
