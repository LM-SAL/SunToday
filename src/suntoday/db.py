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


class PFSSImages(BASE):
    """
    This class represents the database table for successful creation of the
    matched-time PFSS overlay JPEGS.

    Attributes
    ----------
    obs_date : datetime
        Primary key - The observation date of the image
    updated_at : datetime
        Timestamp of when the record was last updated
    adapt_epoch : datetime
        ADAPT map timestamp used for the last successful PFSS render
    """

    __tablename__ = "PFSSImages"
    obs_date = Column(Date(), primary_key=True)
    updated_at = Column(DateTime(timezone=True))
    adapt_epoch = Column(DateTime(timezone=True))


VALID_MODELS = {"images": SDOImages, "timeseries": TimeSeriesImages, "pfss": PFSSImages}


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
    uri = uri or settings.db_url
    engine = create_engine(uri, echo=echo, connect_args={"options": "-c timezone=utc"})
    if not database_exists(engine.url):
        logger.info(f"Creating database at {engine.url}")
        create_database(url=engine.url)
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
    uri = uri or settings.db_url
    engine = create_engine(uri, echo=echo)
    session = sessionmaker(bind=engine)
    return session()


def get_latest_record(session: Session, model_type: str) -> SDOImages | TimeSeriesImages | PFSSImages | None:
    """
    Retrieve the last updated record from the database based on the model type.

    Parameters
    ----------
    session : Session
        SQLAlchemy session object
    model_type : str
        Type of model to query; one of ``VALID_MODELS``.

    Returns
    -------
    Model | None
        The most recently updated record, or None if the table is empty.

    Raises
    ------
    ValueError
        If ``model_type`` is not one of the valid types defined in ``VALID_MODELS``.
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


def get_record(
    session: Session, model_type: str, obs_date: datetime.date
) -> SDOImages | TimeSeriesImages | PFSSImages | None:
    """
    Retrieve a record from the database based on the model type and observation
    date.

    Parameters
    ----------
    session : Session
        SQLAlchemy session object.
    model_type : str
        Type of model to query; one of ``VALID_MODELS``.
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
    adapt_epoch: datetime.datetime | None = None,
):
    """
    Write a new record to the database or update an existing one based on the
    observation date.

    Parameters
    ----------
    session : Session
        SQLAlchemy session object.
    model_type : str
        Type of model to create; one of ``VALID_MODELS``.
    obs_date : str
        Observation date for the record.
    updated_at : str
        Timestamp for when the record was updated
    adapt_epoch : datetime.datetime, optional
        ADAPT map timestamp used for a PFSS render.

    Raises
    ------
    ValueError
        If ``model_type`` is not valid.
    """
    model_class = VALID_MODELS.get(model_type)
    if model_class is None:
        msg = f"Given type: {model_type} not allowed - {VALID_MODELS.keys()}"
        raise ValueError(msg)
    if adapt_epoch is not None and model_class is not PFSSImages:
        msg = "adapt_epoch is only valid for PFSS records"
        raise ValueError(msg)
    try:  # ruff:ignore[too-many-statements-in-try-clause]
        existing_record = session.query(model_class).filter(model_class.obs_date == obs_date).first()
        if existing_record:
            existing_record.updated_at = updated_at
            if adapt_epoch is not None:
                existing_record.adapt_epoch = adapt_epoch
            session.commit()
            logger.info(f"Updated existing {model_type} record for {obs_date} with updated_at: {updated_at}")
        else:
            new_record = model_class(obs_date=obs_date, updated_at=updated_at)
            if adapt_epoch is not None:
                new_record.adapt_epoch = adapt_epoch
            session.add(new_record)
            session.commit()
            logger.info(f"Created new {model_type} record for {obs_date}")
    except Exception as e:
        session.rollback()
        raise e from None
