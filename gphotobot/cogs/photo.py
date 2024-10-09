import asyncio
from datetime import datetime
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from gphoto2 import GPhoto2Error

from gphotobot.bot import GphotoBot
from gphotobot.conf import APP_NAME, settings
from gphotobot.utils import utils
from gphotobot.libgphoto import gmanager, gutils, NoCameraFound

_log = logging.getLogger(__name__)


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
            _log.info("Attempted to run '/photo preview' with custom camera. "
                      "Not yet supported.")
            await interaction.response.send_message(embed=embed)
            return

        # Defer a response
        await interaction.response.defer(thinking=True)

        # Take a photo
        try:
            gcamera = await gmanager.get_default_camera()
            path: Path = await gcamera.preview_photo()
        except NoCameraFound:
            await gutils.handle_no_camera_error(interaction)
            return
        except GPhoto2Error as e:
            await gutils.handle_gphoto_error(interaction, e,
                                             'Failed to capture preview')
            return

        # Create the result embed
        embed = discord.Embed(
            title='Camera Preview',
            description=f'Preview image from **{gcamera}**',
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
            await asyncio.to_thread(path.unlink)
            _log.debug(f'Deleted preview photo: {path}')
        except OSError as e:
            _log.warning(f"Attempted to delete preview photo, but it didn't "
                         f"exist for some reason: path='{path}', {e}")


async def setup(bot: GphotoBot):
    await bot.add_cog(Photo(bot))
    _log.info('Loaded Photo cog')
