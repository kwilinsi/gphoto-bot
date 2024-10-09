import logging
from collections import defaultdict
from typing import Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

from gphotobot.bot import GphotoBot
from gphotobot.utils import const, utils
from gphotobot.libgphoto import GCamera, gmanager, gutils, NoCameraFound

_log = logging.getLogger(__name__)


class Camera(commands.GroupCog,
             group_name='camera',
             group_description='List and manage connected cameras'):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @app_commands.command(description='List all connected cameras',
                          extras={'defer': True})
    async def list(self,
                   interaction: discord.Interaction[commands.Bot]) -> None:
        """
        Show a list of connected cameras.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.
        """

        await interaction.response.defer(thinking=True)

        try:
            camera_list: list[GCamera] = await gmanager.all_cameras()
        except NoCameraFound:
            await gutils.handle_no_camera_error(interaction)
            return
        except GPhoto2Error as e:
            await gutils.handle_gphoto_error(
                interaction, e, 'Failed to auto detect cameras'
            )
            return

        # Send the list of cameras
        n = len(camera_list)
        embed: discord.Embed = utils.default_embed(
            title='Found a camera' if n == 1 else f'Found {n} cameras',
            description=f"There {'is 1' if n == 1 else f'are {n}'} "
                        f"connected camera{'' if n == 1 else 's'}:"
        )

        # Add each camera as a field in the embed
        for index, camera in enumerate(camera_list):
            if index == const.EMBED_FIELD_MAX_COUNT - 1 and \
                    n > const.EMBED_FIELD_MAX_COUNT:
                embed.add_field(
                    name=f'{n - index} more…',
                    value=f'Plus {n - index} more cameras not shown'
                )
                break

            # Add this camera
            embed.add_field(name=camera.trunc_name(),
                            value=await camera.info())

        # Send the list of cameras
        await interaction.followup.send(embed=embed)

    @app_commands.command(description="Edit a camera's settings",
                          extras={'defer': True})
    @app_commands.describe(camera='The name of the camera to edit. Omit to '
                                  'choose from a list.')
    async def edit(self,
                   interaction: discord.Interaction[commands.Bot],
                   camera: Optional[str]):
        """
        Allow the user to edit settings on a camera. If the camera name is
        omitted or blank, offer a list of cameras to choose from.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.
            camera (Optional[str]): The name of the camera to edit.
        """

        # Defer a response to give time to process
        await interaction.response.defer(thinking=True)

        # The user didn't specify a camera
        if camera is None or not camera.strip():
            try:
                cameras = await gmanager.all_cameras()
                camera_dict: dict[str, GCamera] = \
                    await generate_camera_dict(cameras)
                await interaction.followup.send(
                    content="Choose a camera from the list below to edit it:",
                    view=CameraSelectorView(camera_dict)
                )
            except NoCameraFound:
                await gutils.handle_no_camera_error(interaction)

            return

        # Search for the user's desired camera
        matching_cameras: list[GCamera] = await gmanager.get_camera(camera)
        n = len(matching_cameras)
        camera = utils.trunc(camera, 100)  # truncate excessive user input

        # If there's one match, open the edit window
        if n == 1:
            await utils.update_interaction(interaction, utils.default_embed(
                title='Edit',
                description=f"Editing '{camera}'...\n*[Not yet implemented]*"
            ))
            return

        # If there aren't any matching cameras, show an error
        if n == 0:
            embed = utils.contrived_error_embed(
                f"There's no available camera called **\"{camera}\"**. Try "
                f"`/camera list` for information on the available cameras or "
                f"`/camera edit` (without specifying a camera) to choose from "
                f"a list.",
                'No Camera Found'
            )
            await utils.update_interaction(interaction, embed)
            return

        # If there's more than 1 match, send a dropdown menu
        embed = utils.default_embed(
            title=f'Found {n} Matches',
            description=f"There's more than one camera called "
                        f"**\"{camera}\"**. Select one from the list below."
        )

        camera_dict: dict[str, GCamera] = \
            await generate_camera_dict(matching_cameras)
        await interaction.followup.send(
            embed=embed,
            view=CameraSelectorView(camera_dict)
        )


class CameraSelectorView(ui.View):
    def __init__(self, cameras: dict[str, GCamera]):
        super().__init__()

        # TODO prevent exceeding the limit of 25 menu options

        self.cameras: dict[str, GCamera] = cameras
        options: list[discord.SelectOption] = [
            discord.SelectOption(label=name)
            for name in cameras.keys()
        ]

        # Add the dropdown to this view
        dropdown = ui.Select(placeholder='Select a camera...',
                             options=options)
        dropdown.callback = lambda interation: (
            self.select_camera(interation, dropdown.values[0])
        )
        self.add_item(dropdown)

    async def select_camera(self,
                            interaction: discord.Interaction[commands.Bot],
                            camera_label: str):
        camera: GCamera = self.cameras[camera_label]
        return await interaction.response.send_message(
            content=f"You selected label '{camera_label}' for the camera "
                    f"at {camera.addr}",
        )


async def generate_camera_dict(cameras: list[GCamera]) -> \
        dict[str, GCamera]:
    """
    Generate labels for a list of cameras.

    Args:
        cameras (list[GCamera]): The list of cameras.

        Returns:
            dict[str, GCamera]: A dictionary pairing labels with cameras.
        """

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


async def _set_unique_camera_labels(name: str,
                                    cameras: list[GCamera],
                                    camera_dict: dict[str, GCamera]):
    """
    This is a helper function for generate_camera_dict().

    Given one or more cameras with a particular name, give each of them
    unique names, and add them to self.cameras.

    Args:
        name (str): The name.
        cameras (list[GCamera]): One or more cameras with that name.
        camera_dict (dict[str, GCamera]): The master dictionary to which
        to add label:camera pairs.
    """

    # Easy case: already unique name
    if len(cameras) == 1:
        camera_dict[name] = cameras[0]
        return

    # Harder case: shared names. Find something unique
    for cam in cameras:
        # Try using USB ports/device
        usb = cameras.get_usb_bus_device_str()
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
        for i in range(1, len(cams) + 1):
            new_name = utils.trunc(
                name, const.SELECT_MENU_LABEL_LENGTH - len(str(i)) - 4
            ) + f' (#{i})'
            if new_name not in camera_dict:
                camera_dict[new_name] = cam
                break


async def setup(bot: GphotoBot):
    await bot.add_cog(Camera(bot))
    _log.info('Loaded Camera cog')
