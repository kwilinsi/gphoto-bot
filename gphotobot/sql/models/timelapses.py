from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey,
                        select, String, Enum as SQLEnum)
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


class State(PyEnum):
    # The timelapse is finished. Either it's past the end_time, or it reached
    # the total_frames threshold. It will not take any more photos unless the
    # user intervenes manually.
    FINISHED = 0

    # The timelapse was just created. It's set to manual start (i.e. the
    # start_time is None), and the user has yet to start it. It should be
    # impossible to return to this state after starting.
    READY = 1

    # Either (1) a timelapse executor is waiting until the start_time to begin
    # taking photos, or (2) it's waiting for a schedule entry to take effect.
    WAITING = 2

    # A timelapse executor is (or should be) currently taking photos.
    RUNNING = 3

    # That means the user manually intervened to start the timelapse early or
    # keep it going after it would have finished. It'll stay like this until
    # either (a) the start time is reached, or (b) the user stops it manually.
    FORCE_RUNNING = 4

    # The user has manually paused this timelapse. It's ignoring the schedule
    # until un-paused. However, it's still waiting for the end_time, if that's
    # set. If it reaches the end_time, the state will switch to FINISHED.
    PAUSED = 5


class Timelapse(Base):
    __tablename__ = 'Timelapses'

    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign key: many-to-one
    camera_id: Mapped[int] = mapped_column(ForeignKey(Camera.id))
    camera: Mapped[Camera] = relationship(
        back_populates='timelapses',
        lazy='joined'
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
    capture_interval: Mapped[float] = mapped_column(Float())
    frames: Mapped[int] = mapped_column(BigInteger(), default=0)
    total_frames: Mapped[Optional[int]] = mapped_column(BigInteger())
    state: Mapped[State] = mapped_column(SQLEnum(State))

    # Technically, this should be redundant with checking that
    # len(schedule_entries) > 0, but it's simpler to query
    has_schedule: Mapped[bool] = mapped_column(Boolean())

    # Schedules relationship: one-to-many
    # noinspection PyUnresolvedReferences, SpellCheckingInspection
    schedule_entries: Mapped[list["ScheduleEntry"]] = relationship(
        back_populates='timelapse',
        lazy='selectin'
    )


async def get_active_timelapses(session: AsyncSession) -> list[Timelapse]:
    """
    Get a list of all the timelapses where either (a) the state is not FINISHED
    or (b) the end_time is in the future.

    Args:
        session: The database session.

    Returns:
        list[Timelapse]: The list of all active timelapses.
    """

    stmt = select(Timelapse).where(
        (Timelapse.state != State.FINISHED) |
        (Timelapse.end_time > datetime.now())
    )
    result = await session.scalars(stmt)
    return [tl for tl in result]


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
