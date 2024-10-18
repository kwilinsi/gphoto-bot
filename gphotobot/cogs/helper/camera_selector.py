from collections import defaultdict
from collections.abc import Awaitable, Callable
import logging
from typing import Optional

import discord
from discord import ButtonStyle, ui

from gphotobot.conf import settings
from gphotobot.libgphoto import gmanager
from gphotobot.libgphoto.gcamera import GCamera
from gphotobot.utils import const, utils

_log = logging.getLogger(__name__)


async def _set_unique_camera_labels(name: str,
                                    cameras: list[GCamera],
                                    camera_dict: dict[str, GCamera]):
    """
    This is a helper function for generate_camera_dict().

    Given one or more cameras with a particular name, give each of them
    unique names, and add them to self.cameras.

    Args:
        name: The name.
        cameras: One or more cameras with that name.
        camera_dict: The master dictionary to which to add label:camera pairs.
    """

    # Easy case: already unique name
    if len(cameras) == 1:
        camera_dict[name] = cameras[0]
        return

    # Harder case: shared names. Find something unique
    for cam in cameras:
        # Try using USB ports/device
        usb = cam.get_usb_bus_device_str()
        if usb:
            new_name = utils.trunc(
                name, const.SELECT_MENU_LABEL_LENGTH - len(usb) - 7
            ) + f' (USB {usb})'
            camera_dict[new_name] = cam
            continue

        # If that doesn't work, try the serial number
        serial = await cam.get_serial_number_short()
        if serial:
            new_name = utils.trunc(
                name, const.SELECT_MENU_LABEL_LENGTH - len(serial) - 10
            ) + f' (Serial {serial})'
            camera_dict[new_name] = cam
            continue

        # If that doesn't work, just add an incrementing number
        for i in range(1, len(cameras) + 1):
            new_name = utils.trunc(
                name, const.SELECT_MENU_LABEL_LENGTH - len(str(i)) - 4
            ) + f' (#{i})'
            if new_name not in camera_dict:
                camera_dict[new_name] = cam
                break


async def generate_camera_dict(cameras: Optional[list[GCamera]] = None) -> \
        dict[str, GCamera]:
    """
    Generate labels for a list of cameras.

    Args:
        cameras (list[GCamera]): The list of cameras. If this list is empty or
        None, the GCamera cache is used. Defaults to None.

        Returns:
            dict[str, GCamera]: A dictionary pairing labels with cameras.
        """

    # If cameras not specified, get them
    if not cameras:
        cameras = await gmanager.all_cameras()

    # Group cameras by name
    cameras_by_name: defaultdict[str, list[GCamera]] = defaultdict(list)
    for camera in cameras:
        name = utils.trunc(camera.name, const.SELECT_MENU_LABEL_LENGTH)
        cameras_by_name[name].append(camera)

    # This dictionary pairs labels with individual GCameras
    camera_dict: dict[str, GCamera] = {}

    # Assign a name to each camera
    for name, cams in cameras_by_name.items():
        await _set_unique_camera_labels(name, cams, camera_dict)

    return camera_dict


class Dropdown(ui.Select):
    def __init__(self,
                 cameras: dict[str, GCamera],
                 default_camera: Optional[GCamera],
                 callback: Callable[[GCamera], Awaitable[None]]):
        """
        Create dropdown selector with a list of cameras.

        Args:
            cameras: The list of camera names from which to choose.
            default_camera: The default camera to pre-select. None to disable.
            callback: The async function to call when a camera is selected.
        """

        self.cameras: dict[str, GCamera] = cameras
        self.callback_camera: Callable[[GCamera], Awaitable[None]] = callback

        # Pre-select default, if given
        default_label = None
        if default_camera is not None:
            for label, cam in cameras.items():
                if cam == default_camera:
                    default_label = label
                    break

        # Generate the list of options
        options: list[discord.SelectOption] = [
            discord.SelectOption(label=label, default=(label == default_label))
            for label in cameras.keys()
        ]

        # If there's just one, add a camera emoji. Why not?
        if len(options) == 1:
            options[0].emoji = settings.EMOJI_CAMERA

        super().__init__(placeholder='Select a camera…', options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        This is called when the user selects a camera. It identifies the
        associated GCamera and then runs the callback, if it was set.

        Args:
            interaction: The interaction.
        """

        await interaction.response.defer()

        # Get the selected GCamera
        camera: GCamera = self.cameras[self.values[0]]

        # Run the callback
        await self.callback_camera(camera)


class CameraSelector(ui.View):
    def __init__(self,
                 callback: Callable[[GCamera], Awaitable[None]],
                 on_cancel: Callable[[], Awaitable[None]],
                 cameras: dict[str, GCamera],
                 default_camera: Optional[GCamera],
                 cancel_danger: bool):
        """
        Create a view allowing the user to select a camera.

        Args:
            callback: The async function to call whTen a camera is selected.
            on_cancel: The async function to call if the user clicks Cancel.
            cameras: The list of cameras from which to choose.
            default_camera: The default selected camera. None for no default.
            cancel_danger: Whether the cancel button should be red/danger (True)
            or gray/secondary (False).
        """

        _log.debug('Creating CameraSelector view')
        super().__init__()

        # TODO prevent exceeding the limit of 25 menu options

        self.cameras: dict[str, GCamera] = cameras

        # Add the selection menu
        self.add_item(Dropdown(cameras, default_camera, callback))

        # Add the cancel callback
        self.on_cancel: Callable[[], Awaitable[None]] = on_cancel

        # If cancel shouldn't use the danger style, set to secondary style
        if not cancel_danger:
            utils.get_button(self, 'Cancel').style = ButtonStyle.secondary

    @ui.button(label='Cancel', style=ButtonStyle.danger,
               emoji=settings.EMOJI_CANCEL, row=1)
    async def cancel(self,
                     interaction: discord.Interaction,
                     _: ui.Button) -> None:
        """
        Cancel this selector.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.defer()
        await self.on_cancel()

    @classmethod
    async def create_selector(cls,
                              callback: Callable[[GCamera], Awaitable[None]],
                              on_cancel: Callable[[], Awaitable[None]],
                              message: str | discord.Embed,
                              cameras: dict[str, GCamera] = None,
                              interaction: discord.Interaction = None,
                              edit: bool = True,
                              default_camera: Optional[GCamera] = None,
                              cancel_danger: bool = True):
        """
        Create a new camera selector, and send it.

        Args:
            callback: The async function to call when the user selects a camera.
            on_cancel: The async function to call if the user clicks Cancel.
            cameras: The list of cameras from which to choose. If this is empty
            or None, the list of all detected cameras is used.
            interaction: The interaction to which to send the selector.
            message: The message text or embed to send to the user.
            edit: Whether to edit the original response to that interaction
            (True) or send a follow-up to a deferred interaction (False).
            default_camera: The default selected camera. Defaults to None.
            cancel_danger: Whether the cancel button should be red/danger (True)
            or gray/secondary (False). Defaults to True.

        Raises:
            NoCameraFound: If no cameras are provided, and none are detected
            on the system.
        """

        # Get all cameras, if omitted
        if not cameras:
            cameras = await generate_camera_dict()

        # Generate the camera selector view
        view = cls(callback, on_cancel, cameras, default_camera, cancel_danger)

        # Send it
        if interaction:
            if isinstance(message, str):
                content = message
                embed = None
            else:
                content = None
                embed = message

            # Either update the original message, or send a followup
            if edit:
                await interaction.edit_original_response(
                    content=content, embed=embed, view=view
                )
            else:
                await interaction.followup.send(
                    content=content, embed=embed, view=view
                )
