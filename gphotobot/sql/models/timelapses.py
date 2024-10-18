from datetime import datetime
import re
from typing import Literal, Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .cameras import Camera

# The default name format, which is derived from the current date
DEFAULT_NAME_FORMAT = '%Y-%m-%d'

# Maximum string/VARCHAR lengths
NAME_MAX_LENGTH = 100
DIRECTORY_MAX_LENGTH = 300


class Timelapse(Base):
    __tablename__ = 'Timelapses'

    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign key: many-to-one
    camera_id: Mapped[int] = mapped_column(ForeignKey(Camera.id))
    camera: Mapped[Camera] = relationship(
        back_populates='timelapses'
    )

    # Attributes
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    user_id: Mapped[int] = mapped_column(BigInteger())
    directory: Mapped[str] = mapped_column(String(DIRECTORY_MAX_LENGTH))
    start_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    interval: Mapped[float] = mapped_column(Float())
    frames: Mapped[int] = mapped_column(BigInteger(), default=0)
    total_frames: Mapped[Optional[int]] = mapped_column(BigInteger())
    state: Mapped[Literal['Not Started', 'Running', 'Paused', 'Finished(']] = \
        mapped_column(String(11), default='Not Started')

    # Schedules relationship: one-to-many
    # noinspection PyUnresolvedReferences
    schedule_entries: Mapped[list["ScheduleEntry"]] = relationship(
        back_populates='timelapse'
    )


async def get_all_active(session: AsyncSession) -> list[Timelapse]:
    """
    Get a list of all the timelapses where is_finished is False.

    Args:
        session: The database session.

    Returns:
        list[Timelapse]: The list of all active timelapses.
    """

    stmt = select(Timelapse).where(Timelapse.state != 'Finished')
    result = await session.scalars(stmt)
    return [tl for tl in result]


async def generate_default_name(session: AsyncSession) -> str:
    """
    Identify all timelapses that are using the default name (which is just the
    date) and are named for TODAY.

    If there are any, then we'll have to add an incrementing integer to the
    end to disambiguate. Return the name with the next available integer,
    or just the default name if there are no conflicts at all.

    Note: I should probably have some method of synchronization here to
    prevent two people from simultaneously claiming the next available ID.
    Probably not a thread lock (to prevent extreme delays), but maybe a way to
    increment the integer every time this method is called just in case a
    new timelapse is created.

    Args:
        session (Session): The database session.

    Returns:
        str: The next available default name for today.
    """

    # Get all timelapses named for today
    default_name = datetime.now().strftime(DEFAULT_NAME_FORMAT)
    stmt = select(Timelapse).where(Timelapse.name.like(f'{default_name}%'))
    result = await session.scalars(stmt)

    # Find the current highest disambiguating id
    max_int = 0
    for tl in result.all():
        match = re.match(r'\d{4}-\d{2}-\d{2}_(\d+)', tl.name)
        if match:
            i = int(match.group(1))
            max_int = max(max_int, i)

    if max_int == 0:
        return default_name
    else:
        return f'{default_name}_{max_int + 1}'


async def is_name_active(session: AsyncSession, name: str) -> bool:
    """
    Check whether the given name corresponds to an active timelapse (i.e. one
    that hasn't finished yet).

    Args:
        session (Session): The database session.
        name (str): The name to check.

    Returns:
        bool: Whether the given name is active.
    """

    stmt = select(Timelapse).where(Timelapse.name == name)
    result = await session.scalars(stmt)
    return len(result.all()) > 0
