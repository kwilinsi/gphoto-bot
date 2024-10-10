import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import functools
import logging
import os
from pathlib import Path
import re
from typing import Optional

import gphoto2 as gp
from discord.app_commands import guilds
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gphotobot.conf import TMP_DATA_DIR, settings
from gphotobot.sql.models.cameras import Cameras as DBCameras
from gphotobot.utils import const, utils
from .rotation import Rotation
from . import gutils

_log = logging.getLogger(__name__)

# This GPhoto2Error code indicates that the USB device can't be claimed,
# probably because another process is using the camera
USB_BUSY_ERROR_CODE = -53

# Regex for identifying the serial number in the camera summary
SERIAL_NUMBER_REGEX = r'serial\s*number:\s*(\w+)'


def retry_if_busy_usb(func):
    """
    This decorator allows us to retry a particular gPhoto command up to n times
    in the event that we get a USB busy error, which indicates that the camera
    couldn't be accessed because another process is using it.

    Args:
        func: The function to retry.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        attempts = settings.GPHOTO_MAX_RETRY_ATTEMPTS_ON_BUSY_USB + 1

        for i in range(attempts):
            try:
                return await func(*args, **kwargs)
            except gp.GPhoto2Error as e:
                # Retry only on usb busy error
                if e.code == USB_BUSY_ERROR_CODE and i < attempts - 1:
                    delay = settings.GPHOTO_RETRY_DELAY
                    _log.warning(
                        f"Failed to access camera: USB busy (code "
                        f"{USB_BUSY_ERROR_CODE}): attempting retry #{i + 1} "
                        f"in {delay} second{'' if delay == 1 else 's'}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    return wrapper


class GCamera:
    """
    This is a wrapper for the python-gphoto2 Camera class. It is designed to
    enforce safe, sequential access to the gp camera. This prevents multiple
    concurrent calls from, say, trying to take photos at the same time on the
    same camera. It also releases the camera between calls so other system
    processes can access it, such as the gphoto2 CLI tool.
    """

    # RegEx for parsing the USB device and bus from the address
    ADDR_REGEX = r'usb:(\d+),(\d+)'

    def __init__(self,
                 name: str,
                 addr: str,
                 port_info: gp.PortInfo,
                 port_info_list_reference: gp.PortInfoList,
                 abilities: gp.CameraAbilities,
                 gp_camera: Optional[gp.Camera] = None) -> None:
        """
        Initialize an even more Pythonic wrapper for a gphoto2 camera. This
        includes the port info and camera abilities.

        This is an autocloseable wrapper that can be opened in an async context
        manager. This will initialize the camera and exit it when finished.

        async with self as cam:
            cam.do_something()

        Args:
            name (str): The camera name.
            addr (str): The address.
            port_info (gp.PortInfo): The port info.
            port_info_list_reference (gp.PortInfoList): The port info list.
            abilities (gp.CameraAbilities): The camera abilities.
            gp_camera (Optional[gp.Camera]): The underlying gphoto2 camera. If
            None, a new one is created.
        """

        self.name: str = name
        self.addr: str = addr
        self.port_info: gp.PortInfo = port_info
        self.abilities: gp.CameraAbilities = abilities

        # The gp_camera is private, as it must only be accessed through a
        # context manager on this GCamera. That is done through the lock to
        # ensure multiple processes aren't trying to access the camera
        # simultaneously. The camera is intentionally initialized and exit with
        # every use so that it doesn't hog access to the USB device
        self._gp_camera: gp.Camera = gp_camera if gp_camera else gp.Camera()
        self._lock: asyncio.Lock = asyncio.Lock()

        # Record whether this object has been synced with the database
        self.synced_with_database: bool = False

        # The serial number is used to sync with the database. If this is None,
        # it means it's not yet known, and we need to query the camera. If this
        # is an empty string, it means we can't find a serial number for this
        # camera. Either it's not in the summary, or we couldn't get the
        # summary.
        self.serial_number: Optional[str] = None

        # Whether (and how much) to rotate preview images from this camera.
        # Rotation can be done in 90 degree increments. If this is None, it
        # indicates that the rotation is unknown, and it'll default to no
        # rotation.
        self._rotate_preview: Optional[Rotation] = None

        # For some reason, I have to accept a reference to this list and store
        # it here. I never use it at all, and it can be named anything. But if I
        # remove this line, then later, when I try to use the *separate*
        # port_info variable to initialize the camera, I get a segmentation
        # fault. For some reason, keeping this variable around (without using
        # it) fixes that problem. I have no idea what's going on. Maybe it's
        # being garbage collected or something? Some quirk of using a library
        # that's just a bunch of C bindings? Who knows
        self._port_info_list_reference = port_info_list_reference

        _log.debug(f"Initialized GCamera(name='{name}', addr='{addr}')")

    def __str__(self):
        return self.trunc_name()

    @asynccontextmanager
    async def initialize_camera(self):
        """
        Initialize the gp_camera with asyncio to prevent IO blocking. When done,
        the camera automatically exits. Open this as a context manager as
        follows:

        with initialize_camera() as camera:
            camera.do_something()
        """

        # Camera initialization function
        def init_camera():
            _log.debug(f"Initializing '{self}' gp_camera")
            self._gp_camera.set_port_info(self.port_info)
            self._gp_camera.set_abilities(self.abilities)
            self._gp_camera.init()

        # Camera exit function
        def exit_camera():
            try:
                _log.debug(f"Exiting '{self}' gp_camera")
                self._gp_camera.exit()
            except gp.GPhoto2Error as e:
                _log.warning(f"Failed to exit gp_camera on '{self}' "
                             f"(code {e.code}): {e}")

        ########################################

        # Ensure sequential access to the camera
        await self._lock.acquire()
        _log.debug("Acquired lock on gp_camera on '{self}'")

        # Initialize, yield, and auto-exit
        try:
            await asyncio.to_thread(init_camera)
            yield self._gp_camera
        finally:
            await asyncio.to_thread(exit_camera)
            self._lock.release()
            _log.debug(f"Released lock on gp_camera on '{self}'")

    def update_address(self, addr: str, port_info: gp.PortInfo) -> None:
        """
        Update the address and port info of this camera, usually because it
        was disconnected and reconnected.

        This has the side effect of setting the database sync flag to False and
        clearing the serial number.

        Args:
            addr (str): The address.
            port_info (gp.PortInfo): The port info.
        """

        self.addr = addr
        self.port_info = port_info

        self.synced_with_database = False
        self.serial_number = None

    @retry_if_busy_usb
    async def get_serial_number(self) -> str:
        """
        Get the serial number. If it's not set, determine it by retrieving the
        camera summary.

        Use get_serial_number_short() to get a version without leading zeros,
        if applicable.

        Returns:
            The serial number.
        """

        if self.serial_number is not None:
            return self.serial_number

        # Get the camera summary
        async with self.initialize_camera() as camera:
            try:
                summary = str(await asyncio.to_thread(camera.get_summary))
            except gp.GPhoto2Error as e:
                if e.code == USB_BUSY_ERROR_CODE:
                    raise
                _log.warning(f"Can't get serial number for '{self}'. Got "
                             f"error {e.code} on get_summary(): {e}")
                self.serial_number = ""
                return ""

        # Look for the serial number in the summary
        if summary:
            match = re.search(SERIAL_NUMBER_REGEX, summary,
                              flags=re.IGNORECASE)
            if match:
                self.serial_number = match.group(1)
                return self.serial_number
            else:
                _log.debug(f"Couldn't find serial number for '{self}' "
                           f"in the summary ({len(summary)} chars)")
        else:
            _log.debug(f"Couldn't get a summary for '{self}'; failed to find "
                       f"the serial number")

        # Can't find the serial number
        self.serial_number = ""
        return ""

    async def get_serial_number_short(self) -> Optional[str]:
        """
        If the serial number is an integer, it might have a bunch of leading
        zeros. In that case, remove said zeros from the short version.
        Otherwise, this is the same as the regular get_serial_number().

        Returns:
            Optional[str]: The serial number, shortened if applicable.
        """

        serial = await self.get_serial_number()

        # If the serial number is an integer with leading zeros, trim them
        if serial is not None and serial.startswith('0'):
            try:
                int(serial)
                serial = serial.lstrip('0')

                # Just in case it's like binary or hex for some reason
                if serial.startswith(('x', 'b', 'o')):
                    serial = '0' + serial
            except ValueError:
                pass

        return serial

    def get_rotate_preview(self) -> Rotation:
        """
        Get how much rotate the preview image. If the current value is None,
        this will return Rotation.DEGREE_0 for no rotation.

        Returns:
            The amount to rotate preview images.
        """

        if self._rotate_preview is None:
            return Rotation.DEGREE_0
        else:
            return self._rotate_preview

    def set_rotate_preview(self, rotation: Rotation):
        """
        Set a new rotation preview for this camera. If it's different from the
        existing value, this resets the database sync flag.

        Args:
            rotation: The new rotation.
        """

        if self._rotate_preview != rotation:
            self._rotate_preview = rotation
            self.synced_with_database = False

    async def sync_with_database(self, session: AsyncSession):
        """
        Sync this camera with the Cameras table in the database. This will load
        the serial number if it's not loaded already.

        Args:
            session (AsyncSession): The database session.
        """

        serial = await self.get_serial_number()
        bus, device = self.get_usb_bus_device()
        rotation = self.get_rotate_preview()

        _log.debug(f"Syncing '{self}' with database (serial='{serial}')")

        # Look for cameras with the same serial number
        stmt = select(DBCameras).where(DBCameras.serial_number == serial)
        result = (await session.scalars(stmt)).all()

        # If no results, add this camera to the database
        if len(result) == 0:
            session.add(DBCameras(
                name=self.name,
                address=self.addr,
                usb_bus=bus,
                usb_device=device,
                serial_number=self.serial_number,
                rotate_preview=rotation.value
            ))
            _log.info(f"Adding new camera '{self}' to database")
            self.synced_with_database = True
            return

        # Check for multiple results (unexpected). This could maybe happen
        # if they have different names (i.e. different companies)?
        if len(result) > 1:
            result_filtered = [r for r in result if r.name == self.name]
            n = len(result_filtered)
            if n == 1:
                result = result_filtered
            elif n > 1:
                _log.warning(f"Found {n} cameras in db with serial number "
                             f"'{serial}' and name '{self.name}'. "
                             f"Failed to sync")
                return
            else:
                _log.warning(f"Found {len(result)} cameras in db with serial "
                             f"number '{serial}', but none are named "
                             f"'{self.name}'. Failed to sync")
                return

        # Sync any changes with the matching camera
        if len(result) == 1:
            cam = result[0]
            cam.name = self.name
            cam.address = self.addr
            cam.usb_bus = bus
            cam.usb_device = device
            if self._rotate_preview is None:
                self._rotate_preview = Rotation(cam.rotate_preview)
            else:
                cam.rotate_preview = self._rotate_preview.value

        # The camera is now synced
        self.synced_with_database = True

    def get_usb_bus_device(self) -> tuple[Optional[int], Optional[int]]:
        """
        Get the USB Bus and Device number from the address.

        Returns:
            tuple[Optional[int], Optional[int]]: The USB Bus and Device number,
            in that order. If they cannot be determined, both are None.
        """

        bus, device = None, None
        match = re.search(self.ADDR_REGEX, self.addr)
        if match:
            bus = match.group(1)
            try:
                bus = int(bus)
            except ValueError:
                _log.warning(f"Couldn't convert bus '{bus}' to an int")

            device = match.group(2)
            try:
                device = int(device)
            except ValueError:
                _log.warning(f"Couldn't convert device '{device}' to an int")

        return bus, device

    def get_usb_bus_device_str(self) -> Optional[str]:
        """
        Get a string with the USB bus and device number separated by a comma.
        If either the bus or device number is unknown, this returns None.

        Returns:
            Optional[str]: A string with the USB port info.
        """

        bus, device = self.get_usb_bus_device()
        if not bus or not device:
            return None

        return f'{bus:03d},{device:03d}'

    def trunc_name(
            self,
            max_len: Optional[int] = const.EMBED_FIELD_NAME_LENGTH
    ) -> str:
        """
        Get the camera name. It is truncated if necessary to fit in the max_len.

        Args:
            max_len (Optional[int]): The maximum length of the name. If None,
            the name is never truncated. Defaults to the maximum length of
            the name in an embed field.

        Returns:
            str: The name.
        """

        if max_len is None:
            return self.name
        else:
            return utils.trunc(self.name, max_len)

    async def info(self) -> str:
        """
        Get a formatted string with some basic info about the camera. Note that
        this does not include the name.

        Returns:
            An info string.
        """

        # Get the serial number
        serial = await self.get_serial_number_short()
        if not serial:
            serial = '[Unknown]'

        # Get the rotation as a nicely formatted string
        rotation = str(self.get_rotate_preview())

        # Format the address
        bus, device = self.get_usb_bus_device()
        if bus or device:
            bus = f'{bus:03d}' if bus else '[Unknown]'
            device = f'{device:03d}' if device else '[Unknown]'
            addr = f'USB Bus {bus} | Device {device}'
        else:
            addr = self.addr

        # Combine everything
        info = utils.trunc(f'**Addr:** {addr}\n'
                           f'**Serial Number:** {serial}\n'
                           f'**Preview Rotation:** {rotation}',
                           const.EMBED_FIELD_VALUE_LENGTH)
        return info

    @retry_if_busy_usb
    async def preview_photo(self) -> tuple[Path, Rotation]:
        """
        Capture a preview photo.

        Returns:
            tuple[Path, Rotation]: The path to the image, and a rotation value
            indicating whether the image was rotated.
        """

        _log.info(f"Capturing preview photo on '{self.trunc_name()}'...")

        async with self.initialize_camera() as camera:
            file = await asyncio.to_thread(camera.capture_preview)

            # Get the file extension used by the default name
            extension: str = os.path.splitext(file.get_name())[1]

            # Generate a path for the image in the tmp directory
            name: str = datetime.now().strftime('%Y%m%d_%H%M%S%f') + extension
            path: Path = TMP_DATA_DIR / ('preview_' + name)

            await asyncio.to_thread(file.save, str(path))
            _log.debug(f'Saved preview at {path}')

            # If necessary, rotate the image
            rotation = self.get_rotate_preview()
            if rotation != Rotation.DEGREE_0:
                _log.debug(f'Rotating preview {rotation.value} degrees')
                await gutils.rotate_image(path, rotation)

            return path, rotation
