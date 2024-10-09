import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from gphotobot.bot import GphotoBot
from gphotobot.utils import const, utils
from gphotobot.libgphoto import GCamera, gmanager, gutils, NoCameraFound

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
            title='Found a camera' if n == 1 else f'Found {n} cameras'
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
                            value=camera.formatted_addr())

        # Send the list of cameras
        await interaction.followup.send(embed=embed)


async def setup(bot: GphotoBot):
    await bot.add_cog(Camera(bot))
    _log.info('Loaded Camera cog')
