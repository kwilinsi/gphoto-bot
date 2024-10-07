import logging
from sys import modules

import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from gphotobot.conf import settings
from .models.base import Base
from .models.timelapses import Timelapses

_log = logging.getLogger(__name__)

# noinspection PyTypeChecker
engine: sqlalchemy.Engine = None

# noinspection PyTypeChecker
session_maker: sessionmaker = None


def initialize() -> None:
    """
    Initialize the database connection.
    """

    global engine, session_maker

    db_url = URL.create(
        'mariadb+mariadbconnector',
        username=settings.DATABASE_USERNAME,
        password=settings.DATABASE_PASSWORD,
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        database=settings.DATABASE_NAME
    )

    _log.debug("Creating database engine")
    engine = create_engine(db_url)
    _log.debug("Creating session maker")
    session_maker = sessionmaker(bind=engine)
    _log.debug("Creating tables")
    Base.metadata.create_all(engine)

    _log.info("Initialized database")
