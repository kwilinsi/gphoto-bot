from __future__ import annotations

from datetime import time
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .timelapses import Timelapse


class ScheduleEntry(Base):
    __tablename__ = 'ScheduleEntries'

    # Primary key is (timelapse_id, index)

    # Foreign key: many-to-one
    timelapse_id: Mapped[int] = mapped_column(ForeignKey(Timelapse.id),
                                              primary_key=True)
    timelapse: Mapped[Timelapse] = relationship(
        back_populates='schedule_entries'
    )

    # The position of this schedule entry in the timelapse schedule relative to
    # other entries. This is 0 indexed.
    index: Mapped[int] = mapped_column(Integer(), primary_key=True)

    # Attributes
    start_time: Mapped[time] = mapped_column(Time(timezone=True))
    end_time: Mapped[time] = mapped_column(Time(timezone=True))
    days: Mapped[str] = mapped_column(String(250))
    config: Mapped[Optional[str]] = mapped_column(Text())

    def __copy__(self) -> ScheduleEntry:
        return ScheduleEntry(
            timelapse_id=self.timelapse_id,
            index=self.index,
            start_time=self.start_time,
            end_time=self.end_time,
            days=self.days,
            config=self.config
        )

    def __deepcopy__(self, *args) -> ScheduleEntry:
        return self.__copy__()
