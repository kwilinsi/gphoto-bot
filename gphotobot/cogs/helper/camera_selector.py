from collections import defaultdict
from collections.abc import Awaitable, Callable
import logging
from typing import Optional

import discord
from discord import ButtonStyle, Embed, Interaction, Message, ui

from gphotobot import const, settings, utils
from gphotobot.libgphoto import GCamera, gmanager

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


class CameraSelector(utils.BaseView):
    def __init__(self,
                 parent: Interaction | utils.BaseView | Message,
                 callback: Callable[[GCamera], Awaitable[None]],
                 on_cancel: Callable[[], Awaitable[None]],
                 cameras: dict[str, GCamera],
                 message: str | discord.Embed,
                 default_camera: Optional[GCamera] = None,
                 cancel_danger: bool = True):
        """
        Create a view allowing the user to select a camera.

        Args:
            parent: The parent interaction, message, or view.
            callback: The async function to call whTen a camera is selected.
            on_cancel: The async function to call if the user clicks Cancel.
            cameras: The list of cameras from which to choose.
            message: The message to send to the user: either text or an embed.
            default_camera: The default selected camera, or none for no default
            selection. Defaults to None.
            cancel_danger: Whether the cancel button should be red/danger (True)
            or gray/secondary (False).
        """

        super().__init__(
            parent=parent,
            callback=callback,
            callback_cancel=on_cancel
        )

        # TODO prevent exceeding the limit of 25 menu options

        self.cameras: dict[str, GCamera] = cameras
        self.message: str | discord.Embed = message

        # Add the selection menu
        self.add_item(Dropdown(cameras, default_camera, callback))

        # Create the cancel button, which runs the cancel callback
        self.create_button(
            label='Cancel',
            style=ButtonStyle.danger if cancel_danger
            else ButtonStyle.secondary,
            emoji=settings.EMOJI_CANCEL,
            callback=self.run_cancel_callback
        )

        _log.debug('Created a CameraSelector view')

    async def build_embed(self, *args, **kwargs) -> Optional[Embed]:
        return NotImplemented

    async def refresh_display(self, *args, **kwargs) -> None:
        content = embed = None
        if isinstance(self.message, str):
            content = self.message
        else:
            embed = self.message

        await self.edit_original_message(
            content=content,
            embed=embed,
            view=self
        )
