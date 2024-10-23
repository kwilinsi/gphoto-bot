import logging

import discord
from discord import app_commands
from discord.ext import commands

from gphotobot import utils

_log = logging.getLogger(__name__)


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot

    @app_commands.command(description='Test ping response',
                          extras={'ephemeral': True})
    async def ping(self,
                   interaction: discord.Interaction[commands.Bot]) -> None:
        """
        Ping the bot to confirm that it's only and test latency.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.
        """

        await interaction.response.send_message(
            f'Pong! (response='
            f'{utils.latency(interaction.created_at)})',
            ephemeral=True
        )

        msg = await interaction.original_response()
        latency = utils.latency(interaction.created_at,
                                msg.created_at)
        await msg.edit(content=f'{msg.content[:-1]}, '
                       f'total={latency})')


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
    _log.info('Loaded Ping cog')
