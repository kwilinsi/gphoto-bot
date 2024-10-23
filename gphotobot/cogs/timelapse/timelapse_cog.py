from __future__ import annotations

import logging

from discord import app_commands, Embed, Interaction, utils as discord_utils
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

from gphotobot import const, GphotoBot, utils
from gphotobot.libgphoto import GCamera, gmanager, gutils, NoCameraFound
from gphotobot.sql import async_session_maker, State, timelapses, Timelapse
from gphotobot.sql.models.timelapses import NAME_MAX_LENGTH
from .control_panel import TimelapseControlPanel
from .timelapse_creator import TimelapseCreator
from .timelapse_invalid_name import TimelapseInvalidNameView
from .validation import InvalidTimelapseNameError

_log = logging.getLogger(__name__)


class TimelapseCog(commands.GroupCog,
                   group_name='timelapse',
                   group_description='Manage automated timelapses'):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    async def get_timelapse_info(self, timelapse: Timelapse) -> str:
        """
        Get a formatted string with information about a timelapse. This is
        designed for Discord.

        Args:
            timelapse: The timelapse.

        Returns:
            str: The info string.
        """

        user = self.bot.get_user(timelapse.user_id)
        if user is None:
            _log.debug(f'User {timelapse.user_id} not cached: '
                       f'fetching via API call')
            user = await self.bot.fetch_user(timelapse.user_id)

        # List basic known info
        return (f'**Status:** {timelapse.state.name}'
                f'\n**Owner:** {user.mention}'
                f'\n**Directory:** `{timelapse.directory}`')

    @app_commands.command(description='Create a new timelapse',
                          extras={'defer': True})
    @app_commands.describe(
        name=f'A unique name (max {NAME_MAX_LENGTH} characters)'
    )
    async def create(self,
                     interaction: Interaction[GphotoBot],
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
                   interaction: Interaction[GphotoBot]) -> None:
        """
        List all the currently active timelapses.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Defer the interaction
        await interaction.response.defer(thinking=True)

        # Query active timelapses from database
        try:
            async with async_session_maker() as session:  # read-only session
                active_timelapses: list[Timelapse] = \
                    await timelapses.get_active_timelapses(session)
        except SQLAlchemyError as error:
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
                name=f'__{discord_utils.escape_markdown(timelapse.name)}__',
                value=await self.get_timelapse_info(timelapse),
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

    @app_commands.command(description='Reload timelapse from the database '
                                      'to update the scheduler',
                          extras={'defer': True})
    async def reload(self,
                     interaction: Interaction[GphotoBot]) -> None:
        # Defer the interaction
        await interaction.response.defer(thinking=True)

        # Reload the timelapses
        from .execute import TIMELAPSE_COORDINATOR
        msg: str = await TIMELAPSE_COORDINATOR.run()

        # Send the summary message
        await interaction.followup.send(embed=utils.default_embed(
            title='Reloaded Timelapses',
            description=msg
        ))

    @app_commands.command(description='Show information about a timelapse',
                          extras={'defer': True})
    @app_commands.describe(name=f'The name of the timelapse')
    async def show(self,
                   interaction: Interaction[GphotoBot],
                   name: str) -> None:
        """
        Show a view with information about a timelapse.

        Args:
            interaction: The interaction that triggered this UI event.
            name: The name of the timelapse.
        """

        # Defer a response
        await interaction.response.defer(thinking=True)

        # Open db session to get the matching timelapse. Handle any errors
        try:
            async with async_session_maker(expire_on_commit=False) as session:
                result = tuple(r for r in await session.scalars(
                    select(Timelapse)
                    .where(func.lower(Timelapse.name) == name.lower())  # noqa
                ))
                assert len(result) == 1  # Make sure there's exactly 1 result
        except SQLAlchemyError as error:
            await utils.handle_err(
                interaction=interaction,
                error=error,
                title='Database Error',
                text='Failed to locate the matching timelapse in the database.'
            )
            return
        except AssertionError:
            clean: str = discord_utils.escape_markdown(name)
            embed: Embed = utils.contrived_error_embed(
                title='No Matches',
                text=f"There aren't any timelapses called **\"{clean}\"**. "
                     f"You can create one with `/timelapse create`."
            )
            await utils.update_interaction(interaction, embed)
            return

        # Get the camera associated with the timelapse
        try:
            camera: GCamera = await gmanager.get_camera(result[0].camera)
        except NoCameraFound:
            clean: str = discord_utils.escape_markdown(name)
            await gutils.handle_no_camera_error(
                interaction,
                message=f"Couldn't find a camera called **\"{clean}\"**"
            )
            return

        # Create and send the timelapse control panel view
        view = TimelapseControlPanel(interaction, result[0], camera)
        await interaction.followup.send(embed=await view.build_embed(),
                                        view=view)

    @show.autocomplete('name')
    async def timelapse_name_autocomplete(
            self,
            _: Interaction[GphotoBot],
            current: str) -> "list"[app_commands.Choice[str]]:
        """
        This handles autocomplete for the "name" parameter of `/timelapse show`.
        It allows the user to start typing a name and have it autofill valid
        timelapse names.

        Args:
            _: The interaction that triggered this UI event.
            current: The current text that the user has typed so far.

        Returns:
            A list of autocomplete choices.
        """

        try:
            # Open db session to query for names like the one given by the user
            async with async_session_maker() as session:  # read-only session

                # If the user hasn't typed anything yet, just go with everything
                # that isn't FINISHED
                if not current.strip():
                    stmt = (select(Timelapse)
                            .where(Timelapse.state != State.FINISHED))
                else:
                    stmt = (select(Timelapse)
                            .where(Timelapse.name.ilike(f'%{current}%')))

                # Execute the statement
                result = await session.scalars(stmt)

                # Return a list of up to 25 matching names
                return [app_commands.Choice(name=tl.name, value=tl.name)
                        for tl in result][:25]

        except SQLAlchemyError as error:
            _log.warning("Failed to query db for timelapses with "
                         f"names like '%{current}%'", error)
            return []  # Idk, just return an empty list
