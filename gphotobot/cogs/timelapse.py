from datetime import datetime, timedelta
import dateutil.parser
import logging
from pathlib import Path
import re
from typing import Literal, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands
from sqlalchemy import exc
from sqlalchemy.ext.asyncio import AsyncSession

from gphotobot.bot import GphotoBot
from gphotobot.conf import settings
from gphotobot.sql import async_session_maker
from gphotobot.sql.models import timelapses
from gphotobot.utils import const, utils
from gphotobot.utils.validation_error import ValidationError

_log = logging.getLogger(__name__)


class Timelapse(commands.Cog):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @staticmethod
    def get_timelapse_info(timelapse: timelapses.Timelapses) -> str:
        """
        Get a formatted string with information about a timelapse. This is
        designed for Discord.

        Args:
            timelapse (timelapses.Timelapses): The timelapse.

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

    @app_commands.command(description='Prepare a new timelapse')
    async def create(self,
                     interaction: discord.Interaction[commands.Bot]) -> None:
        """
        Create a new timelapse.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.
        """

        # TODO change this to keep track of the default name for the day so I
        #  don't have to query the database, which could time out

        async with async_session_maker() as session:  # read-only session
            # Generate default info
            name: str = await timelapses.generate_default_name(session)
            directory: Path = settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY / name

            # Create a modal
            creator = TimelapseCreator()
            creator.name.default = name
            creator.directory.default = str(directory)

            # Send the modal to prompt the user for more info
            await interaction.response.send_modal(creator)

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
                active_timelapses: list[timelapses.Timelapses] = \
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


class TimelapseCreator(ui.Modal, title='Create a Timelapse'):
    # noinspection SpellCheckingInspection
    TIME_PARSE_REGEX = (r'^(?:(\d*(?:\.\d+)?) *y(?:ears?|rs?)?)? *'
                        r'(?:(\d*(?:\.\d+)?) *d(?:ays?|s?)?)? *'
                        r'(?:(\d*(?:\.\d+)?) *h(?:ours?|rs?)?)? *'
                        r'(?:(\d*(?:\.\d+)?) *m(?:inutes?|ins?)?)? *'
                        r'(?:(\d*(?:\.\d+)?) *s(?:econds?|ecs?)?)?$')

    # Instructions for error messages
    START_TIME_INSTRUCTIONS = (
        'Enter the time to start the timelapse, or leave it blank to start it '
        'manually. Use "now" or "begin" to start immediately. Or enter a '
        f'date/time, like "5:00 a.m." or "{str(datetime.today().date())} '
        f'{(datetime.now() + timedelta(hours=1, minutes=20)).strftime(
            "%I:%M:%S %p")}".'
    )
    END_CONDITION_INSTRUCTIONS = (
        'Enter the condition to end the timelapse: either the total number of '
        'frames to capture, or use a specific date/time like "8:30 a.m." or '
        f'"{str(datetime.today().date())} '
        f'{(datetime.now() + timedelta(hours=2, minutes=15)).strftime(
            "%I:%M:%S %p")}".'
    )
    INTERVAL_INSTRUCTIONS = ('Enter a duration of time, like "2 minutes", '
                             '"12s", or "00:10:00".')

    # These strings are all equivalent to "now" for the start time
    START_TIME_NOW_EQUIVALENTS = [
        'now', 'start', 'right now', 'begin', 'begin now'
    ]

    # The timelapse name
    name = ui.TextInput(
        label='Name',
        required=True,
        placeholder='Enter a name to access this timelapse later',
        max_length=timelapses.NAME_MAX_LENGTH
    )

    # The directory for storing photos
    directory = ui.TextInput(
        label='Folder for photos',
        required=True,
        placeholder='Choose a directory to store the photos',
        max_length=timelapses.DIRECTORY_MAX_LENGTH
    )

    # The time to start capturing
    start_time = ui.TextInput(
        label='Start time',
        placeholder="Enter start time, 'now', or omit to start manually",
        required=False,
        max_length=100
    )

    # The time to wait between captures
    interval = ui.TextInput(
        label='Interval between captures',
        placeholder="Enter a time: (ex. '5s', '1h 5m', '10d 4h 3m 2s')",
        required=True,
        max_length=100
    )

    # The time to end or the number of frames to end on
    end_condition = ui.TextInput(
        label='End at',
        required=True,
        placeholder='Enter end time or number of frames to capture',
        max_length=100
    )

    async def validate_input(self, session: AsyncSession) -> \
            tuple[str,
            str,
            Optional[datetime | Literal['now']],
            Optional[datetime],
            Optional[int],
            float]:
        """
        Validate all the arguments in the modal.

        Args:
            session (AsyncSession): The database session.

        Returns:
            A tuple with each validated argument: the name, directory, start
            time, end time, total frames, and interval.

        Raises:
            ValidationError: If anything fails validation, this is raised, and
            the message should be sent to the user.
        """

        # Validate the name
        name = self.name.value.strip()
        if await timelapses.is_name_active(session, name):
            raise ValidationError(
                'name',
                f'That name is already in use by an active '
                'timelapse. You can see a list of timelapses with '
                '`/timelapse list`.'
            )
        elif len(name) > timelapses.NAME_MAX_LENGTH:
            raise ValidationError(
                'name',
                "The name can't be longer than "
                f"{timelapses.NAME_MAX_LENGTH} characters."
            )

        # Validate the directory
        # TODO add more validation here to check whether it already contains
        #  files and such
        directory = self.directory.value
        if len(directory) > timelapses.DIRECTORY_MAX_LENGTH:
            raise ValidationError(
                'directory',
                f"The directory path can't be longer than"
                f" {timelapses.NAME_MAX_LENGTH} characters."
            )

        # Validate the start time
        try:
            start_time = self.parse_start_time()
        except ValueError:
            raise ValidationError(
                'start_time',
                'Invalid start time. ' + self.START_TIME_INSTRUCTIONS
            )
        except AssertionError:
            raise ValidationError(
                'start_time',
                "Invalid start time: it can't be in the past. " +
                self.START_TIME_INSTRUCTIONS
            )

        # Validate the end condition
        try:
            end_time, total_frames = self.parse_end_condition(start_time)
        except ValueError:
            raise ValidationError(
                'end_condition',
                'Invalid end condition. ' + self.END_CONDITION_INSTRUCTIONS
            )
        except AssertionError:
            raise ValidationError(
                'end_condition',
                "Invalid end time: it can't be in the past or after "
                "the start time."
            )

        # Validate the interval
        try:
            interval = self.parse_interval()
        except ValueError:
            raise ValidationError(
                'interval',
                'Invalid interval. ' + self.INTERVAL_INSTRUCTIONS
            )
        except AssertionError:
            raise ValidationError(
                'interval',
                'Missing interval. ' + self.INTERVAL_INSTRUCTIONS
            )

        return name, directory, start_time, end_time, total_frames, interval

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the user's input to the modal.

        Args:
            interaction: The interaction.
        """

        await interaction.response.defer(thinking=True)

        # Writable session
        async with async_session_maker() as session, session.begin():
            # Validate user input
            try:
                name, directory, start_time, end_time, \
                    total_frames, interval = await self.validate_input(session)
            except ValidationError as e:
                await self.invalid_input(interaction, e.message, e.attribute)
                return

            # Only add start time to the database if there's an exact time
            start = start_time if isinstance(start_time, datetime) else None

            timelapse = timelapses.Timelapses(
                name=self.name.value,
                user_id=interaction.user.id,
                directory=directory,
                start_time=start,
                end_time=end_time,
                interval=interval,
                total_frames=total_frames
            )

            session.add(timelapse)

        await interaction.followup.send('Thanks, added your timelapse!')

    async def invalid_input(self,
                            interaction: discord.Interaction,
                            message: str,
                            parameter: str) -> None:
        """
        Respond to the interaction with an error message indicating that the
        user's input was invalid.

        Args:
            interaction (discord.Interaction): The interaction.
            message (str): A descriptive message to send the user.
            parameter (str): The name of the parameter that was invalid.
        """

        embed = utils.contrived_error_embed(
            title='Invalid Input',
            text=message,
        )

        error_view = TimelapseCreatorError(self, parameter)
        message = await interaction.followup.send(embed=embed, view=error_view)
        _log.info(f'I want to delete this message: type = {type(message)}\n'
                  "For now I'm just deleting the followup...")
        await interaction.followup.delete()

    def parse_start_time(self) -> Optional[datetime | Literal['now']]:
        """
        Attempt the parse the start time, if a time was given. If the start
        time is given as "now," wait to resolve that to a time until the
        timelapse actually begins.

        Returns:
            Optional[datetime | Literal['now']]: The start time, if specified,
            or the string 'now' if that was given.

        Raises:
            ValueError: If the time is given but cannot be parsed.
            AssertionError: If the time can be parsed, but it's in the past.
        """

        val = self.start_time.value

        if not val:
            return None
        elif val.strip().lower() in self.START_TIME_NOW_EQUIVALENTS:
            return 'now'

        # Try parsing it as a datetime
        try:
            dt = dateutil.parser.parse(val)
            # If the time is in the past, reject it
            assert dt >= datetime.now()
            return dt
        except dateutil.parser.ParserError | OverflowError:
            raise ValueError()

    def parse_end_condition(self,
                            start: Optional[datetime | Literal['now']]) -> \
            tuple[Optional[datetime], Optional[int]]:
        """
        Attempt to parse whatever value the user put for the end condition.
        It could be an end time or a number of frames.

        Args:
            start (Optional[datetime | Literal['now']]): The start time. If
            given, the end time must be after this.

        Returns:
            tuple[Optional[datetime], Optional[int]]: The end time and the
            number of frames. Exactly one of these will be None.

        Raises:
            ValueError: If the end condition cannot be parsed.
            AssertionError: If the end condition is an invalid datetime (either
            because it's in the past or the user didn't specify a time).
        """

        val = self.end_condition.value

        # Frames will either be a single number or a two-word string like
        # "50 frames"
        split = val.split(' ')
        if len(split) <= 2 and split[0].isdigit():
            return None, int(split[0])

        # Try parsing it as a datetime
        try:
            dt = dateutil.parser.parse(val)
            # If the time is in the past, reject it
            assert dt >= datetime.now()

            # If a start time is given, the end time must come after
            if isinstance(start, datetime):
                assert dt > start

            return dt, None
        except dateutil.parser.ParserError | OverflowError:
            raise ValueError()

    def parse_interval(self) -> float:
        """
        Attempt to parse whatever value the user put for the interval.

        Note: This interprets strings like 4:02 as 4 hours and 2 minutes. That
        should probably be fixed to read as 4 minutes and 2 seconds, which will
        definitely be more common in this case.

        Returns:
            int: The interval, in seconds.

        Raises:
            AssertionError: If no interval was given at all.
            ValueError: If the interval cannot be parsed.
        """

        val = self.interval.value
        assert isinstance(val, str) and val.strip()

        # Try matching against the fancy RegEx for strings like "4d 3h 2m 1.2s"
        # and "3 hours 8 min 5seconds
        match = re.match(self.TIME_PARSE_REGEX, val,
                         flags=re.RegexFlag.IGNORECASE)

        # Compute total seconds
        if match:
            interval = 0
            for index, factor in enumerate([1, 60, 3600, 86400, 31536000]):
                val = match.group(index + 1)
                interval += factor * float(val if val else 0)
            return interval

        # Try using dateutil to parse a time as an interval
        try:
            dt = dateutil.parser.parse(val)
            # If the user specified a date, they're doing this wrong
            if dt.date() != datetime.today().date():
                raise ValueError()

            # Interpret the time as a duration of seconds, and make sure it's
            # not 0
            time = dt.time()
            interval = (time.hour * 3600 + time.minute * 60 +
                        time.second + time.microsecond / 1000)
            assert interval > 0
            return interval
        except dateutil.parser.ParserError | OverflowError:
            raise ValueError()


class TimelapseCreatorError(ui.View):
    def __init__(self,
                 creator: TimelapseCreator,
                 errant_parameter: str):
        """
        Initialize a view for an error creating a timelapse.

        Args:
            creator: The creator modal.
            errant_parameter: The name of the parameter that had an issue.
        """

        super().__init__()
        self.creator = creator
        self.errant_parameter = errant_parameter

    @ui.button(label='Retry', style=discord.ButtonStyle.secondary)
    async def retry(self,
                    interaction: discord.Interaction,
                    _: ui.Button) -> None:
        """
        When the user clicks "retry", send them the original modal.

        Args:
            interaction: The interaction.
            _: This button.
        """

        # Fill in the values where the user left off, except for whichever
        # value they messed up on
        for param_name in ['name', 'directory', 'start_time',
                           'interval', 'end_condition']:
            if param_name != self.errant_parameter:
                param = getattr(self.creator, param_name)
                param.default = param.value

        # Send the modal again
        await interaction.response.send_modal(self.creator)


async def setup(bot: GphotoBot):
    await bot.add_cog(Timelapse(bot))
    _log.info('Loaded Timelapse cog')
