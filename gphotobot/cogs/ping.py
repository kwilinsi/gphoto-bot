import logging

import discord
from discord.ext import commands

from gphotobot.utils import utils

_log = logging.getLogger(__name__)


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot

    @discord.app_commands.command(description='Test ping response',
                                  extras={'ephemeral': True})
    async def ping(self, interaction: discord.Interaction):
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
    _log.debug('Loaded Ping cog')
