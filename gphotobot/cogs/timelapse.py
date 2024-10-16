from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import re
from typing import Literal, Optional

import discord
from discord import app_commands, ButtonStyle, ui, utils as discord_utils
from discord.ext import commands
from sqlalchemy import exc, func, select

from gphotobot.bot import GphotoBot
from gphotobot.conf import settings
from gphotobot.libgphoto import GCamera, gmanager, NoCameraFound
from gphotobot.utils import const, utils
from gphotobot.utils.validation_error import ValidationError
from gphotobot.utils.base.view import BaseView
from gphotobot.sql import async_session_maker
from gphotobot.sql.models import timelapses
from gphotobot.sql.models.timelapses import (Timelapses, NAME_MAX_LENGTH,
                                             DIRECTORY_MAX_LENGTH)
from .helper import timelapse_utils
from .helper.camera_selector import CameraSelector
from .helper.runtime_modal import ChangeRuntimeModal
from .helper.schedule import Schedule, ScheduleBuilder
from .helper.interval_modal import ChangeIntervalModal

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

    def build_embed(self) -> discord.Embed:
        """
        Build an embed that explains in user-friendly terms what's wrong with
        the name they tried to use.

        Returns:
            A new embed.
        """

        # Build a user-friendly message explaining what they did wrong

        if self.problem == 'taken' or self.problem == 'taken_case':
            msg = (f"Sorry, there is already a timelapse called "
                   f"**\"{self.name}\"** in the database. You must "
                   f"choose a unique name to create a timelapse.")
            if self.problem == 'taken_case':
                msg += ("\n\nDifferent capitalization doesn't count: \"name\" "
                        "and \"NaMe\" are not sufficiently unique.")
        elif self.problem == 'too_long':
            name_trunc = utils.trunc(self.name, NAME_MAX_LENGTH,
                                     escape_markdown=True)
            msg = (f"Sorry, your timelapse name **\"{name_trunc}**\" is too "
                   f"long. Timelapse names can't be longer than "
                   f"{NAME_MAX_LENGTH} characters.")
        elif self.problem == 'char':
            # Explain which characters are allowed. Include the lines about
            # starting with a letter and not having spaces only if the user
            # violated those parts

            name_esc = utils.trunc(self.name, NAME_MAX_LENGTH,
                                   escape_markdown=True)
            msg = (f"Sorry, your timelapse name **\"{name_esc}\"** isn't "
                   "valid. Names can only use letters, numbers, hyphens, and "
                   "underscores.")
            if not self.name[0].isalpha():
                msg = msg[:-1] + ', and they must start with a letter.'
            if re.search(r'\s', self.name):
                msg += ' Spaces are not allowed.'
        elif self.problem == 'start_char':
            msg = (f"Sorry, your timelapse name **\"{self.name}\"** "
                   "isn't valid. Names must __start with a letter__ and use "
                   "only letters, numbers, hyphens, and underscores.")
        else:
            raise ValueError(f"Unreachable: problem='{self.problem}'")

        # Put the error message in an embed
        embed = utils.contrived_error_embed(
            text=msg,
            title='Error: Invalid Name'
        )

        # If the user had multiple hyphens/underscores, add a note about that
        if self.is_shortened:
            embed.add_field(
                name='Note',
                value='Multiple consecutive hyphens/underscores '
                      'are automatically shortened to just one.',
                inline=False
            )

        return embed


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


def validate_directory(directory: str) -> Path:
    """
    Validate a new directory path, and return it as a pathlib Path. If the input
    directory isn't absolute, it is appended to the default timelapse directory
    root.

    Args:
        directory: The directory to validate.

    Returns:
        The validated name.

    Raises:
        ValidationError: If the directory is invalid.
    """

    if not directory:
        raise ValidationError(msg='You must specify a directory.')

    # Record whether it's already too long; might use this later. (Note that
    # this function is not structured optimally for speed. It's meant to give
    # the most helpful error message).
    base_is_too_long: bool = len(directory) > DIRECTORY_MAX_LENGTH

    # If it's not absolute, resolve it from the default timelapse root dir
    directory = Path(directory)
    if directory.is_absolute():
        note = ''
    else:
        note = (" (Note: relative paths are resolved from the default "
                "timelapse root directory: "
                f"`{settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY}`).")
        directory = settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY / directory

    # Can't be a file
    if directory.is_file():
        ext = utils.trunc(directory.suffix, 50, escape_markdown=True)
        name = utils.trunc(
            directory.name, 100, ellipsis_str=ext, escape_markdown=True
        )
        raise ValidationError(
            msg=f"**{name}** is a file, not a directory." + note
        )

    # Can't have stuff in it
    if directory.is_dir() and any(directory.iterdir()):
        # Get a string pointing to the last bit of the path
        root: Path = Path(directory.root)
        if directory == root:
            name, reverse = str(directory), False
        elif directory.parent == root or directory.parent.parent == root:
            name, reverse = str(directory), True
        else:
            name = os.path.join('…', directory.parent.name, directory.name)
            reverse = True

        name = utils.trunc(name, 100, escape_markdown=True, reverse=reverse)
        n = len(list(directory.iterdir()))

        raise ValidationError(
            msg=f"The timelapse directory must be empty, but **{name}** "
                f"contains {n} item{'' if n == 1 else 's'}." + note
        )

    # Can't be too long
    if len(str(directory)) > DIRECTORY_MAX_LENGTH:
        raise ValidationError(
            msg=f"The directory path must not exceed {DIRECTORY_MAX_LENGTH} "
                "characters." + ('' if base_is_too_long else note)
        )

    return directory


def determine_default_directory(name: str) -> Optional[Path]:
    """
    Given a timelapse name, pick a default directory in which to store its
    pictures. The directory is not created, but it may already exist. However,
    if it does exist, it's guaranteed to be empty.

    The path must fit within the DIRECTORY_MAX_LENGTH. If no directory can be
    found that meets this condition, the default directory will be None.

    Args:
        name: The name of the timelapse.

    Returns:
        The path to the automatically chosen directory. Or, if it's impossible
        to pick a directory without exceeding the maximum length, None.
    """

    root: Path = settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY

    # If the timelapse root doesn't exist, it's guaranteed that 'root / name'
    # doesn't have anything in it
    if not root.exists():
        d = root / name
        return d if len(str(d)) <= DIRECTORY_MAX_LENGTH else None

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
    d = utils.get_unique_path(
        root / name,
        lambda p: not p.exists() or  # Either doesn't exist, or
                  (p.is_dir() and not any(p.iterdir()))  # empty directory
    )

    return d if len(str(d)) <= DIRECTORY_MAX_LENGTH else None


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
            view = TimelapseInvalidName(interaction, e)
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
        self.name = error.name

        # The number of consecutive times the user has given an invalid name
        # with the same problem
        self.attempt: int = 1

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

            embed: discord.Embed = self.error.build_embed()
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
                embed.color = settings.DISABLED_ERROR_EMBED_COLOR  # noqa

                # Stop listening to interactions on this view
                self.stop()
        else:
            # Otherwise, this is a new error
            self.attempt = 1
            self.error = error
            embed = self.error.build_embed()

        await self.interaction.edit_original_response(
            embed=embed, view=self
        )

    @ui.button(label='Change Name', style=ButtonStyle.primary,
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

    @ui.button(label='Cancel', style=ButtonStyle.secondary,
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


class NewNameModal(ui.Modal, title='Timelapse Name'):
    # The timelapse name
    name = ui.TextInput(
        label='Name',
        required=True,
        min_length=1,
        max_length=NAME_MAX_LENGTH
    )

    def __init__(self,
                 parent_view: TimelapseInvalidName | TimelapseCreator) -> None:
        """
        Initialize this modal, which prompts the user to enter a new name for
        a timelapse.

        The parent view is either an invalid name view, meaning the user
        tried to create a timelapse with an invalid name, or it's an existing
        creator, meaning that the user is changing the name they entered.

        Args:
            parent_view: The view that spawned this modal.
        """

        super().__init__()
        self.parent_view = parent_view

        # Remember the type of parent view
        self.was_invalid: bool = isinstance(self.parent_view,
                                            TimelapseInvalidName)

        # If the user previously gave an invalid name, add a little reminder
        if self.was_invalid:
            self.name.placeholder = 'Enter a new, valid name'
        else:
            self.name.placeholder = 'Enter a new name'

        _log.debug(f'Created a new name modal on a '
                   f'{parent_view.__class__.__name__}')

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the new name, validating it and proceeding to the next stage
        if the name is good.

        Args:
            interaction: The interaction.
        """

        # Defer a response, as we'll be editing an existing message rather than
        # sending a new one
        await interaction.response.defer(ephemeral=True)

        # Validate the user's timelapse name
        try:
            validated_name = await validate_name(self.name.value)
        except InvalidTimelapseNameError as error:
            # Handle an(other) invalid error
            if self.was_invalid:
                await self.parent_view.new_invalid_name(error)
            else:
                embed = error.build_embed()
                embed.add_field(
                    name='Name Not Changed',
                    value=f'The name is still **"{self.parent_view.name}"**. '
                          'Enter a valid name to change it.'
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ===== The name is valid =====

        # If there's an invalid name view, disable it, and replace it with a new
        # timelapse creator view
        if self.was_invalid:
            self.parent_view.stop()
            await TimelapseCreator.create_new(
                self.parent_view.interaction,
                validated_name,
                do_validate=False
            )
        else:
            # Otherwise, just change the name
            await self.parent_view.change_name(validated_name)


class ChangeDirectoryModal(ui.Modal, title='Timelapse Directory'):
    directory = ui.TextInput(
        label='Directory',
        required=True,
        min_length=1,
        max_length=DIRECTORY_MAX_LENGTH
    )

    def __init__(self,
                 parent: TimelapseCreator,
                 directory: Optional[Path]) -> None:
        """
        Initialize this modal, which prompts the user to enter a new directory
        for the timelapse files.

        Args:
            parent: The timelapse creator view that spawned this modal.
            directory: The current directory, used as a pre-filled value.
        """

        super().__init__()
        self.parent_view = parent
        if directory is not None:
            self.directory.default = str(directory)

        _log.debug(f'Created a change directory modal on timelapse '
                   f"'{parent.name}'")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the new directory request, validating it and then changing it if
        it's valid.

        Args:
            interaction: The interaction.
        """

        # Defer a response, as we'll be editing an existing message rather than
        # sending a new one
        await interaction.response.defer(ephemeral=True)

        # Validate the directory
        try:
            await self.parent_view.set_directory(
                validate_directory(self.directory.value)
            )
        except ValidationError as error:
            await interaction.followup.send(
                embed=utils.contrived_error_embed(
                    title='Error: Invalid Directory', text=error.msg
                ),
                ephemeral=True
            )


class TimelapseCreator(BaseView):
    def __init__(self,
                 interaction: discord.Interaction,
                 name: str,
                 camera: Optional[GCamera],
                 directory: Optional[Path]):
        """
        Create a new view for helping the user make a timelapse.

        Args:
            interaction: The interaction that led to this view. This is used to
            get the original message to edit it as changes are made.
            name: The already-validated name of the timelapse.
            camera: The camera to use for the timelapse.
            directory: The directory for storing timelapse photos.
        """

        super().__init__(interaction)
        self._name = name
        self.user: discord.User | discord.Member = interaction.user
        self._camera: Optional[GCamera] = camera
        self._directory: Optional[Path] = directory

        # If the camera is already set, change button label
        if self._camera is not None:
            utils.get_button(self, 'Set Camera').label = 'Change Camera'

        # Retrieve the directory button, storing a reference to it. Change it
        # to 'Set Directory' if the directory is currently unset
        self.button_directory = utils.get_button(self, 'Change Directory')
        if directory is None:
            self.button_directory.label = 'Set Directory'

        # Default interval
        self._interval: Optional[timedelta] = None

        # Start runtime conditions
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._total_frames: Optional[int] = None

        # A timelapse schedule
        self._schedule: Optional[Schedule] = None

        # Create the interval button
        self.button_interval = self.create_button(
            label='Set Interval',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_TIME_INTERVAL,
            callback=self.select_button_interval,
            auto_defer=False,
            row=2
        )

        # Get runtime button
        self.button_runtime = self.create_button(
            label='Set Runtime' if self._start_time is None and
                                   self._end_time is None
            else 'Change the Runtime',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            callback=self.select_button_runtime,
            auto_defer=False,
            row=3,
        )

        # Create the schedule button
        self.button_schedule = self.create_button(
            label='Create a Schedule' if self._schedule is None
            else 'Edit the Schedule',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CREATE_SCHEDULE,
            callback=lambda _: self.select_button_schedule(),
            row=3
        )

        _log.info(f"Starting a new timelapse creator called {name}")

    @classmethod
    async def create_new(cls,
                         interaction: discord.Interaction,
                         name: str,
                         do_validate: bool = True) -> None:
        """
        Create a new timelapse creator view. This gets some default values and
        builds the initial timelapse creation panel.

        Args:
            interaction: The interaction requesting to make a timelapse.
            name: The name of the timelapse.
            do_validate: Whether to validate the timelapse name before
            using it. Only disable if already validated. Defaults to True.

        Raises:
            InvalidTimelapseNameError: If the given name is not valid.
        """

        # Validate the input name if enabled
        if do_validate:
            name = await validate_name(name)

        # Determine the default directory
        directory: Optional[Path] = determine_default_directory(name)

        # Get a default camera
        try:
            camera = await gmanager.get_default_camera()
        except NoCameraFound:
            camera = None  # Worry about this later

        # Build and send the timelapse creator view
        await cls(interaction, name, camera, directory).refresh_display()

    async def refresh_display(self) -> None:
        """
        Edit the original interaction response message, updating it with this
        view and embed.
        """

        await self.interaction.edit_original_response(
            content='', embed=self.build_embed(), view=self
        )

    def build_embed(self) -> discord.Embed:
        """
        Construct an embed with the info about this timelapse. This embed is
        associated with the buttons in this view.

        Returns:
            The embed.
        """

        # Escape markdown in the name
        safe_name = discord_utils.escape_markdown(self._name)

        # Get the camera name
        if self._camera is None:
            camera = '*undefined*'
        else:
            camera = utils.trunc(self._camera.name, 75, escape_markdown=True)

        # Create the base embed
        embed = utils.default_embed(
            title='Create a Timelapse',
            description=f"**Name:** {safe_name}\n"
                        f"**Creator:** {self.user.mention}\n"
                        f"**Camera:** {camera}"
        )

        # Add directory info
        if self._directory is None:
            # The directory can never be removed. If missing, it was never
            # chosen due to being too long
            directory = '*[Undefined: default path was too long]*'
        else:
            directory = f'`{self._directory}`'

        embed.add_field(name='Directory', value=directory, inline=False)

        # Add interval
        if self._interval is None:
            interval = '*Undefined*'
        else:
            interval = utils.format_duration(self._interval,
                                             always_decimal=True)

        embed.add_field(name='Capture Interval', value=interval, inline=False)

        # Add runtime info
        runtime_text = timelapse_utils.generate_embed_runtime_text(
            self._start_time,
            self._end_time,
            self._total_frames
        )
        embed.add_field(name='Runtime', value=runtime_text, inline=False)

        # Add schedule
        if self._schedule is not None:
            embed.add_field(
                name='Schedule',
                value=self._schedule.get_summary_str(),
                inline=False
            )

        # Return finished embed
        return embed

    async def set_directory(self, directory: Path) -> None:
        """
        Change the directory. If the directory is currently unset, this has the
        side effect of renaming the "Set Directory" button back to "Change
        Directory".

        If the directory changes, this also refreshes the display.

        Args:
            directory: The new directory.
        """

        if self._directory is None:
            self.button_directory.label = 'Change Directory'
            self._directory = directory
        elif self._directory != directory:
            self._directory = directory
            await self.refresh_display()

    async def set_interval(self, interval: timedelta) -> None:
        """
        Change the interval. If the interval is currently unset, this has the
        side effect of renaming the "Set Interval" to "Change Interval".

        If the interval changes, this also refreshes the display.

        Args:
            interval: The new interval.
        """

        if self._interval is None:
            utils.get_button(self, 'Set Interval').label = \
                'Change Interval'
        elif self._interval == interval:
            return

        self._interval = interval
        await self.refresh_display()

    async def set_runtime(self,
                          start_time: Optional[datetime],
                          end_time: Optional[datetime],
                          total_frames: Optional[int]) -> None:
        """
        Change the start/end time and/or the total frames. This has the side
        effect of possibly changing the label and emoji on the associated
        button.

        Args:
            start_time: The new start time.
            end_time: The new end time.
            total_frames:  The new total frame count.
        """

        # Change the button label, if applicable
        if start_time is not None or end_time is not None or \
                total_frames is not None:
            self.button_runtime.label = 'Change Runtime'
            self.button_runtime.emoji = settings.EMOJI_CHANGE_TIME
        elif start_time is None and end_time is None and total_frames is None:
            self.button_runtime.label = 'Set Runtime'
            self.button_runtime.emoji = settings.EMOJI_SET_RUNTIME

        # Update and display the configuration if it changed
        if total_frames != self._total_frames or \
                start_time != self._start_time or \
                end_time != self._end_time:
            self._start_time = start_time
            self._end_time = end_time
            self._total_frames = total_frames
            await self.refresh_display()

    @ui.button(label='Create', style=ButtonStyle.success,
               emoji=settings.EMOJI_DONE_CHECK, row=0)
    async def select_button_create(self,
                                   interaction: discord.Interaction,
                                   _: ui.Button) -> None:
        """
        Create this timelapse, and add it to the database. Switch to a new
        display for controlling the created timelapse.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_message(content='Create!',
                                                ephemeral=True)
        await self.refresh_display()
        self.stop()

    @ui.button(label='Info', style=ButtonStyle.primary,
               emoji=settings.EMOJI_INFO, row=0)
    async def select_button_info(self,
                                 interaction: discord.Interaction,
                                 _: ui.Button) -> None:
        """
        Show the user information about timelapses, as if they had run the
        `/timelapse info` command.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_message(
            content='This is some info on timelapses!',
            ephemeral=True
        )

    @ui.button(label='Cancel', style=ButtonStyle.danger,
               emoji=settings.EMOJI_CANCEL, row=0)
    async def select_button_cancel(self,
                                   interaction: discord.Interaction,
                                   _: ui.Button) -> None:
        """
        Cancel this timelapse creator.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.defer()
        await self.interaction.delete_original_response()
        self.stop()

    @ui.button(label='Change Name', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_EDIT, row=1)
    async def select_button_name(self,
                                 interaction: discord.Interaction,
                                 _: ui.Button) -> None:
        """
        Open a modal prompting the user to enter a new timelapse name.

        Args:
            interaction: The interaction.
            _: This button.
        """

        modal = NewNameModal(self)
        await interaction.response.send_modal(modal)

    @ui.button(label='Change Directory', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_DIRECTORY, row=1)
    async def select_button_directory(self,
                                      interaction: discord.Interaction,
                                      _: ui.Button) -> None:
        """
        Open a modal prompting to the user to change the timelapse directory.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_modal(ChangeDirectoryModal(
            self, self._directory
        ))

    @ui.button(label='Set Camera', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_CAMERA, row=2)
    async def select_button__camera(self,
                                    interaction: discord.Interaction,
                                    button: ui.Button) -> None:
        """
        Replace the view with one prompting the user to select a camera from
        a dropdown.

        Args:
            interaction: The interaction.
            button: This button.
        """

        await interaction.response.defer()

        # Define the callback that actually changes updates the camera
        async def callback(camera: GCamera):
            self._camera = camera
            button.label = 'Change Camera'
            await self.refresh_display()

        # Send a new camera selector view
        try:
            await CameraSelector.create_selector(
                callback=callback,
                on_cancel=self.refresh_display,
                message=f"Choose a{'' if self._camera is None else ' new'} "
                        f"timelapse camera from the list below:",
                interaction=interaction,
                edit=True,
                default_camera=self._camera,
                cancel_danger=False
            )
        except NoCameraFound:
            _log.warning(f"Failed to get a camera for timelapse '{self._name}'")
            embed = utils.contrived_error_embed(
                'No cameras detected. Please connected a camera to the '
                'system, and try again.',
                'Missing Camera'
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def select_button_interval(self,
                                     interaction: discord.Interaction) -> None:
        """
        Open a modal prompting to the user to change the interval between
        frames in the timelapses.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Send the modal
        await interaction.response.send_modal(ChangeIntervalModal(
            self.set_interval, self._interval
        ))

    async def select_button_runtime(self,
                                    interaction: discord.Interaction) -> None:
        """
        Open a modal prompting to the user to set/change the runtime
        configuration.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Send the modal
        await interaction.response.send_modal(ChangeRuntimeModal(
            self._start_time,
            self._end_time,
            self._total_frames,
            self.set_runtime
        ))

    async def select_button_schedule(self) -> None:
        """
        Add a timelapse schedule for more complex and precise control of when
        it takes photos.
        """

        # Create a schedule builder
        await ScheduleBuilder(
            self.interaction,
            self._start_time,
            self._end_time,
            self._total_frames,
            self._schedule,
            self.set_schedule,  # primary callback
            self.refresh_display  # on cancel, just refresh the display
        ).refresh_display()

    @property
    def name(self) -> str:
        """
        Get the timelapse name.

        Returns:
            The name.
        """

        return self._name

    async def change_name(self, name: str) -> None:
        """
        Change the timelapse name. If the given name is actually new, the
        display is automatically refreshed.

        If the previous directory was derived from the previous name, this has
        the side effect of changing the directory too (if possible).

        Args:
            name: The new name.
        """

        # Do nothing if the name didn't change
        if self._name == name:
            return

        _log.debug(f"Changing timelapse name from '{self._name}' to '{name}'")

        # If the previous directory, is unset or uses the previous name, try to
        # change it based on the new name
        if self._directory is None or \
                self._name.lower() in self._directory.name.lower():
            new_dir = determine_default_directory(name)
            if new_dir is not None:
                _log.debug(f"Updated directory from '{self._directory}' "
                           f"to '{new_dir}'")
                self._directory = new_dir

        # Change the name
        self._name = name

        # Refresh the display
        await self.refresh_display()

    @property
    def schedule(self) -> Optional[Schedule]:
        """
        Get the timelapse schedule, if set.

        Returns:
            The schedule.
        """

        return self._schedule

    async def set_schedule(self,
                           start_time: Optional[datetime],
                           end_time: Optional[datetime],
                           total_frames: Optional[int],
                           new_schedule: Optional[Schedule]) -> None:
        """
        Set the runtime and timelapse schedule. It is assumed that at least
        something is actually changed by calling this (as opposed to, say
        change_name(), which could receive the existing name).

        Note that it is possible for the schedule to be None, meaning that it's
        either removed or the other parameters have been changed instead.

        After updating the schedule, this refreshes the display.

        Args:
            start_time: The (possibly new) runtime start.
            end_time: The (possibly new) runtime end.
            total_frames: The (possibly new) total frame threshold.
            new_schedule: The (possibly new) timelapse schedule.
        """

        await self.set_runtime(start_time, end_time, total_frames)
        self._schedule = new_schedule

        # Update the button text
        if new_schedule is None:
            self.button_schedule.label = 'Create a Schedule'
        else:
            self.button_schedule.label = 'Edit the Schedule'

        await self.refresh_display()


async def setup(bot: GphotoBot):
    await bot.add_cog(Timelapse(bot))
    _log.info('Loaded Timelapse cog')
