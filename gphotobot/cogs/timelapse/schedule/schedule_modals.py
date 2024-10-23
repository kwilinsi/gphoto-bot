from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
import logging
from typing import Literal, Optional

import dateutil.parser
from discord import Interaction, ui, TextStyle, utils as discord_utils

from gphotobot import utils
from .dates import Dates

_log = logging.getLogger(__name__)


class ScheduleRuntimeModal(ui.Modal, title='Schedule Runtime'):
    # This is very similar to runtime_modal.ChangeRuntimeModal, except that it
    # doesn't include a field for the total frames

    # The time it starts taking photos
    start_time = ui.TextInput(
        label='Start Time',
        placeholder='Time to start taking photos',
        required=True,
        max_length=20
    )

    # End condition 1: a time to stop taking photos
    end_time = ui.TextInput(
        label='End Time',
        placeholder='Time to stop taking photos',
        required=True,
        max_length=20
    )

    def __init__(self,
                 callback: Callable[[time, time], Awaitable],
                 start_time: Optional[time] = None,
                 end_time: Optional[time] = None) -> None:
        """
        Initialize this modal, which prompts the user to update the runtime
        for a schedule entry.

        Though the times can be None initially, once set, they cannot be
        removed.

        Args:
            callback: The asynchronous function to call to update the start and
            end times.
            start_time: The currently set time of day to start. Defaults to
            None.
            end_time: The currently set time of day to end. Defaults to None.
        """

        super().__init__()
        self.callback: Callable[[time, time], Awaitable] = callback

        # Set defaults, if given
        if start_time is not None:
            self.start_time.default = utils.format_time(start_time)
        if end_time is not None:
            self.end_time.default = utils.format_time(end_time)

        _log.debug(f'Created a change runtime modal for a schedule entry')

    async def on_submit(self, interaction: Interaction) -> None:
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
        except utils.ValidationError as e:
            # Send the error message
            embed = utils.contrived_error_embed(
                title=f'Error: Invalid {e.attr}',
                text=e.msg
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Set the values
        await self.callback(start, end)

    @staticmethod
    def parse_time(time_str: str,
                   boundary: Literal['Start', 'End'],
                   start_time: Optional[time] = None) -> time:
        """
        Parse the given time.

        Args:
            time_str: The time to parse.
            boundary: Whether this is the start or end time.
            start_time: If this is the end time, pass the parsed start time to
            confirm that the end time is after it. Defaults to None.

        Returns:
            The parsed time.

        Raises:
            utils.ValidationError: If the time is invalid. This explains what's wrong
            with it with a user-friendly message.
        """

        if time_str is None or not time_str.strip():
            raise utils.ValidationError(attr=boundary + ' Time',
                                        msg='You must specify both the start and '
                                            'end time.')

        try:
            parsed_time: datetime = dateutil.parser.parse(time_str)
        except ValueError:
            clean: str = discord_utils.escape_markdown(time_str)
            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time **\"{clean}\"** is invalid. "
                    "Enter a date or time in a standard format (e.g. "
                    f"'10:04 p.m.' or '22:00:31')."
            )
        except OverflowError:
            clean: str = discord_utils.escape_markdown(time_str)
            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time **\"{clean}\"** couldn't "
                    "be understood properly. It may have too large of numbers "
                    "or too many decimals. Please try using a standard time"
                    "format."
            )

        # The user should only give a time, not a date
        if parsed_time.date() != datetime.now().date():
            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"Do not specify a date in the runtime. The days that use "
                    "this start/end time are determined by a separate rule in "
                    "this schedule entry."
            )

        # Remove the date part
        parsed_time: time = parsed_time.time()

        # For end times, make sure the start time came first
        if start_time is not None and parsed_time <= start_time:
            clean: str = utils.format_time(parsed_time)
            start: str = utils.format_time(start_time)
            raise utils.ValidationError(
                attr=boundary + ' Time',
                msg=f"The end time **\"{clean}\"** is invalid. It must come "
                    f"after the start time **\"{start}\"**."
            )

        # The time passed validation
        return parsed_time


class SpecificDatesModal(ui.Modal, title='Add Dates'):
    # The time it starts taking photos
    dates_field = ui.TextInput(
        label='Dates',
        placeholder=f'Enter 1-{Dates.MAX_ALLOWED_DATES} dates, '
                    'separated by commas',
        required=False,
        style=TextStyle.paragraph,
        max_length=600
    )

    def __init__(self,
                 callback: Callable[[Optional[list[date]], bool], Awaitable],
                 adding: bool) -> None:
        """
        Initialize this modal, which prompts the user to either add specific
        dates to a schedule entry or remove existing dates.

        Args:
            callback: The function to call with (a) the list of dates and (b)
            a boolean indicating whether to add (True) or remove them (False).
            adding: Whether this is for adding new dates (True) or removing
            existing dates (False).
        """

        super().__init__()
        self.callback: Callable[[Optional[str], bool], Awaitable] = callback
        self.adding: bool = adding

        if not adding:
            self.title = 'Remove Dates'
            self.dates_field.placeholder = ('Enter dates to remove, '
                                            'separated by commas')

        _log.debug(f'Created a specific dates modal for a timelapse schedule')

    async def on_submit(self, interaction: Interaction) -> None:
        """
        Process the interactions, parsing and validating it and
        then running the callback function.

        This doesn't check to make sure that the user isn't adding too many
        dates. However, it does catch utils.ValidationErrors thrown by the callback
        function and pass them along to the user.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Defer a response, as we'll be editing an existing message
        await interaction.response.defer()

        if not self.dates_field.value.strip():
            await self.callback(None, self.adding)
            return

        # Split by commas and semicolons
        date_strs: list[str] = (
            self.dates_field.value
            .replace(';', ',')
            .replace('\n', ',')
            .split(',')
        )

        # Parse the dates
        parsed_dates: list[date] = []

        try:
            for date_str in date_strs:
                if date_str.strip():
                    parsed_dates.append(self.parse_time(date_str))
        except utils.ValidationError as e:
            # Send the error message
            embed = utils.contrived_error_embed(
                title='Error: Invalid Date',
                text=e.msg
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If there aren't any dates, they must have all been blank strings
        if len(parsed_dates) == 0:
            embed = utils.contrived_error_embed(
                title='Error: Missing Dates',
                text="It looks like you tried to enter some dates, but they "
                     "couldn't be understood properly. Please try using a "
                     f"standard date format, such as {self.get_examples()}, "
                     f"and make sure you separate them with commas or "
                     f"semicolons."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Pass parsed dates to the callback function
        try:
            await self.callback(parsed_dates, self.adding)
        except utils.ValidationError as e:
            # Send the error message
            embed = utils.contrived_error_embed(title=e.attr, text=e.msg)
            await interaction.followup.send(embed=embed, ephemeral=True)

    def parse_time(self, date_string: str) -> date:
        """
        Parse the given date. This ensures that the date is valid.

        This will throw an error if the date specifies a particular time or
        if it is in the past. The current date is accepted.

        Args:
            date_string: The string to parse as a date.

        Returns:
            The parsed date.

        Raises:
            utils.ValidationError: If the date is invalid. This explains what's wrong
            with it with a user-friendly message.
        """

        today: date = datetime.now().date()

        try:
            parsed: datetime = dateutil.parser.parse(date_string)
        except ValueError:
            clean: str = utils.trunc(date_string, 100, escape_markdown=True)
            raise utils.ValidationError(
                msg=f"The date **\"{clean}\"** is invalid. Enter a date in a "
                    f"standard format, such as {self.get_examples()}."
            )
        except OverflowError:
            clean: str = utils.trunc(date_string, 100, escape_markdown=True)
            raise utils.ValidationError(
                msg=f"The date **\"{clean}\"** couldn't be understood "
                    f"properly. It may have too large of numbers or too many "
                    "decimals. Please try using a standard date format, such "
                    f"as {self.get_examples()}."
            )

        # The user should only give a time, not a date
        if parsed.time() != time():
            raise utils.ValidationError(
                msg=f"Do not specify a time. That is controlled separately "
                    "and applied to all the dates in this schedule entry."
            )

        # Remove the time part
        parsed_date: date = parsed.date()

        # Make sure it's not in the past
        if parsed_date < today:
            clean: str = parsed_date.strftime('%Y-%m-%d')
            diff = (today - parsed_date).days
            if diff == 1:
                diff = 'yesterday'
            elif diff == 2:
                diff = 'two days ago'
            else:
                diff = f"{diff} days ago"
            raise utils.ValidationError(
                msg=f"The date **\"{clean}\"** is invalid. Dates can't be in "
                    f"the past, but that was **\"{diff}\"**."
            )

        # The date validation
        return parsed_date

    @staticmethod
    def get_examples() -> str:
        """
        Get a string with two correctly formatted dates. This is useful for
        error messages. The dates are today and some arbitrary day in the
        future. Each is enclosed in quotation marks.

        Returns:
            The examples.
        """

        today: str = datetime.now().strftime('%Y-%m-%d')
        future: str = ((datetime.now() + timedelta(days=600))
                       .strftime('%m/%d/%Y'))
        return f"\"{today}\" or \"{future}\""
