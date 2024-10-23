from datetime import date, datetime, timedelta
import logging
from typing import Awaitable, Callable, Literal, Optional

import dateutil.parser
import discord
from discord import ui, utils as discord_utils

from gphotobot import utils

_log = logging.getLogger(__name__)


class ChangeRuntimeModal(ui.Modal, title='Timelapse Runtime Config'):
    # TODO Implement proper timezone support for timelapse scheduling

    # The default format for printing raw datetimes (without using markdown)
    DATE_TIME_FORMAT = '%Y-%m-%d %I:%M:%S %p'

    # The time it starts taking photos
    start_time = ui.TextInput(
        label='Start Time',
        placeholder='Date/Time to start taking photos',
        required=False,
        max_length=50
    )

    # End condition 1: a time to stop taking photos
    end_time = ui.TextInput(
        label='End Time',
        placeholder='Set end date/time (or use total frame count below)',
        required=False,
        max_length=50
    )

    # End condition 2: a total number of frames to capture before stopping
    total_frames = ui.TextInput(
        label='Total Frames',
        placeholder='Set total frames to capture '
                    '(or use end time above)',
        required=False,
        max_length=10
    )

    def __init__(self,
                 start_time: Optional[datetime],
                 end_time: Optional[datetime],
                 total_frames: Optional[int],
                 callback: Callable[[
                     Optional[datetime],
                     Optional[datetime],
                     Optional[int]
                 ], Awaitable]) -> None:
        """
        Initialize this modal, which prompts the user to update the runtime
        configuration.

        Args:
            start_time: The current start time, used as a pre-filled default.
            end_time: The current end time, used as a pre-filled default.
            total_frames: The current total frames, used as a pre-filled
            default.
            callback: The async function to call with the user input to this
            modal.
        """

        super().__init__()
        self.callback: Callable[[
            Optional[datetime],
            Optional[datetime],
            Optional[int]
        ], Awaitable] = callback

        # Set defaults, if given
        if start_time is not None:
            self.start_time.default = start_time.strftime(self.DATE_TIME_FORMAT)
        if end_time is not None:
            self.end_time.default = end_time.strftime(self.DATE_TIME_FORMAT)
        if total_frames is not None:
            self.total_frames.default = str(total_frames)

        _log.debug(f'Created a change runtime modal for a timelapse')

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the new start/end time request, parsing and validating it and
        then running the callback function.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Defer a response, as we'll be editing an existing message
        await interaction.response.defer()

        # Parse the start/end times
        try:
            start = self.parse_time(self.start_time.value, 'Start')
            end = self.parse_time(self.end_time.value, 'End', start)
            total_frames = self.parse_total_frames(self.total_frames.value)
        except utils.ValidationError as e:
            # Send the error message
            embed = utils.contrived_error_embed(
                title=f'Error: Invalid {e.attr}',
                text=e.msg
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Set the values
        await self.callback(start, end, total_frames)

    def parse_time(self,
                   time: Optional[str],
                   boundary: Literal['Start', 'End'],
                   start_time: Optional[datetime] = None) -> Optional[datetime]:
        """
        Parse the given time.

        Args:
            time: The time to parse.
            boundary: Whether this is the start or end time.
            start_time: If this is the end time, pass the parsed start time to
            confirm that the end time is after it. Defaults to None.

        Returns:
            The parsed time, or None if the input time is None or blank.

        Raises:
            ValidationError: If the time is invalid. This explains what's wrong
            with it with a user-friendly message.
        """

        # Exit immediately if no time was given
        if time is None or not time.strip():
            return None

        # Attempt to parse the time
        try:
            time = dateutil.parser.parse(time)
        except ValueError:
            clean: str = discord_utils.escape_markdown(time)
            some_time: str = ((datetime.today() + timedelta(days=1, minutes=85))
                              .strftime('%Y-%m-%d %I:%M:%S %p'))
            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time **\"{clean}\"** is invalid. "
                    "Enter a date or time in a standard format (e.g. "
                    f"'10:04 p.m.' or '{some_time}')."
            )
        except OverflowError:
            clean: str = discord_utils.escape_markdown(time)
            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time **\"{clean}\"** couldn't "
                    "be understood properly. It may have too large of numbers "
                    "or too many decimals. Please try using a standard time"
                    "format."
            )

        # Make sure the time is in the future
        if time <= datetime.now():
            if time.date() == datetime.now().date():
                clean: str = time.strftime('%I:%M:%S %p')
            else:
                clean: str = time.strftime(self.DATE_TIME_FORMAT)

            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time is invalid. Both the start "
                    f"and end times must be in the future, but **\"{clean}\"** "
                    "already passed."
            )

        # Make sure the end time is after the start time
        if time is not None and start_time is not None and time <= start_time:
            today: date = date.today()
            if time.date() == today and start_time.date() == today:
                clean: str = time.strftime('%I:%M:%S %p')
                start: str = start_time.strftime('%I:%M:%S %p')
            else:
                clean: str = time.strftime(self.DATE_TIME_FORMAT)
                start: str = start_time.strftime(self.DATE_TIME_FORMAT)

            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The end time **\"{clean}\"** is invalid. It must come "
                    f"after the start time **\"{start}\"**."
            )

        # The datetime passed validation
        return time

    @staticmethod
    def parse_total_frames(frames: Optional[str]) -> Optional[int]:
        """
        Parse the total number of frames.

        Returns:
            The parsed frame count, or None if it wasn't specified.

        Raises:
            ValidationError: If the input is invalid. This explains what's wrong
            with it with a user-friendly message.
        """

        if frames is None or not frames.strip():
            return None

        try:
            frames = float(frames)
            int_frames = int(frames)
            assert int_frames == frames
        except ValueError:
            clean: str = discord_utils.escape_markdown(frames)
            raise utils.ValidationError(
                attr='Total Frame Count',
                msg=f"Invalid total frames **\"{clean}\"**. The total "
                    "frame count is the number of pictures to take "
                    "before stopping the timelapse. It must be a "
                    "positive integer (≥1 with no commas or decimals)."
            )
        except AssertionError:
            clean: str = discord_utils.escape_markdown(frames)
            raise utils.ValidationError(
                attr='Total Frame Count',
                msg=f"Invalid total frames **\"{clean}\"**. The total "
                    "frame count must be a whole number of frames. It can't "
                    "have any decimals."
            )

        # Make sure it's positive
        if int_frames <= 0:
            raise utils.ValidationError(
                attr='Total Frame Count',
                msg=f"Invalid total frames **\"{int_frames}\"**. The total "
                    "frame count must be a positive number."
            )

        return int_frames
