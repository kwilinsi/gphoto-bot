from datetime import datetime
from typing import Optional

from sqlalchemy import (BigInteger, Boolean, Column, DateTime,
                        Float, Integer, String)
from sqlalchemy.sql import func
from sqlalchemy.orm import Session, Mapped, mapped_column

from .base import Base

# The default name format, which is derived from the current date
DEFAULT_NAME_FORMAT = '%Y-%m-%d'

# Maximum string/VARCHAR lengths
NAME_MAX_LENGTH = 100
DIRECTORY_MAX_LENGTH = 300


class Timelapses(Base):
    __tablename__ = 'Timelapses'

    id: Mapped[int] = mapped_column(primary_key=True)
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
    is_running: Mapped[bool] = mapped_column(Boolean(), default=False)
    is_finished: Mapped[bool] = mapped_column(Boolean(), default=False)


def get_all_active(session) -> list[Timelapses]:
    """
    Get a list of all the timelapses where is_finished is False.

    Args:
        session: The database session.

    Returns:
        list[Timelapses]: The list of all active timelapses.
    """

    return (session.query(Timelapses)
            .filter(Timelapses.is_finished == False)
            .all())


def generate_default_name(session: Session) -> str:
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
    result = (session.query(Timelapses)
              .filter(Timelapses.name.like(f'{default_name}%'))
              .all())

    # Find the current highest disambiguating id
    max_int = 0
    for tl in result:
        match = re.match(r'\d{4}-\d{2}-\d{2}_(\d+)', tl.name)
        if match:
            i = int(match.group(1))
            max_int = max(max_int, i)

    if max_int == 0:
        return default_name
    else:
        return f'{default_name}_{max_int + 1}'


def is_name_active(session: Session, name: str) -> bool:
    """
    Check whether the given name corresponds to an active timelapse (i.e. one
    that hasn't finished yet).

    Args:
        session (Session): The database session.
        name (str): The name to check.

    Returns:
        bool: Whether the given name is active.
    """

    return len(session.query(Timelapses)
               .filter(Timelapses.name == name)
               .all()) > 0
