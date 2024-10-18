from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import exc

from gphotobot.bot import GphotoBot
from gphotobot.utils import const, utils
from gphotobot.sql import async_session_maker
from gphotobot.sql.models import timelapses
from gphotobot.sql.models.timelapses import Timelapse, NAME_MAX_LENGTH
from .timelapse_creator import TimelapseCreator
from .timelapse_invalid_name import TimelapseInvalidNameView
from .validation import InvalidTimelapseNameError

_log = logging.getLogger(__name__)


class TimelapseCog(commands.Cog):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @staticmethod
    def get_timelapse_info(timelapse: Timelapse) -> str:
        """
        Get a formatted string with information about a timelapse. This is
        designed for Discord.

        Args:
            timelapse: The timelapse.

        Returns:
            str: The info string.
        """

        TIME_FORMAT = '%Y-%m-%d %I:%M:%S %p'

        # List basic known info
        info = (f'**State:** {timelapse.state}'
                f'\n**User ID:** {timelapse.user_id}'
                f'\n**Directory:** `{timelapse.directory}`'
                f'\n**Frames:** {timelapse.frames}'
                f'\n**Interval:** {utils.format_duration(timelapse.interval)}')

        # Add the start time if it's known
        if timelapse.start_time:
            time = timelapse.start_time.strftime(TIME_FORMAT)
            info += f'\n**Start Time:** {time}'

        # Add end time if known
        if timelapse.end_time:
            time = timelapse.end_time.strftime(TIME_FORMAT)
            info += f'\n**End Time:** {time}'

        # Add the total frames (number of frames when it stops) if known
        if timelapse.total_frames:
            info += f'\n**Total Frames:** {timelapse.total_frames}'

        return info

    @app_commands.command(description='Create a new timelapse',
                          extras={'defer': True})
    @app_commands.describe(
        name=f'A unique name (max {NAME_MAX_LENGTH} characters)'
    )
    async def create(self,
                     interaction: discord.Interaction[commands.Bot],
                     name: str) -> None:
        """
        Create a new timelapse.

        Args:
            interaction: The interaction.
            name: The user-input name for the timelapse.
        """

        # Defer a response
        await interaction.response.defer(thinking=True)

        # Create a new timelapse
        try:
            await TimelapseCreator.create_new(interaction, name)
        except InvalidTimelapseNameError as e:
            # Catch names that fail validation
            view = TimelapseInvalidNameView(interaction, e)
            await interaction.followup.send(embed=e.build_embed(), view=view)
            return

    @app_commands.command(description='Show all active timelapses',
                          extras={'defer': True})
    async def list(self,
                   interaction: discord.Interaction[commands.Bot]) -> None:
        """
        List all the currently active timelapses.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.
        """

        # Defer the interaction
        await interaction.response.defer(thinking=True)

        # Query active timelapses from database
        try:
            async with async_session_maker() as session:  # read-only session
                active_timelapses: list[Timelapse] = \
                    await timelapses.get_all_active(session)
        except exc.SQLAlchemyError as error:
            await utils.handle_err(
                interaction=interaction,
                error=error,
                text='Failed to get active timelapses from the database.'
            )
            return

        # Return if no timelapses
        if not active_timelapses:
            embed = utils.default_embed(
                title='No active timelapses',
                description="There aren't any active timelapses. "
                            "You can create one with `/timelapse create`."
            )
            await interaction.followup.send(embed=embed)
            return

        # Build an embed with a list of timelapses
        n = len(active_timelapses)
        embed = utils.default_embed(
            title="Active Timelapses",
            description=f"Found {n} active timelapse{'' if n == 1 else 's'}."
        )

        # If there are too many timelapses to fit, show as many as possible
        if n > const.EMBED_FIELD_MAX_COUNT:
            active_timelapses = \
                active_timelapses[:const.EMBED_FIELD_MAX_COUNT - 1]

        # Add info for each timelapse
        for timelapse in active_timelapses:
            embed.add_field(
                name=timelapse.name,
                value=self.get_timelapse_info(timelapse),
                inline=False
            )

        # Again, if there are too many timelapses to fit, indicate how many
        # were omitted
        if n > const.EMBED_FIELD_MAX_COUNT:
            omitted = n - const.EMBED_FIELD_MAX_COUNT - 1
            embed.add_field(
                name=f"{omitted} more...",
                value=f"{omitted} more timelapses not shown",
                inline=False
            )

        # Send the embed
        await interaction.followup.send(embed=embed)
