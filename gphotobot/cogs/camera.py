import logging
import re

import discord
from discord.app_commands.errors import AppCommandError
import gphoto2 as gp
from discord.ext import commands

from gphotobot.conf import settings
from gphotobot.utils import utils, const


_log = logging.getLogger(__name__)


class Camera(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[discord.Client],
            error: AppCommandError) -> None:
        """
        Handle errors thrown by slash commands in this cog.

        Args:
            interaction (discord.Interaction[discord.Client]): The slash
            command interaction.
            error (AppCommandError): The error.
        """

        # Get the slash command
        command = '/' + interaction.command.name

        try:
            # Switch to the original error if available
            if isinstance(error, discord.app_commands.CommandInvokeError):
                error = error.original

            # Send an error response in Discord, and log the error and stacktrace
            await utils.handle_err(
                interaction,
                error,
                f"Unexpected error while processing `{command}`.",
                log_text=f"Error processing '{command}'",
                show_details=True,
                show_traceback=True
            )
        except:
            # If there's an error handling the error, we have big problems
            _log.critical(
                f"Failed to handle an {error.__class__.__name__} error "
                f"raised while processing '{command}'",
                exc_info=True
            )

    @discord.app_commands.command(description='Show available cameras',
                                  extras={'defer': True})
    async def camera(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        # Auto detect available cameras
        try:
            cameras = list(gp.Camera.autodetect())
        except gp.GPhoto2Error as e:
            await utils.handle_gphoto_err(
                interaction, e, 'Failed to auto detect cameras'
            )

        # If no cameras found, exit
        if not cameras:
            await interaction.followup.send('No cameras detected.')
            return

        # Send the list of cameras
        n = len(cameras)
        cameras.sort(key=lambda x: x[0])
        embed = discord.Embed(
            title='Found a camera' if n == 1 else f'Found {n} cameras',
            color=settings.DEFAULT_EMBED_COLOR
        )

        # Add each cameras as a field in the embed
        for index, camera in enumerate(cameras):
            if index == const.EMBED_FIELD_MAX_COUNT - 1 and \
                    len(cameras) > const.EMBED_FIELD_MAX_COUNT:
                n = len(cameras) - index
                embed.add_field(
                    name=f'{n} more…',
                    value=f'Plus {n} more cameras not shown'
                )
                break

            # Add this camera
            name = utils.trunc(camera[0], const.EMBED_FIELD_NAME_LENGTH)
            addr = str(camera[1])

            match = re.match(r'usb:(\d+),(\d+)', addr)
            if match:
                addr = (f'USB port\n'
                        f'Bus {match.group(1)} | Device {match.group(2)}')

            addr = utils.trunc(addr, const.EMBED_FIELD_VALUE_LENGTH)
            embed.add_field(name=name, value=addr)

        # Send the list of cameras
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Camera(bot))
    _log.debug('Loaded Camera cog')
