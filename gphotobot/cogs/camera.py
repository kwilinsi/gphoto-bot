from datetime import datetime
import logging
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from gphoto2 import GPhoto2Error

from gphotobot.bot import GphotoBot
from gphotobot.conf import APP_NAME, settings
from gphotobot.utils import const, gphoto, utils

_log = logging.getLogger(__name__)


class Camera(commands.Cog):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @app_commands.command(description='Show available cameras',
                          extras={'defer': True})
    async def camera(self,
                     interaction: discord.Interaction[commands.Bot]) -> None:
        """
        Show a list of available cameras.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.
        """

        await interaction.response.defer(thinking=True)

        try:
            n, cameras = gphoto.list_cameras()
        except gphoto.NoCameraFound:
            await gphoto.handle_no_camera_error(interaction)
            return
        except GPhoto2Error as e:
            await gphoto.handle_gphoto_error(
                interaction, e.__cause__, 'Failed to auto detect cameras'
            )
            return

        # Send the list of cameras
        embed = utils.default_embed(
            title='Found a camera' if n == 1 else f'Found {n} cameras'
        )

        # Add each camera as a field in the embed
        for index, camera in enumerate(cameras):
            if index == const.EMBED_FIELD_MAX_COUNT - 1 and \
                    n > const.EMBED_FIELD_MAX_COUNT:
                embed.add_field(
                    name=f'{n - index} more…',
                    value=f'Plus {n - index} more cameras not shown'
                )
                break

            # Add this camera
            embed.add_field(name=camera.trunc_name(),
                            value=camera.formatted_addr())

        # Send the list of cameras
        await interaction.followup.send(embed=embed)


@app_commands.guilds(settings.DEVELOPMENT_GUILD_ID)
class Photo(commands.GroupCog,
            group_name='photo',
            group_description=f'Manage {APP_NAME}'):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @app_commands.command(extras={'defer': True},
                          description='Take a test picture with the camera '
                                      'with the current camera configuration.')
    @app_commands.describe(camera='The name of the camera to use. If omitted, '
                                  'the first camera is selected automatically.')
    async def preview(self,
                      interaction: discord.Interaction[commands.Bot],
                      camera: Optional[str]):
        # Don't actually accept custom camera input for now
        if camera:
            embed = utils.contrived_error_embed(
                'Specifying a camera is not yet supported. Please omit the '
                'camera to use the default.'
            )
            await interaction.response.send_message(embed=embed)
            _log.info("Attempted to run '/photo preview' with custom camera. "
                      "Not yet supported.")
            return

        # Defer a response
        await interaction.response.defer(thinking=True)

        # Take a photo
        try:
            camera, path = gphoto.preview()
        except gphoto.NoCameraFound:
            await gphoto.handle_no_camera_error(interaction)
            return
        except GPhoto2Error as e:
            await gphoto.handle_gphoto_error(interaction, e,
                                             'Failed to capture preview')
            return

        # Create the result embed
        embed = discord.Embed(
            title='Camera Preview',
            description=f'Preview image from **{camera}**',
            color=settings.DEFAULT_EMBED_COLOR,
            timestamp=datetime.now()
        )

        # Add the preview image to the embed
        file = discord.File(path, filename=f'preview.{path.suffix}')
        embed.set_image(url=f'attachment://{file.filename}')

        # Send the embed
        await interaction.followup.send(file=file, embed=embed)

        # Delete the preview
        try:
            path.unlink()
            _log.debug(f'Deleted preview photo: {path}')
        except OSError as e:
            _log.warning(f"Attempted to delete preview photo, but it didn't "
                         f"exist for some reason: '{path}' {e}")


async def setup(bot: GphotoBot):
    await bot.add_cog(Camera(bot))
    _log.info('Loaded Camera cog')

    await bot.add_cog(Photo(bot))
    _log.info('Loaded Photo cog')
