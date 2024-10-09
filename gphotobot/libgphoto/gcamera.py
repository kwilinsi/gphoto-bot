import asyncio
from copy import copy
from datetime import datetime
import logging
import os
from pathlib import Path
import re
from typing import Optional

import gphoto2 as gp

from gphotobot.conf import TMP_DATA_DIR
from gphotobot.utils import const, utils

_log = logging.getLogger(__name__)


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

    async def __aenter__(self) -> gp.Camera:
        """
        Initialize the gp camera in an async context. This guarantees that it
        will exit.

        This also enforces concurrent access to the gp_camera.

        Returns:
              An initialized camera.
        """

        # Ensure sequential access to the camera
        await self._lock.acquire()

        def init():
            self._gp_camera.set_port_info(self.port_info)
            self._gp_camera.set_abilities(self.abilities)
            self._gp_camera.init()

        await asyncio.to_thread(init)
        return self._gp_camera

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            self._gp_camera.exit()
        except gp.GPhoto2Error as e:
            _log.warning(f'Failed to exit gp_camera in context manager: {e}')
        finally:
            # Release access to the lock so another process can use the camera
            self._lock.release()

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

    async def preview_photo(self) -> Path:
        """
        Capture a preview photo.

        Returns:
            Path: The path to the image.
        """

        _log.info(f"Capturing preview photo on '{self.trunc_name()}'...")

        async with self as camera:
            file = await asyncio.to_thread(camera.capture_preview)

            # Get the file extension used by the default name
            extension: str = os.path.splitext(file.get_name())[1]

            # Generate a path for the image in the tmp directory
            name: str = datetime.now().strftime('%Y%m%d_%H%M%S%f') + extension
            path: Path = TMP_DATA_DIR / name

            await asyncio.to_thread(file.save, str(path))
            _log.debug(f'Saved preview at {path}')

            return path
