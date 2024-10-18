import logging

from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)
from sqlalchemy.engine import URL

from gphotobot.conf import settings
from .models.base import Base
from .models.cameras import Camera
from .models.timelapses import Timelapse
from .models.schedule_entries import ScheduleEntry

_log = logging.getLogger(__name__)

# noinspection PyTypeChecker
engine: AsyncEngine = None

# noinspection PyTypeChecker
async_session_maker: async_sessionmaker[AsyncSession] = None


async def initialize() -> None:
    """
    Initialize the database connection.
    """

    global engine, async_session_maker

    db_url = URL.create(
        'mariadb+asyncmy',
        username=settings.DATABASE_USERNAME,
        password=settings.DATABASE_PASSWORD,
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        database=settings.DATABASE_NAME
    )

    _log.debug("Creating database engine...")
    # pool_pre_ping=True to prevent losing connection to database at very
    # slight performance hit
    engine = create_async_engine(db_url, pool_pre_ping=True)

    _log.debug("Creating session maker...")
    async_session_maker = async_sessionmaker(bind=engine)

    _log.debug("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    _log.info("Initialized database")
