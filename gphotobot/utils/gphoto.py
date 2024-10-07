from datetime import datetime
import inspect
import logging
import os
from pathlib import Path
import re

import discord
import gphoto2 as gp
from discord.ext import commands

from gphotobot.conf import TMP_DATA_DIR
from . import const, utils
from .utils import error_embed, trunc, update_interaction

_log = logging.getLogger(__name__)


class NoCameraFound(Exception):
    """
    This is thrown when a camera was expected but wasn't found, either because
    there are no cameras connected at all or because the specified camera
    wasn't found.
    """
    pass


class CameraEntry:
    ADDR_REGEX = r'usb:(\d+),(\d+)'

    def __init__(self, name: str, addr: any) -> None:
        """
        Initialize a simple entry for a camera with its name and address.

        Args:
            name (str): The camera name.
            addr (any): The address.
        """

        self.name = name
        if not isinstance(addr, str):
            _log.warning(f"Camera addr type is {type(addr)}: '{addr}'")
        self.addr = str(addr)

    def trunc_name(self) -> str:
        """
        Get the camera name. It is truncated if necessary to fit as the name of
        an embed field.

        Returns:
            str: The truncated name.
        """
        return utils.trunc(self.name, const.EMBED_FIELD_NAME_LENGTH)

    def formatted_addr(self) -> str:
        """
        Get a formatted string with the camera address. If it conforms to the
        expected RegEx form for a USB address, this is a string indicating the
        USB bus and device. Otherwise, it's just the raw address string. In
        the latter case, it is truncated if necessary to fit as the value of
        an embed field.

        Returns:
            str: The formatted address string.
        """

        match = re.match(CameraEntry.ADDR_REGEX, self.addr)
        if match:
            return f'USB port\nBus {match.group(1)} | Device {match.group(2)}'
        else:
            return utils.trunc(self.addr, const.EMBED_FIELD_VALUE_LENGTH)


def list_cameras() -> tuple[int, list[CameraEntry]]:
    """
    Get a list of detected cameras.

    Raises:
        NoCameraFound: If there aren't any cameras.

    Returns:
        tuple[int, list[CameraEntry]]: The number of cameras, and the list of
        cameras.
    """

    # Auto detect available cameras
    cameras = list(gp.Camera.autodetect())

    # If no cameras found, exit
    if not cameras:
        raise NoCameraFound()

    # Count the cameras
    n = len(cameras)

    cameras = [CameraEntry(c[0], c[1]) for c in cameras]
    cameras.sort(key=lambda c: c.name)

    # Return the cameras and the number
    return n, cameras


class ACCamera:
    def __init__(self, camera: gp.Camera):
        """
        This is an AutoCloseable wrapper around the gphoto2 Camera class. It
        calls exit() on the camera when closed.

        Args:
            camera (gp.Camera): The gphoto2 camera to wrap.
        """

        self.camera = camera

    def __enter__(self):
        return self.camera

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.camera.exit()


def get_camera() -> gp.Camera:
    """
    Get the default camera.

    Returns:
        gp.Camera: The camera.
    """

    _log.debug('Getting camera')

    try:
        camera = gp.Camera()
        camera.init()
        return ACCamera(camera)
    except gp.GPhoto2Error as e:
        # Code -105, "Unknown model," seems to occur when we haven't specified
        # a model and no camera is auto-detected.
        if e.code == -105:
            raise NoCameraFound(e)
        else:
            raise e


def get_camera_name(camera: gp.Camera) -> str:
    """
    Get the name of a given camera.

    Args:
        camera (gp.Camera): The camera.

    Returns:
        str: The camera name.
    """

    # Attempt to extract the name with RegEx from the camera summary
    summary: str = str(camera.get_summary())
    match = re.match(r'Manufacturer: ([\w ]+)\nModel: ([\w ]+)',
                     summary)

    if match:
        return match.group(1) + ' ' + match.group(2)
    else:
        return '[Unknown Camera]'


def preview() -> tuple[str, Path]:
    """
    Take a preview image.

    Returns:
        tuple[str, Path]: The name of the camera and the path to the image.
    """

    _log.debug('Taking preview photo')

    with get_camera() as camera:
        # gp_camera_capture_preview(): http://gphoto.org/doc/api/gphoto2-camera_8h.html#a8fa6903e3bf0ab26edc4e915512aa44f
        preview_file = camera.capture_preview()

        # Get the file extension used by the default name
        extension: str = os.path.splitext(preview_file.get_name())[1]

        # Generate a path for the image in the tmp directory
        name: str = datetime.now().strftime('%Y%m%d_%H%M%S%f') + extension
        path: Path = TMP_DATA_DIR / name

        # gp_file_save(): http://www.gphoto.org/doc/api/gphoto2-file_8c.html#a56e413d5ea3abc6e512b92c5861b9594
        preview_file.save(str(path))
        _log.info(f'Saved preview at {path}')

        return get_camera_name(camera), path


async def handle_gphoto_error(interaction: discord.Interaction[commands.Bot],
                              error: gp.GPhoto2Error,
                              text: str) -> None:
    """
    Nicely handle an error from gPhoto2.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction to
        which to send the error message.
        error (gp.GPhoto2Error): The error.
        text (str): Text explaining what went wrong.
    """

    # Build an embed to nicely display the error
    embed = error_embed(
        error,
        text,
        'gPhoto2 Error',
        show_details=False,
        show_traceback=False
    )

    # Add the error code and message
    embed.add_field(
        name=f'Code: {error.code}',
        value=trunc(error.string if error.string else '*[No details given]*',
                    const.EMBED_FIELD_VALUE_LENGTH),
        inline=False
    )

    await update_interaction(interaction, embed)

    # Log details
    _log.error(f"{text} (Code {error.code}): "
               f"{error.string if error.string else '[No details given]'}")
    _log.debug(f'Traceback on {gp.GPhoto2Error.__name__}:', exc_info=True)


async def handle_no_camera_error(
        interaction: discord.Interaction[commands.Bot]) -> None:
    """
    Send an error embed in response to an interaction indicating that no camera
    was found.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction to
        which to send the error message.
    """

    _log.warning(f'Failed to get a camera when processing '
                 f'{utils.app_command_name(interaction)}')
    embed = utils.contrived_error_embed('No camera detected',
                                        'Missing Camera')
    await utils.update_interaction(interaction, embed)


async def setup(_):
    _log.info('Loaded utils.gphoto extension')
