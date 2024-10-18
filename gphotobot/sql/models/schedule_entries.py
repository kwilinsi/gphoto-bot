from datetime import time
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .timelapses import Timelapse


class ScheduleEntry(Base):
    __tablename__ = 'ScheduleEntries'

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign key: many-to-one
    timelapse_id: Mapped[int] = mapped_column(ForeignKey(Timelapse.id))
    timelapse: Mapped[Timelapse] = relationship(
        back_populates='schedule_entries'
    )

    # Attributes
    start_time: Mapped[time] = mapped_column(Time(timezone=True))
    end_time: Mapped[time] = mapped_column(Time(timezone=True))
    days: Mapped[str] = mapped_column(String(250))
    config: Mapped[Optional[str]] = mapped_column(Text())
