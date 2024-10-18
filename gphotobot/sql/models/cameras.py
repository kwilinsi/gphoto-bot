from typing import Optional

from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# Maximum string/VARCHAR lengths
NAME_MAX_LENGTH = 50
ADDRESS_MAX_LENGTH = 75
SERIAL_NUMBER_MAX_LENGTH = 100


class Camera(Base):
    __tablename__ = 'Cameras'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    address: Mapped[str] = mapped_column(String(ADDRESS_MAX_LENGTH))
    usb_bus: Mapped[Optional[int]] = mapped_column(SmallInteger())
    usb_device: Mapped[Optional[int]] = mapped_column(SmallInteger())
    serial_number: Mapped[Optional[str]] = mapped_column(
        String(SERIAL_NUMBER_MAX_LENGTH)
    )
    rotate_preview: Mapped[int] = mapped_column(SmallInteger(), default=False)

    # Timelapse relationship
    # noinspection PyUnresolvedReferences
    timelapses: Mapped[list["Timelapse"]] = relationship(
        back_populates='camera'
    )
