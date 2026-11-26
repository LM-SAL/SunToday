"""
Records of what was last rendered, used to skip work that is current.

``updated_at`` is the time of the data that was rendered, not the time
the job ran.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Column, Date, DateTime, create_engine
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy_utils import create_database, database_exists

from suntoday import logger

if TYPE_CHECKING:
    import datetime as dt

BASE = declarative_base()


__all__ = ["create_db", "get_latest_record", "get_record", "write_or_update_record"]


class SDOImages(BASE):
    """
    Last successful render of the SDO image products, one row per day.
    """

    __tablename__ = "SDOImages"
    obs_date = Column(Date(), primary_key=True)
    updated_at = Column(DateTime(timezone=True))


class TimeSeriesImages(BASE):
    """
    Last successful render of the lightcurve, one row per day.
    """

    __tablename__ = "TimeSeriesImages"
    obs_date = Column(Date(), primary_key=True)
    updated_at = Column(DateTime(timezone=True))


class PFSSImages(BASE):
    """
    Last successful render of the PFSS overlays, one row per day.

    ``boundary_epoch`` is the time of the boundary map that render used.
    Its column is still called ``adapt_epoch``.
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
    Return an engine, creating the database and its tables if missing.
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
    Return the most recently updated record of a type, or None.
    """
    model = _get_model(model_type)
    record = session.query(model).order_by(model.updated_at.desc()).first()
    if record is None:
        logger.info(f"Found zero results for model for {model_type}")
    return record


def get_record(
    session: Session, model_type: str, obs_date: dt.date
) -> SDOImages | TimeSeriesImages | PFSSImages | None:
    """
    Return the record of a type for an observation date, or None.
    """
    model = _get_model(model_type)
    record = session.query(model).filter(model.obs_date == obs_date).first()
    if record is None:
        logger.info(f"Found zero results for model for {model_type} on {obs_date}")
    return record


def write_or_update_record(
    session: Session,
    model_type: str,
    obs_date: dt.date,
    *,
    updated_at: dt.datetime,
    boundary_epoch: dt.datetime | None = None,
):
    """
    Create or update the record of a type for an observation date.
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
