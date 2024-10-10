import logging
from pathlib import Path
import re
from typing import Literal

import discord
from discord import app_commands, ui
from discord.ext import commands
from sqlalchemy import exc, func, select

from gphotobot.bot import GphotoBot
from gphotobot.conf import settings
from gphotobot.utils import const, utils
from gphotobot.sql import async_session_maker
from gphotobot.sql.models.timelapses import Timelapses, NAME_MAX_LENGTH

_log = logging.getLogger(__name__)


class InvalidTimelapseNameError(Exception):
    def __init__(self,
                 name: str,
                 problem: Literal['taken', 'taken_case', 'length',
                 'char', 'start_char'],
                 is_shortened: bool):
        """
        Initialize an exception that explains what's wrong about a particular
        user-attempted name.

        The recognized problems are:
        - 'taken': This name is already used by another timelapse in the db.
        - 'taken_case': The same as 'taken' except that the names are
        capitalized differently.
        - 'length': The name exceeds the maximum length.
        - 'char': The name uses one or more invalid characters.
        - 'start_char': The name starts with an invalid character.

        Args:
            name: The name the user attempted to use. More specifically, the
            name that makes the most sense for explaining the issue to the
            user. If the name had consecutive underscores, this may or may not
            have them removed.
            problem: The reason the name is invalid.
            is_shortened: Whether consecutive hyphens/underscores were
            shortened into a single character.
        """

        super().__init__()
        self.name = name
        self.problem = problem
        self.is_shortened = is_shortened


async def validate_name(name: str) -> str:
    """
    Validate a new timelapse name and return it.

    Args:
        name: The name to validate.

    Returns:
        The validated name. This may be different from the input name.

    Raises:
        InvalidTimelapseNameError: If the name is invalid.
    """

    # Consolidate consecutive hyphens/underscores
    n = re.sub(r'([_-])[-_]+', r'\1', name)
    is_shortened = name != n

    if len(n) > NAME_MAX_LENGTH or len(n) < 1:
        raise InvalidTimelapseNameError(n, 'length', is_shortened)

    if re.search(r'[^\w-]', n):
        raise InvalidTimelapseNameError(name, 'char', is_shortened)

    if not n[0].isalpha():
        raise InvalidTimelapseNameError(name, 'start_char', is_shortened)

    # Check database for duplicate name
    async with async_session_maker() as session:  # read-only session
        stmt = (select(Timelapses)
                .where(func.lower(Timelapses.name) == n.lower()))
        result: Timelapses = (await session.scalars(stmt)).first()
        if result is not None:
            raise InvalidTimelapseNameError(
                n, 'taken' if result.name == n else 'taken_case', is_shortened
            )

    return n


def determine_default_directory(name: str) -> Path:
    """
    Given a timelapse name, pick a default directory in which to store its
    pictures. The directory is not created, but it may already exist. However,
    if it does exist, it's guaranteed to be empty.

    Args:
        name: The name of the timelapse.

    Returns:
        The path to the automatically chosen directory.
    """

    root: Path = settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY

    # If the timelapse root doesn't exist, it's guaranteed that 'root / name'
    # doesn't have anything in it
    if not root.exists():
        return root / name

    # This shouldn't ever happen, but it's possible that the default timelapse
    # root dir was created as a file since the program started
    new: Path = utils.get_unique_path(root, lambda p: not p.is_file())
    if new != root:
        _log.warning(f"The default timelapse directory is a file: '{root}'. "
                     f"Changing it to '{new}'")
        settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY = new
        root = new

    # Try using the timelapse name as a directory name. If that doesn't work,
    # keep adding numbers to it until it does.
    return utils.get_unique_path(
        root / name,
        lambda p: not p.exists() or  # Either doesn't exist, or
                  (p.is_dir() and not any(p.iterdir()))  # empty directory
    )


class Timelapse(commands.Cog):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @staticmethod
    def get_timelapse_info(timelapse: Timelapses) -> str:
        """
        Get a formatted string with information about a timelapse. This is
        designed for Discord.

        Args:
            timelapse: The timelapse.

        Returns:
            str: The info string.
        """

        TIME_FORMAT = '%Y-%m-%d %I:%M:%S %p'

        # List whether it's running/finished/active
        if timelapse.is_running:
            info = f'**Running:** YES'
        elif timelapse.is_finished:
            info = f'**Finished:** YES'
        else:
            info = f'**Active:** YES\n**Finished:** NO'

        # List basic known info
        info += (f'\n**User ID:** {timelapse.user_id}'
                 f'\n**Directory:** `{timelapse.directory}`'
                 f'\n**Frames:** {timelapse.frames}'
                 f'\n**Interval:** {utils.format_time(timelapse.interval)}')

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

        # Validate the user's timelapse name
        try:
            validated_name = await validate_name(name)
        except InvalidTimelapseNameError as e:
            view = TimelapseInvalidName(interaction, e)
            await interaction.followup.send(embed=view.embed(), view=view)
            return

        # Create a new timelapse
        view = TimelapseCreator(interaction, validated_name)
        await view.refresh_display()
        # await interaction.followup.send(embed=view.embed(), view=view)

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
                active_timelapses: list[Timelapses] = \
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


class TimelapseInvalidName(ui.View):
    # The maximum number of attempts the user can make with the same problem
    # before this view is auto cancelled
    MAX_CONSECUTIVE_ATTEMPTS: int = 5

    def __init__(self,
                 interaction: discord.Interaction[commands.Bot],
                 error: InvalidTimelapseNameError):
        """
        Initialize an invalid name taken view to tell the user that they need
        to pick a different name (and help them do so).

        Args:
            interaction: The interaction that triggered this view.
            error: The error with info on why the name is invalid.
        """

        super().__init__()

        self.interaction = interaction
        self.error: InvalidTimelapseNameError = error

        # The number of consecutive times the user has given an invalid name
        # with the same problem
        self.attempt: int = 1

    def embed(self) -> discord.Embed:
        """
        Build an embed that explains that the name is already taken.

        Returns:
            An embed.
        """

        # Build a user-friendly message explaining what they did wrong

        if self.error.problem == 'taken' or self.error.problem == 'taken_case':
            msg = (f"Sorry, there is already a timelapse called "
                   f"**\"{self.error.name}\"** in the database. You must "
                   f"choose a unique name to create a timelapse.")
            if self.error.problem == 'taken_case':
                msg += ("\n\nDifferent capitalization doesn't count: \"name\" "
                        "and \"NaMe\" are not sufficiently unique.")
        elif self.error.problem == 'too_long':
            name_trunc = utils.trunc(self.error.name, NAME_MAX_LENGTH,
                                     escape_markdown=True)
            msg = (f"Sorry, your timelapse name **\"{name_trunc}**\" is too "
                   f"long. Timelapse names can't be longer than "
                   f"{NAME_MAX_LENGTH} characters.")
        elif self.error.problem == 'char':
            # Explain which characters are allowed. Include the lines about
            # starting with a letter and not having spaces only if the user
            # violated those parts

            name_esc = utils.trunc(self.error.name, NAME_MAX_LENGTH,
                                   escape_markdown=True)
            msg = (f"Sorry, your timelapse name **\"{name_esc}\"** isn't "
                   "valid. Names can only use letters, numbers, hyphens, and "
                   "underscores.")
            if not self.error.name[0].isalpha():
                msg = msg[:-1] + ', and they must start with a letter.'
            if re.search(r'\s', self.error.name):
                msg += ' Spaces are not allowed.'
        elif self.error.problem == 'start_char':
            msg = (f"Sorry, your timelapse name **\"{self.error.name}\"** "
                   "isn't valid. Names must __start with a letter__ and use "
                   "only letters, numbers, hyphens, and underscores.")
        else:
            raise ValueError(f"Unreachable: problem='{self.error.problem}'")

        # Put the error message in an embed
        embed = utils.contrived_error_embed(
            text=msg,
            title='Error: Invalid Name'
        )

        # If the user had multiple hyphens/underscores, add a note about that
        if self.error.is_shortened:
            embed.add_field(
                name='Note',
                value='Multiple consecutive hyphens/underscores '
                      'are automatically shortened to just one.',
                inline=False
            )

        return embed

    async def new_invalid_name(self, error: InvalidTimelapseNameError) -> None:
        """
        Call this when the user gives another invalid name.

        Args:
            error: The new error.
        """

        if error.problem == self.error.problem:
            self.attempt += 1
            cancelled = self.attempt == self.MAX_CONSECUTIVE_ATTEMPTS

            header = (f'Still Invalid (Attempt '
                      f'{self.attempt}/{self.MAX_CONSECUTIVE_ATTEMPTS})')
            if error.name == self.error.name:
                text = "That name is still invalid."
                if not cancelled:
                    text += " Please try again with a **new** name."
            else:
                self.error = error
                text = "This name is invalid for the same reason."

            embed = self.embed()
            embed.add_field(name=header, value=text, inline=False)

            if cancelled:
                embed.add_field(
                    name='Max Attempts Reached',
                    value='Timelapse creation automatically cancelled.',
                    inline=False
                )
                # Disable all buttons
                for child in self.children:
                    if hasattr(child, 'disabled'):
                        child.disabled = True

                # Show embed is disabled
                # noinspection PyDunderSlots
                embed.color = settings.DISABLED_ERROR_EMBED_COLOR

                # Stop listening to interactions on this view
                self.stop()
        else:
            # Otherwise, this is a new error
            self.attempt = 1
            self.error = error
            embed = self.embed()

        await self.interaction.edit_original_response(
            embed=embed, view=self
        )

    @ui.button(label='Change Name', style=discord.ButtonStyle.primary,
               emoji=settings.EMOJI_EDIT)
    async def input_new_name(self,
                             interaction: discord.Interaction,
                             _: ui.Button) -> None:
        """
        Show a modal prompting the user to enter a new name.

        Args:
            interaction: The interaction.
            _: This button.
        """

        modal = NewNameModal(self)
        await interaction.response.send_modal(modal)

    @ui.button(label='Cancel', style=discord.ButtonStyle.secondary,
               emoji=settings.EMOJI_CANCEL)
    async def cancel(self,
                     interaction: discord.Interaction,
                     _: ui.Button) -> None:
        """
        Cancel creating a timelapse.

        Args:
            interaction: The interaction.
            _: This button.
        """

        self.stop()
        await interaction.response.defer()  # acknowledge the interaction
        await self.interaction.delete_original_response()


class NewNameModal(ui.Modal, title='Enter a New Name'):
    # The timelapse name
    name = ui.TextInput(
        label='Name',
        required=True,
        placeholder='Enter a new, valid name',
        min_length=1,
        max_length=NAME_MAX_LENGTH
    )

    def __init__(self, invalid_name_view: TimelapseInvalidName) -> None:
        """
        Initialize this modal, which prompts the user to enter a new name for
        a timelapse.

        Args:
            invalid_name_view: The view that spawned this modal.
        """

        super().__init__()
        self.invalid_name_view = invalid_name_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the new name, validating it and proceeding to the next stage
        if the name is good.

        Args:
            interaction: The interaction.
        """

        # Defer a response, as we'll be editing an existing message rather than
        # sending a new one
        await interaction.response.defer()

        # Validate the user's timelapse name
        try:
            validated_name = await validate_name(self.name.value)
        except InvalidTimelapseNameError as e:
            await self.invalid_name_view.new_invalid_name(e)
            return

        # Disable the invalid name view, as it's no longer needed
        self.invalid_name_view.stop()

        # Replace the error message with the creator panel
        creator_view = TimelapseCreator(self.invalid_name_view.interaction,
                                        validated_name)
        await creator_view.refresh_display()


class TimelapseCreator(ui.View):
    def __init__(self, interaction: discord.Interaction, name: str):
        """
        Create a new view for helping the user make a timelapse.

        Args:
            interaction: The interaction that led to this view. This is used to
            get the original message to edit it as changes are made.
            name: The already-validated name of the timelapse.
        """

        super().__init__()
        self.interaction = interaction
        self.name = name
        self.user: discord.User | discord.Member = interaction.user
        self.directory = determine_default_directory(name)

    async def refresh_display(self) -> None:
        """
        Edit the original interaction response message, updating it with this
        view and embed.
        """

        await self.interaction.edit_original_response(
            embed=self.build_embed(), view=self
        )

    def build_embed(self) -> discord.Embed:
        """
        Construct an embed with the info about this timelapse. This embed is
        associated with the buttons in this view.

        Returns:
            The embed.
        """

        # If the directory is over 50 characters, put it on its own line
        if len(str(self.directory)) > 50:
            directory = f'\n`{self.directory}`'
        else:
            directory = f' `{self.directory}`'

        embed = utils.default_embed(
            title='Create a Timelapse',
            description=f"**Name:** {self.name}\n"
                        f"**Creator:** {self.user.mention}\n"
                        f"**Directory:**{directory}"
        )

        return embed

    @ui.button(label='Done', style=discord.ButtonStyle.success,
               emoji=settings.EMOJI_DONE_CHECK, row=0)
    async def done(self,
                   interaction: discord.Interaction,
                   button: ui.Button) -> None:
        button.label = 'Start'
        await interaction.response.send_message(content='Done!',
                                                ephemeral=True)
        await self.refresh_display()

    @ui.button(label='Info', style=discord.ButtonStyle.primary,
               emoji=settings.EMOJI_INFO, row=0)
    async def info(self,
                   interaction: discord.Interaction,
                   _: ui.Button) -> None:
        await interaction.response.send_message(
            content='This is some info on timelapses!',
            ephemeral=True
        )

    @ui.button(label='Cancel', style=discord.ButtonStyle.danger,
               emoji=settings.EMOJI_CANCEL, row=0)
    async def cancel(self,
                     interaction: discord.Interaction,
                     _: ui.Button) -> None:
        await interaction.response.send_message(
            content='Cancelling!',
            ephemeral=True
        )


async def setup(bot: GphotoBot):
    await bot.add_cog(Timelapse(bot))
    _log.info('Loaded Timelapse cog')
