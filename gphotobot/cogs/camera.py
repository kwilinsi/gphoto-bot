from functools import partial
import logging
import re
from typing import Callable, Optional, Awaitable

import discord
from discord import app_commands, ui, InteractionMessage
from discord.ext import commands
from gphoto2 import GPhoto2Error

from gphotobot.bot import GphotoBot
from gphotobot.conf import settings
from gphotobot.libgphoto import GCamera, gmanager, gutils, NoCameraFound
from gphotobot.libgphoto.rotation import Rotation
from gphotobot.sql import async_session_maker
from gphotobot.utils import const, utils
from gphotobot.utils.base.view import BaseView
from .helper.camera_selector import CameraSelector, generate_camera_dict

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
            camera_list: list[GCamera] = await gmanager.all_cameras(
                force_reload=True
            )
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
                # Send a camera selector
                await CameraSelector(
                    interaction=interaction,
                    callback=partial(CameraEditor.create_editor,
                                     interaction=interaction),
                    on_cancel=interaction.delete_original_response,
                    cameras=await generate_camera_dict(),
                    message="Choose a camera from the list below to edit it:",
                    edit_response=False
                ).refresh_display()
            except NoCameraFound:
                await gutils.handle_no_camera_error(interaction)

            return

        # Search for the user's desired camera
        matching_cameras: list[GCamera] = await gmanager.get_camera(camera)
        n = len(matching_cameras)
        camera = utils.trunc(camera, 100)  # truncate excessive user input

        # If there's one match, open an edit window
        if n == 1:
            await CameraEditor.create_editor(matching_cameras[0], interaction)
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

        # Send a camera selector
        await CameraSelector(
            interaction=interaction,
            callback=partial(
                CameraEditor.create_editor, interaction=interaction
            ),
            on_cancel=interaction.delete_original_response,
            cameras=await generate_camera_dict(matching_cameras),
            message=embed,
            edit_response=False
        ).refresh_display()


class CameraEditor(BaseView):
    def __init__(self, camera: GCamera, interaction: discord.Interaction):
        """
        Initialize a camera editor view on a given camera.

        Args:
            camera: The camera.
            interaction: The interaction. The original response is edited when
            refreshing the display.
        """
        super().__init__(
            interaction,
            permission_error_msg='Type `/camera edit` to edit a camera.'
        )

        # The camera being edited
        self.camera: GCamera = camera

        # The message using this view
        self.interaction: discord.Interaction = interaction
        self.message: Optional[InteractionMessage] = None

        self._embed: Optional[discord.Embed] = None

        _log.debug(f"Created a CameraEditor view for '{camera}'")

    @classmethod
    async def create_editor(cls,
                            camera: GCamera,
                            interaction: discord.Interaction):
        """
        Create a new camera editor for the given camera. The given interaction
        is used as the base for the view: the response is edited and replaced
        with the camera editor.

        Args:
            camera: The selected camera.
            interaction: This interaction is used to edit original response and
            replace with the CameraEditor view.
        """

        # Create a view, and refresh the display to send it
        await cls(camera, interaction).refresh_display(rebuild=True)

    async def build_embed(self, rebuild: bool = False) -> discord.Embed:
        """
        Build the embed that constitutes the main message. This view is attached
        to that message.

        The embed is stored as self.embed. If rebuild is False and there is a
        cached embed, that one is used instead.

        Returns:
            The embed.
        """

        # Use a cached embed if available and rebuild isn't forced
        if not rebuild and self._embed is not None:
            return self._embed

        # Get the camera name
        name = self.camera.trunc_name(const.EMBED_TITLE_LENGTH - 10)

        # Build the embed
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
            await self.refresh_display(rebuild=True)


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
