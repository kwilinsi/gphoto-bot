import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from gphoto2 import GPhoto2Error

from gphotobot import APP_NAME, GphotoBot, settings, utils
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

        try:
            # Get the default camera
            camera = await gmanager.get_default_camera()

            # Capture and send the image
            async with gutils.preview_image_embed(camera) as (embed, file):
                await interaction.followup.send(file=file, embed=embed)
        except NoCameraFound:
            # No camera error occurs while trying to get the default camera
            await gutils.handle_no_camera_error(interaction)
        except GPhoto2Error as error:
            await gutils.handle_gphoto_error(
                interaction, error, 'Failed to capture preview'
            )


async def setup(bot: GphotoBot):
    await bot.add_cog(Photo(bot))
    _log.info('Loaded Photo cog')
