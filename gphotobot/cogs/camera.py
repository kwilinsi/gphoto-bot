import asyncio
import logging
import re
from collections import defaultdict
from typing import Callable, Optional, Awaitable

import discord
from discord import app_commands, ui, InteractionMessage
from discord.ext import commands

from gphotobot.bot import GphotoBot
from gphotobot.conf import settings
from gphotobot.libgphoto import GCamera, gmanager, gutils, NoCameraFound
from gphotobot.libgphoto.rotation import Rotation
from gphotobot.sql import async_session_maker
from gphotobot.utils import const, utils

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

                # Create and send the message
                view = CameraSelectorView(camera_dict)
                await interaction.followup.send(
                    content="Choose a camera from the list below to edit it:",
                    view=view
                )
                view.message = await interaction.original_response()
            except NoCameraFound:
                await gutils.handle_no_camera_error(interaction)

            return

        # Search for the user's desired camera
        matching_cameras: list[GCamera] = await gmanager.get_camera(camera)
        n = len(matching_cameras)
        camera = utils.trunc(camera, 100)  # truncate excessive user input

        # If there's one match, open the edit window
        if n == 1:
            view = CameraEditor(matching_cameras[0])
            await interaction.followup.send(
                embed=await view.get_embed(), view=view
            )
            view.message = await interaction.original_response()
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
        view = CameraSelectorView(camera_dict)
        await interaction.followup.send(embed=embed, view=view)
        view.message = await interaction.original_response()


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

        # The message using this view
        self.message: Optional[InteractionMessage] = None

    async def select_camera(self,
                            interaction: discord.Interaction[commands.Bot],
                            camera_label: str):
        await interaction.response.defer()

        camera: GCamera = self.cameras[camera_label]
        view = CameraEditor(camera)
        view.message = self.message
        await self.message.edit(
            content='',
            embed=await view.get_embed(),
            view=view
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


class CameraEditor(ui.View):
    def __init__(self, camera: GCamera):
        """
        Initialize a camera editor view on a given camera.

        Args:
            camera:
        """

        super().__init__()

        # The camera being edited
        self.camera: GCamera = camera

        # The message using this view
        self.message: Optional[InteractionMessage] = None

        self._embed: Optional[discord.Embed] = None

    async def get_embed(self, rebuild: bool = False) -> discord.Embed:
        """
        Get the message embed. If it doesn't exist yet, it is built.

        Args:
            rebuild (bool, optional): Whether to rebuild the embed even if it
            already exists. Defaults to False.

        Returns:
            discord.Embed: The embed.
        """

        if self._embed is None or rebuild:
            return await self.build_embed()
        else:
            return self._embed

    async def build_embed(self) -> discord.Embed:
        """
        Rebuild the embed that constitutes the main message. This view is
        attached to that message.

        The embed is stored as self.embed.

        Returns:
            discord.Embed: The embed.
        """

        name = self.camera.trunc_name(const.EMBED_TITLE_LENGTH - 10)

        self._embed = utils.default_embed(
            title='Editing | ' + name,
            description=await self.camera.info()
        )

        return self._embed

    @ui.button(label='Change Rotation', style=discord.ButtonStyle.secondary)
    async def rotate(self,
                     interaction: discord.Interaction,
                     _: ui.Button) -> None:
        """
        When the user clicks "Rotation", show a modal asking them to change it.

        Args:
            interaction: The interaction.
            _: The button.
        """

        modal = RotationModal(self.update_preview_rotation)
        await interaction.response.send_modal(modal)

    @ui.button(label='Done', style=discord.ButtonStyle.primary)
    async def save(self,
                   interaction: discord.Interaction,
                   _: ui.Button) -> None:
        """
        Save changes to the camera to the database, disable all the buttons,
        and stop listening for interactions.

        Args:
            interaction: The interaction.
            _: The button.
        """

        await interaction.response.defer(thinking=True, ephemeral=True)

        # Disable all the buttons
        for child in self.children:
            if hasattr(child, 'disabled'):
                child.disabled = True
        self.stop()

        # Save the camera's new settings to the database, if any changed
        saved = False
        if not self.camera.synced_with_database:
            async with async_session_maker() as session, session.begin():
                await self.camera.sync_with_database(session)
                saved = True

        # Mark the embed done/disabled
        self._embed.title = 'Done | ' + \
                            self.camera.trunc_name(const.EMBED_TITLE_LENGTH - 7)
        self._embed.set_footer(text='Edit with /camera edit')
        self._embed.color = settings.DISABLED_EMBED_COLOR
        await self.refresh_display(rebuild=False)

        # Send "done" message
        if saved:
            await interaction.followup.send(
                'Finished editing and saved changes.', ephemeral=True
            )
        else:
            await interaction.followup.send(
                'Finished editing. There was nothing to save.', ephemeral=True
            )

    async def update_preview_rotation(self,
                                      interaction: discord.Interaction,
                                      rot: Rotation) -> None:
        """
        Update the preview rotation for this camera.

        Args:
            interaction: The interaction from the user that triggered this.
            rot: The new rotation.
        """

        if self.camera.get_rotate_preview() == rot:
            self.camera.set_rotate_preview(
                rot)  # in case it was actually None
            embed = utils.default_embed(
                title='Rotation Already Set',
                text='The preview rotation for this camera is already '
                     f'**{rot}**. Nothing was changed.'
            )
            await interaction.response.send_message(embed=embed,
                                                    ephemeral=True)
        else:
            self.camera.set_rotate_preview(rot)
            await self.refresh_display()

    async def refresh_display(self, rebuild: bool = True) -> None:
        """
        Edit this view message, refreshing the display.

        Args:
            rebuild (bool, optional): Whether to rebuild the embed before
            refreshing. Defaults to True.
        """

        await self.message.edit(embed=await self.get_embed(rebuild), view=self)


class RotationModal(ui.Modal, title='Change the Preview Rotation'):
    # This RegEx pattern extracts numbers (positive/negative floats and ints)
    # from a string. It could probably be more succinct. Here's a test string
    # for it:
    # Match these: -1 -4.98 .3 8135 0-deg 9abc 1. | Not these: 12-3 0.4.3 .-2.4
    NUMBER_EXTRACT = r'(?<![\d.-])-?(?:\d+\.\d*|\d*\.?\d+)(?![\d.]|-\d)'

    # The timelapse name
    rotation = ui.TextInput(
        label='New Rotation',
        required=True,
        placeholder='Enter 0, 90, 180, 270 (or -90) degrees',
        max_length=30
    )

    def __init__(self,
                 callback: Callable[[discord.Interaction, Rotation],
                 Awaitable[None]]):
        """
        Initialize this modal.

        Args:
            callback: The function to call with the new Rotation.
        """

        super().__init__()
        self.callback: Callable[[discord.Interaction, Rotation],
        Awaitable[None]] = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the user's input.

        Args:
            interaction: The interaction.
        """

        try:
            rot = self.validate_input()
            await interaction.response.defer()
            await self.callback(interaction, rot)
        except ValueError:
            embed = utils.contrived_error_embed(
                title='Invalid Rotation Input',
                text="I couldn't understand that. Enter a number of degrees: "
                     "0, 90, 180, or 270. Or use 'none' to reset, 'half' for "
                     "180 turn, etc."
            )
            interaction.response.send_message(embed=embed, ephemeral=True)
            return
        except AssertionError:
            embed = utils.contrived_error_embed(
                title='Invalid Rotation Input',
                text="Invalid rotation. Only quarter turns are supported: "
                     "0, 90, 180, or 270 degrees. Make sure you only enter "
                     "one measurement."
            )
            interaction.response.send_message(embed=embed, ephemeral=True)
            return

    def validate_input(self) -> Rotation:
        """
        Validate the user's input, identifying the selected Rotation.

        Returns:
            Rotation: The selected rotation.

        Raises:
            ValueError: If the input can't be parsed as a Rotation.
            AssertionError: If the input seems to give more than one number of
            degrees, like "90 180", or an unsupported number, like "32".
        """

        rot_str: str = self.rotation.value.strip().lower()

        # Fast exit on words for 0 degrees
        if rot_str in ('none', 'no', 'disable', 'off', 'stop', 'clear', '0',
                       'zero', 'null', 'nil', 'reset'):
            return Rotation.DEGREE_0

        # Check for numbers
        nums = [float(m) % 360
                for m in re.findall(self.NUMBER_EXTRACT, rot_str)]

        # If no numbers are present, try words
        if len(nums) == 0:
            if rot_str in ('half', 'flip', 'upside-down', 'upside down',
                           'one hundred eighty'):
                return Rotation.DEGREE_180
            elif rot_str in ('quarter', 'ninety'):
                nums = [90]
            elif rot_str == 'two hundred seventy':
                nums = [270]
            else:
                raise ValueError()

        # If the user specified 'counter-clockwise', reverse all degrees
        for s in ('counterclockwise', 'counter-clockwise'):
            if s in rot_str:
                nums = tuple({(360 - n) % 360 for n in nums})
                break

        # If multiple measurements were given, it's invalid
        if len(nums) > 1:
            raise ValueError()

        # Try to get the rotation
        try:
            return Rotation(nums[0])
        except ValueError:
            raise AssertionError()


async def setup(bot: GphotoBot):
    await bot.add_cog(Camera(bot))
    _log.info('Loaded Camera cog')
