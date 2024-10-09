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

from gphotobot.conf import TMP_DATA_DIR, settings
from gphotobot.utils import const, utils

_log = logging.getLogger(__name__)


def retry_if_busy_usb(func):
    """
    This decorator allows us to retry a particular gPhoto command up to n times
    in the event that we get error code -53, which indicates that the USB device
    couldn't be claimed because another process is using it.

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
                # Retry only on code -53
                if e.code == -53 and i < attempts - 1:
                    delay = settings.GPHOTO_RETRY_DELAY
                    _log.warning(
                        f"Failed to access camera: USB busy (code -53): "
                        f"attempting retry #{i + 1} in {delay} "
                        f"second{'' if delay == 1 else 's'}"
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

        Args:
            addr (str): The address.
            port_info (gp.PortInfo): The port info.
        """

        self.addr = addr
        self.port_info = port_info

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

    def formatted_addr(
            self,
            max_len: Optional[int] = const.EMBED_FIELD_VALUE_LENGTH
    ) -> str:
        """
        Get a formatted string with the camera address. If it conforms to the
        expected RegEx form for a USB address, this is a string indicating the
        USB bus and device. Otherwise, it's just the raw address string.

        If necessary, the address is truncated to fit within the max_len.

        Args:
            max_len (Optional[int]): The maximum length of the address. If None,
            it is never truncated. Defaults to the maximum length of the value
            in an embed field.

        Returns:
            str: The formatted address string.
        """

        match = re.match(self.ADDR_REGEX, self.addr)
        if match:
            addr = f'USB port\nBus {match.group(1)} | Device {match.group(2)}'
        else:
            addr = self.addr

        if max_len is None:
            return addr
        else:
            return utils.trunc(addr, max_len)

    @retry_if_busy_usb
    async def preview_photo(self) -> Path:
        """
        Capture a preview photo.

        Returns:
            Path: The path to the image.
        """

        _log.info(f"Capturing preview photo on '{self.trunc_name()}'...")

        async with self.initialize_camera() as camera:
            file = await asyncio.to_thread(camera.capture_preview)

            # Get the file extension used by the default name
            extension: str = os.path.splitext(file.get_name())[1]

            # Generate a path for the image in the tmp directory
            name: str = datetime.now().strftime('%Y%m%d_%H%M%S%f') + extension
            path: Path = TMP_DATA_DIR / name

            await asyncio.to_thread(file.save, str(path))
            _log.debug(f'Saved preview at {path}')

            return path
