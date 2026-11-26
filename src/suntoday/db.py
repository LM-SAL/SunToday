"""
Provides all the database helpers needed.
"""

import datetime

from sqlalchemy import Column, Date, DateTime, create_engine
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy_utils import create_database, database_exists

from suntoday import logger

BASE = declarative_base()


__all__ = ["create_db", "get_latest_record", "get_record", "write_or_update_record"]


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
    boundary_epoch : datetime
        Boundary-map timestamp used for the last successful PFSS render. The
        legacy column name is retained for database compatibility.
    """

    __tablename__ = "PFSSImages"
    obs_date = Column(Date(), primary_key=True)
    updated_at = Column(DateTime(timezone=True))
    boundary_epoch = Column("adapt_epoch", DateTime(timezone=True))


VALID_MODELS = {"images": SDOImages, "timeseries": TimeSeriesImages, "pfss": PFSSImages}


def _get_model(model_type: str) -> type[SDOImages | TimeSeriesImages | PFSSImages]:
    """
    Look up the table class for a model type; unknown types raise ValueError.
    """
    model = VALID_MODELS.get(model_type)
    if model is None:
        msg = f"Given type: {model_type} not allowed - {VALID_MODELS.keys()}"
        raise ValueError(msg)
    return model


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
    """
    model = _get_model(model_type)
    record = session.query(model).order_by(model.updated_at.desc()).first()
    if record is None:
        logger.info(f"Found zero results for model for {model_type}")
    return record


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
    """
    model = _get_model(model_type)
    record = session.query(model).filter(model.obs_date == obs_date).first()
    if record is None:
        logger.info(f"Found zero results for model for {model_type} on {obs_date}")
    return record


def write_or_update_record(
    session: Session,
    model_type: str,
    obs_date: datetime.date,
    *,
    updated_at: datetime.datetime,
    boundary_epoch: datetime.datetime | None = None,
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
    obs_date : datetime.date
        Observation date for the record.
    updated_at : datetime.datetime
        Timestamp for when the record was updated
    boundary_epoch : datetime.datetime, optional
        Boundary-map timestamp used for a PFSS render.

    Raises
    ------
    ValueError
        If ``boundary_epoch`` is given for a non-PFSS record.
    """
    model_class = _get_model(model_type)
    if boundary_epoch is not None and model_class is not PFSSImages:
        msg = "boundary_epoch is only valid for PFSS records"
        raise ValueError(msg)
    try:  # ruff:ignore[too-many-statements-in-try-clause]
        record = session.query(model_class).filter(model_class.obs_date == obs_date).first()
        if record is None:
            record = model_class(obs_date=obs_date)
            session.add(record)
        record.updated_at = updated_at
        if boundary_epoch is not None:
            record.boundary_epoch = boundary_epoch
        session.commit()
        logger.info(f"Recorded {model_type} for {obs_date} with updated_at: {updated_at}")
    except Exception:
        session.rollback()
        raise
