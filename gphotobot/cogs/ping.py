import discord
from discord.ext import commands

from gphotobot.utils import utils


class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(description='Test ping response')
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


async def setup(bot):
    await bot.add_cog(Ping(bot))
