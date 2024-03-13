"""
Provides all the database helpers needed.
"""

import datetime

from sqlalchemy import Column, Date, DateTime, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy_utils import create_database, database_exists

from suntoday import logger

BASE = declarative_base()


__all__ = ["DatabaseError", "create_db", "get_latest_record", "get_record", "get_session", "write_or_update_record"]


class DatabaseError(Exception):
    """
    Base database error for this module.
    """


class SDOImages(BASE):
    """
    This class represents the database table for successful creation of all SDO
    JPEGS.

    Attributes
    ----------
    obs_date : datetime
        Primary key - The observation date of the image
    updated_at : datetime
        Timestamp of when the record was last updated
    """

    __tablename__ = "SDOImages"
    obs_date = Column(Date(), primary_key=True)
    updated_at = Column(DateTime(timezone=True))


class TimeSeriesImages(BASE):
    """
    This class represents the database table for successful creation of all
    lightcurve JPEGS.

    Attributes
    ----------
    obs_date : datetime
        Primary key - The observation date of the image
    updated_at : datetime
        Timestamp of when the record was last updated
    """

    __tablename__ = "TimeSeriesImages"
    obs_date = Column(Date(), primary_key=True)
    updated_at = Column(DateTime(timezone=True))


VALID_MODELS = {"images": SDOImages, "timeseries": TimeSeriesImages}


def create_db(uri=None, *, echo: bool = False):
    """
    Create a new database at the specified URI if it doesn't exist.

    Parameters
    ----------
    uri : str, optional
        The database connection URI. If not provided, it will use the default
        configuration from the Settings class.
    echo : bool, optional
        If True, enables SQLAlchemy engine logging, by default False

    Returns
    -------
    Engine
        SQLAlchemy engine object connected to the database
    """
    from suntoday.config import Settings

    settings = Settings()
    uri = uri or settings.db_url.format(
        db_user=settings.db_user,
        db_password=settings.db_password,
        db_host=settings.db_host,
        db_port=settings.db_port,
        db_name=settings.db_name,
    )
    engine = create_engine(uri, echo=echo, connect_args={"options": "-c timezone=utc"})
    if not database_exists(engine.url):
        msg = f"Creating database at {engine.url}"
        logger.info(msg)
        create_database(url=engine.url)
        msg = "Database created"
    else:
        msg = f"Database already exists at {engine.url}"
        logger.info(msg)
    logger.info("Ensuring all tables are created in the database.")
    BASE.metadata.create_all(engine)
    return engine


def get_session(uri=None, *, echo: bool = False) -> Session:
    """
    Create and return a new database session.

    Parameters
    ----------
    uri : str, optional
        The database connection URI. If not provided, it will use the default
        configuration from the Settings class.
    echo : bool, optional
        If True, enables SQLAlchemy engine logging, by default False

    Returns
    -------
    Session
        SQLAlchemy session object connected to the database
    """
    from suntoday.config import Settings

    settings = Settings()
    uri = uri or settings.db_url.format(
        db_user=settings.db_user,
        db_password=settings.db_password,
        db_host=settings.db_host,
        db_port=settings.db_port,
        db_name=settings.db_name,
    )
    engine = create_engine(uri, echo=echo)
    session = sessionmaker(bind=engine)
    return session()


def get_latest_record(session: Session, model_type: str) -> SDOImages | TimeSeriesImages:
    """
    Retrieve the last updated record from the database based on the model type.

    Parameters
    ----------
    session : Session
        SQLAlchemy session object
    model_type : str
        Type of model to query, 'images' or 'timeseries'

    Returns
    -------
    Model
        The matching record from the database.

    Raises
    ------
    ValueError
        If ``model_type`` is not one of the valid types defined in ``VALID_TYPES``.
    """
    model = VALID_MODELS.get(model_type)
    if model is None:
        msg = f"Given type: {model_type} not allowed - {VALID_MODELS.keys()}"
        raise ValueError(msg)
    results = session.query(model).order_by(model.updated_at.desc()).first()
    if results is None:
        msg = f"Found zero results for model for {model_type}"
        logger.info(msg)
        return None
    return results


def get_record(session: Session, model_type: str, obs_date: datetime.date) -> SDOImages | TimeSeriesImages | None:
    """
    Retrieve a record from the database based on the model type and observation
    date.

    Parameters
    ----------
    session : Session
        SQLAlchemy session object.
    model_type : str
        Type of model to query, 'images' or 'timeseries'.
    obs_date : datetime.date
        Observation date for the record.

    Returns
    -------
    Model | None
        The matching record from the database or None if not found.

    Raises
    ------
    ValueError
        If ``model_type`` is not one of the valid types defined in ``VALID_MODELS``.
    """
    model = VALID_MODELS.get(model_type)
    if model is None:
        msg = f"Given type: {model_type} not allowed - {VALID_MODELS.keys()}"
        raise ValueError(msg)
    results = session.query(model).filter(model.obs_date == obs_date).first()
    if results is None:
        msg = f"Found zero results for model for {model_type} on {obs_date}"
        logger.info(msg)
        return None
    return results


def write_or_update_record(
    session: Session,
    model_type: str,
    obs_date: str,
    *,
    updated_at: str,
):
    """
    Write a new record to the database or update an existing one based on the
    observation date.

    Parameters
    ----------
    session : Session
        SQLAlchemy session object.
    model_type : str
        Type of model to create, 'images' or 'timeseries'
    obs_date : str
        Observation date for the record.
    updated_at : str
        Timestamp for when the record was updated

    Raises
    ------
    ValueError
        If ``model_type`` is not valid.
    """
    model_class = VALID_MODELS.get(model_type)
    if model_class is None:
        msg = f"Given type: {model_type} not allowed - {VALID_MODELS.keys()}"
        raise ValueError(msg)
    try:
        existing_record = session.query(model_class).filter(model_class.obs_date == obs_date).first()
        if existing_record:
            logger.info(f"Found existing {model_type} record for {obs_date}")
            existing_record.updated_at = updated_at
            session.commit()
            logger.info(f"Updated existing {model_type} record for {obs_date} with updated_at: {updated_at}")
        else:
            new_record = model_class(obs_date=obs_date, updated_at=updated_at)
            session.add(new_record)
            session.commit()
            logger.info(f"Created new {model_type} record for {obs_date}")
    except Exception as e:
        session.rollback()
        raise e from None
