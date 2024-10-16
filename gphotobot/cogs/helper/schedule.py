from __future__ import annotations

from abc import ABC, abstractmethod
import bisect
from collections.abc import Awaitable, Callable, Collection, Iterable, Iterator
from datetime import date, datetime, time, timedelta
from enum import Enum
from functools import total_ordering
import logging
from typing import Literal, Optional, Union

import dateutil.parser
import discord
from discord import ButtonStyle, Embed, ui, utils as discord_utils, TextStyle, \
    SelectOption

from gphotobot.conf import settings
from gphotobot.utils import const, utils
from gphotobot.utils.validation_error import ValidationError
from gphotobot.utils.base.view import BaseView
from . import timelapse_utils
from .runtime_modal import ChangeRuntimeModal
from .interval_modal import ChangeIntervalModal

_log = logging.getLogger(__name__)


class TracksChanges(ABC):
    @abstractmethod
    def has_changed(self) -> bool:
        """
        Determine whether any of this object's values have changed.

        Returns:
            True if and only if something has changed.
        """


class ChangeTracker[T](TracksChanges):
    def __init__(self, value: T) -> None:
        self._original_value = value
        self._current_value = value

    @property
    def current(self) -> T:
        """
        Get the current value with possible changes.

        Returns:
            The current value.
        """

        return self._current_value

    def update(self, value: T) -> bool:
        """
        Replace the current value with a new one, and return whether it changed.

        Args:
            value: The new value.

        Returns:
            Whether the new value is different from the previous one (NOT
            whether it's different from the original).
        """

        if self._current_value == value:
            return False
        else:
            self._current_value = value
            return True

    @property
    def original(self) -> T:
        """
        Get the original value before any changes.

        Returns:
            The original value.
        """

        return self._original_value

    def has_changed(self) -> bool:
        """
        Determine whether the value has changed by comparing the current and
        original values.

        If the given object implements TracksChanges (as this does), it also
        calls has_changed() on that object.

        Returns:
            True if and only if the value has changed.
        """

        if self._current_value != self.original:
            return True

        if isinstance(self._current_value, TracksChanges):
            return self._current_value.has_changed()

        return False


class ChangeTrackingDict[T, U](dict, TracksChanges):
    def __init__(self, d: Optional[dict[T, U]]):
        d = {} if d is None else d
        super().__init__(d)
        self.original: dict[T, U] = d

    def save_current_state(self):
        self.original = dict(self)

    def has_changed(self) -> bool:
        return (
                self.original != dict(self) or
                any(isinstance(k, TracksChanges) and k.has_changed()
                    for k in self.keys()) or
                any(isinstance(v, TracksChanges) and v.has_changed()
                    for v in self.values())
        )


class Days(ABC):
    """
    A Days object constitutes the primary part of a ScheduleEntry, specifying
    the single day or multiple days that it applies.

    All Days objects must be immutable. Methods that apply "changes" should
    actually return modified copies.
    """

    @abstractmethod
    def to_db(self) -> str:
        """
        Convert the data for this Days identifier into a string that can be used
        in the database. It must have all the information necessary to recreate
        this Days object.

        This should be the name of the class with all the relevant data in
        parentheses:
        "Days(data_here)"

        Returns:
            A database-ready string.
        """

        pass

    @classmethod
    @abstractmethod
    def from_db(cls, string: str) -> Days:
        """
        Given a database string produced by to_db(), construct an instance of
        this class.

        Returns:
            A new Days object.
        """

        pass

    @abstractmethod
    def is_one_date(self) -> bool:
        """
        Determine whether this rule only applies to exactly one date, meaning
        it is only relevant for one day in time.

        Returns:
            Whether it applies to just one date.
        """

        pass

    @abstractmethod
    def list_days(self) -> str:
        """
        Get a string with a *concise* list of all Days included in this rule. In
        some cases, this is identical to the header string. In other cases, it's
        used to get extra information missing from the header.

        Returns:
            A string listing all the days.
        """

    @abstractmethod
    def to_header_str(self) -> tuple[str, bool]:
        """
        Get a short, user-friendly description of this Days rule that can go
        in the header of an embed. If there's too much information to fit in
        a short header, list something generic that describes the type of
        rule.

        This also returns a boolean indicating whether the header contains all
        the information about the days. For example, "MWF" gives you all the
        information about a DaysOfWeek rule on Mondays, Wednesdays, and Fridays.
        Similarly, "2024-01-01" gives you all the information about a single
        Date rule. But "5 custom dates" doesn't have enough information, because
        it's not clear what those dates are.

        Returns:
            A tuple with the header text and whether it has all the info.
        """

        pass

    @abstractmethod
    def rule_type_str(self) -> str:
        """
        Get a user-friendly string describing the type of this rule. Often,
        this isn't dependent on the contents of the rule at all.

        Returns:
            A user-friendly rule string.
        """

        pass

    @abstractmethod
    def does_ever_run(self) -> bool:
        """
        Check whether this rule will ever apply at all. If False, it means that
        this rule is empty or will otherwise never take effect.

        Returns:
            Whether this rule ever runs, even once.
        """

        pass

    @abstractmethod
    def __eq__(self, other: any) -> bool:
        pass


@total_ordering
class DayOfWeekEnum(Enum):
    """
    Enum for each day of the week that associates them with a particular letter.
    """

    # Index (sorting order), single letter abbreviation, short name

    # As painful as it is, I'm starting the week with Monday because I think
    # the abbreviation MTWRFSU is slightly faster to understand than UMTWRFS
    MONDAY = (0, 'M', 'Mon')
    TUESDAY = (1, 'T', 'Tue')
    WEDNESDAY = (2, 'W', 'Wed')
    THURSDAY = (3, 'R', 'Thur')
    FRIDAY = (4, 'F', 'Fri')
    SATURDAY = (5, 'S', 'Sat')
    SUNDAY = (6, 'U', 'Sun')

    @classmethod
    def from_abbr(cls, abbr: str) -> DayOfWeekEnum:
        """
        Get a day of the week from its single letter abbreviation.

        Args:
            abbr: The single-letter abbreviation. This must be uppercase.

        Returns:
            The associated day of the week.

        Raises:
            ValueError: If there is no match for the given abbreviation.
        """

        for day in cls:
            if abbr == day.value[1]:
                return day

        raise ValueError(f"No DayOfWeek matches for '{abbr}'")

    @classmethod
    def from_full_name(cls, name: str) -> DayOfWeekEnum:
        """
        Get a day of the week from its full name as as string.

        Args:
            name: The full name. This is case in-sensitive.

        Returns:
            The associated day of the week.

        Raises:
            ValueError: If there is no match for the given abbreviation.
        """

        name_upper = name.upper()
        for day in cls:
            if name_upper == day.name:
                return day

        raise ValueError(f"No DayOfWeek matches for '{name}'")

    def __str__(self):
        """
        Return the full, capitalized name of this day (e.g. "Thursday").

        Returns:
            The name of this day of the week.
        """

        return self.name.capitalize()

    def __lt__(self, other):
        """
        Test whether this is less than the given value (presumably another
        DayOfWeekEnum) by comparing the integer value associated with the day.

        Args:
            other: The other value to compare to this one.

        Returns:
            True if and only if they are both day of week enums, and this has
            a lower integer value.
        """

        if self.__class__ is other.__class__:
            return self.value[0] < other.value[0]
        return NotImplemented


EVERY_DAY_OF_WEEK: set[DayOfWeekEnum] = {
    DayOfWeekEnum.MONDAY,
    DayOfWeekEnum.TUESDAY,
    DayOfWeekEnum.WEDNESDAY,
    DayOfWeekEnum.THURSDAY,
    DayOfWeekEnum.FRIDAY,
    DayOfWeekEnum.SATURDAY,
    DayOfWeekEnum.SUNDAY
}

WEEK_DAYS: set[DayOfWeekEnum] = {
    DayOfWeekEnum.MONDAY,
    DayOfWeekEnum.TUESDAY,
    DayOfWeekEnum.WEDNESDAY,
    DayOfWeekEnum.THURSDAY,
    DayOfWeekEnum.FRIDAY
}


class DaysOfWeek(Days, Collection):
    def __init__(self, days: Optional[Iterable[DayOfWeekEnum]] = None):
        """
        Initialize a Dates object with one or more days of the week.

        Args:
            days: One or more day of the week. Duplicates are ignored. Defaults
            to None.
        """

        self._day_set: set[DayOfWeekEnum] = set(days) if days else set()

    def add(self,
            days: DayOfWeekEnum | Iterable[DayOfWeekEnum]) -> DaysOfWeek:
        """
        Get a new DaysOfWeek record with a one or more new day added.

        Args:
            days: One or more days to add.

        Returns:
            A new DaysOfWeek record.
        """

        return self.__class__(self._day_set | set(days))

    def remove(self,
               days: DayOfWeekEnum | Iterable[DayOfWeekEnum]) -> DaysOfWeek:
        """
        Get a new DaysOfWeek record with one or more given days removed. If the
        specified day is not in this record, this effectively creates a copy.

        Args:
            days: One or more days to remove.

        Returns:
            A new DaysOfWeek record.
        """

        return self.__class__(self._day_set - set(days))

    def to_db(self) -> str:
        return 'DaysOfWeek(' + ''.join(d.value[1] for d in self._day_set) + ')'

    @classmethod
    def from_db(cls, string: str) -> DaysOfWeek:
        return cls(DayOfWeekEnum.from_abbr(d) for d in string[11:-1].upper())

    def is_one_date(self) -> bool:
        return False

    def list_days(self) -> str:
        # The header always contains all information, so it works for this
        return self.to_header_str()[0]

    def first_str(self) -> str:
        """
        Get the capitalized name of some day from this week. As this is backed
        by a set, the order (and thus the particular day returned) is not
        guaranteed. This is useful if there's only one day. If there aren't
        any days, it'll raise an error.

        Returns:
            The capitalized name of one of the days (e.g. "Tuesday").
        """

        return next(iter(self._day_set)).name.capitalize()

    def excluded_days(self) -> list[DayOfWeekEnum]:
        """
        Get the days of the week not included in this rule.

        Returns:
            A list of days (in order) not included in this rule.
        """

        return sorted(EVERY_DAY_OF_WEEK - self._day_set)

    def is_weekdays(self) -> bool:
        """
        Check whether this rule applies on Monday, Tuesday, Wednesday, Thursday,
        and Friday, but not on Saturday or Sunday (i.e. the weekdays).

        Returns:
            True if and only if it applies exclusively on weekdays.
        """

        return self._day_set == WEEK_DAYS

    def to_header_str(self) -> tuple[str, bool]:
        if len(self._day_set) == 1:
            return next(iter(self._day_set)).name.capitalize() + 's', True
        elif len(self._day_set) == 7:
            return 'Every Day', True
        elif self._day_set == {DayOfWeekEnum.SUNDAY, DayOfWeekEnum.SATURDAY}:
            return 'Weekends', True
        elif len(self._day_set) == 2:
            return ' & '.join(d.value[2] for d in self), True
        elif self.is_weekdays():
            return 'Weekdays', True
        else:
            return ''.join(d.value[1] for d in self), True

    def rule_type_str(self) -> str:
        return 'Every day' if len(self._day_set) == 7 else 'Days of the week'

    def eq_days(self, days: Collection[DayOfWeekEnum]) -> bool:
        """
        Test whether this rule applies to exactly the given set of days of the
        week.

        Args:
            days: The set of week days to compare to this rule.

        Returns:
            True if and only if the sets are identical.
        """

        if isinstance(days, set):
            return self._day_set == days
        else:
            return self._day_set == set(days)

    def does_ever_run(self) -> bool:
        return len(self) > 0

    def __eq__(self, other: any) -> bool:
        return isinstance(other, self.__class__) and \
            self._day_set == other._day_set

    def __len__(self) -> int:
        return len(self._day_set)

    def __iter__(self) -> Iterator[DayOfWeekEnum]:
        return iter(sorted(self._day_set, key=lambda d: d.value[0]))

    def __contains__(self, x):
        return x in self._day_set


class Dates(Days, Collection):
    # ISO-8601 date format
    DATE_FORMAT = '%Y-%m-%d'

    # The maximum specific dates this can have
    MAX_ALLOWED_DATES = 20

    def __init__(self, dates: Optional[Iterable[datetime | date]] = None):
        """
        Initialize a Dates object with one or more dates.

        Args:
            dates: One or more dates. Duplicates are ignored. Defaults to None.

        Raises:
            ValidationError: If the number of dates exceeds the maximum allowed
            number (MAX_ALLOWED_DATES). This is intended for showing to the user
            in an embed. The attr should be used as the embed title.
        """

        if dates:
            # Process the list of dates, getting them to the right data type
            self._date_list: list[date] = list(set(
                d.date() if isinstance(d, datetime) else d
                for d in dates
            ))

            # Validate length before sorting
            if len(self._date_list) > self.MAX_ALLOWED_DATES:
                raise ValidationError(
                    attr='Error: Too Many Dates',
                    msg=f"You can't have more than "
                        f"**{Dates.MAX_ALLOWED_DATES}** specific dates in a "
                        f"schedule entry. Try creating another entry if you "
                        f"need more dates."
                )

            # Sort the list
            self._date_list.sort()
        else:
            self._date_list: list[date] = []

    def add(self,
            new_dates: Union[date,
            datetime,
            Iterable[date | datetime]]) -> Dates:
        """
        Get a new Dates record with one or more new dates added. If the dates
        are already in this list, nothing happens.

        Args:
            new_dates: One or more dates to add.

        Returns:
            A new Dates record.

        Raises:
            ValidationError: If the number of dates exceeds the maximum allowed
            threshold (MAX_ALLOWED_DATES). See __init__().
        """

        # Copy the set of dates for this new object
        dates_copy = self._date_list.copy()

        # Convert a single datetime to a date
        if isinstance(new_dates, datetime):
            new_dates = new_dates.date()

        # Add new date(s)
        if isinstance(new_dates, date):
            if new_dates not in dates_copy:
                bisect.insort(dates_copy, new_dates)
        else:
            for d in new_dates:
                if isinstance(d, datetime):
                    d = d.date()
                if d not in dates_copy:
                    bisect.insort(dates_copy, d)

        # Return the copy with (possibly) added dates
        # TODO disable re-sorting in constructor, which makes insort pointless
        return self.__class__(dates_copy)

    def remove(self, removed_dates: Union[date,
    datetime,
    Iterable[date | datetime]]) -> Dates:
        """
        Get a new Dates record with one or more dates removed. If the given
        dates aren't in this record, then this just creates a copy.

        Args:
            removed_dates: The dates to remove.

        Returns:
            A new Dates record with the dates removed.
        """

        # Case with a single datetime
        if isinstance(removed_dates, datetime):
            remove = removed_dates.date()
            return self.__class__(d for d in self if d != remove)

        # Case with a single date
        if isinstance(removed_dates, date):
            return self.__class__(d for d in self if d != removed_dates)

        # Case with an arbitrary number of dates and/or datetimes
        r = tuple(d if isinstance(d, date) else d.date() for d in removed_dates)
        return self.__class__(d for d in self._date_list if d not in r)

    def to_db(self) -> str:
        return (
                'Dates(' +
                ','.join(d.strftime(self.DATE_FORMAT)
                         for d in self._date_list) +
                ')'
        )

    @classmethod
    def from_db(cls, string: str) -> Dates:
        return cls(datetime.strptime(d, cls.DATE_FORMAT).date()
                   for d in string[6:-1].upper().split(','))

    def is_one_date(self) -> bool:
        return len(self._date_list) == 1

    def list_days(self) -> str:
        # Handle simple cases with 0 or 1 dates
        if len(self._date_list) == 0:
            return "*Add dates below*"
        elif len(self._date_list) == 1:
            return self.date_to_ordinal_str(self._date_list[0])

        # Group remaining days into consecutive ranges
        ranges: list[tuple[date, Optional[date]]] = []

        start: date = self._date_list[0]
        end: date = start
        ONE_DAY: timedelta = timedelta(days=1)

        for i in range(1, len(self._date_list)):
            if self._date_list[i] == end + ONE_DAY:
                end = self._date_list[i]
            else:
                ranges.append((start, None) if start == end else (start, end))
                start = end = self._date_list[i]

        # Handle last range/date
        ranges.append((start, None) if start == end else (start, end))

        # Test whether all the dates are in the same year
        # noinspection PyUnusedLocal
        same_year: bool = all(d.year == end.year for d in self._date_list)

        # Convert the dates to strings, ignoring years if they're all the same
        def to_str(d: date) -> str:
            return (self.date_to_ordinal_str(d) if same_year
                    else d.strftime('%Y-%m-%d'))

        # Combine the dates and date ranges into a single formatted string
        merged = utils.list_to_str(
            to_str(s) if e is None else to_str(s) + " to " + to_str(e)
            for s, e in ranges
        )

        # If they're all using the same year and that year is not the current
        # year, then add the year at the end of the string
        if same_year and end.year != datetime.now().year:
            merged += ' of ' + str(end.year)

        # Return the final string
        return merged

    @staticmethod
    def date_to_ordinal_str(d: date) -> str:
        """
        Convert a date to a string with an abbreviated month name and the day
        of the month with an ordinal. This does not include the year. For
        example: "Oct 8th" or "May 22nd."

        Args:
            d: The date to format.

        Returns:
            The formatted string.
        """

        day = d.day
        suffix = "th" if 11 <= day <= 13 else \
            {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return d.strftime(f'%b {day}{suffix}')

    def to_header_str(self) -> tuple[str, bool]:
        # Try listing the dates
        days = self.list_days()

        # If the string form contains more than two dates, just say how many
        # total dates there are
        if ',' in days or (' to ' in days and ' and ' in days):
            return f'{len(self._date_list)} custom dates', False
        else:
            return days, True

    def rule_type_str(self) -> str:
        return 'Specific dates'

    def does_ever_run(self) -> bool:
        return len(self) > 0

    def __eq__(self, other: any) -> bool:
        # The dates list should always be sorted
        return isinstance(other, Dates) and self._date_list == other._date_list

    def __str__(self) -> str:
        """
        This is identical to list_days(). It returns a user-friendly list of
        every date, written as concisely as possible.

        Returns:
            A list of dates.
        """

        return self.list_days()

    def __repr__(self):
        """
        Get a string representation of this Dates object. It includes each date
        in the ISO-8601 format YYYY-MM-DD, without any attempt to combine them
        for easier readability (as in the str() version). Each date is
        separated by a semicolon, and they are all enclosed in "Dates()".

        Returns:
            String representation of this Dates object.
        """

        date_str = ';'.join(d.strftime(self.DATE_FORMAT)
                            for d in self._date_list)
        return f"{self.__class__.__name__}({date_str})"

    def __iter__(self):
        return iter(self._date_list)

    def __len__(self):
        return len(self._date_list)

    def __contains__(self, x):
        return x in self._date_list


class ScheduleEntry(TracksChanges):
    """
    A ScheduleEntry is the building block of a full timelapse Schedule. It
    coordinates a single range of time during which the timelapse will run.
    This is done by specifying a day (either by a date, day of the week, or
    some other rule), and a range of time during that day. Note that the day
    specifier can refer to multiple days (e.g. Monday through Wednesday).

    It may also include other configuration specific to this block of time, such
    as the interval between photos or camera settings.

    Because timelapses photos are stored in directories based on the date, an
    individual schedule entry can never span multiple days.
    """

    # Default start time: start of the day (00:00:00.000000 a.m.)
    MIDNIGHT = time()

    # Default end time: end of the day (11:59:59.999999 P.M.)
    ELEVEN_FIFTY_NINE = time(hour=23, minute=59, second=59, microsecond=999999)

    def __init__(self,
                 days: Days = DaysOfWeek(EVERY_DAY_OF_WEEK),
                 start_time: time = MIDNIGHT,
                 end_time: time = ELEVEN_FIFTY_NINE,
                 config: Optional[dict[str, any]] = None):
        """
        Initialize an entry for a schedule.

        Args:
            days: The day (or days) this applies. Defaults to every day of
            the week.
            start_time: The time of day this rule starts. Defaults to midnight.
            end_time: The time of day this rule ends. Defaults to 11:59:59 p.m.
            config: Timelapse configuration specific to this schedule entry.
        """

        self._days: ChangeTracker[Days] = ChangeTracker(days)
        self._start_time: ChangeTracker[time] = ChangeTracker(start_time)
        self._end_time: ChangeTracker[time] = ChangeTracker(end_time)
        self._config: ChangeTrackingDict[str, any] = ChangeTrackingDict(config)

    @property
    def days(self) -> Days:
        return self._days.current

    @days.setter
    def days(self, d: Days) -> None:
        self._days.update(d)

    @property
    def start_time(self) -> time:
        return self._start_time.current

    @start_time.setter
    def start_time(self, t: time) -> None:
        self._start_time.update(t)

    @property
    def end_time(self) -> time:
        return self._end_time.current

    @end_time.setter
    def end_time(self, t: time) -> None:
        self._end_time.update(t)

    def has_changed(self) -> bool:
        return self._days.has_changed() or \
            self._start_time.has_changed() or \
            self._end_time.has_changed() or \
            self._config.has_changed()

    def get_embed_field_strings(self) -> tuple[str, str]:
        """
        Get user-friendly strings that describe this schedule entry for use in
        an embed field.

        The first parameter, the embed header, briefly describes the days, if
        possible.

        The second parameter, the body text, lists the start/end times and
        configuration.

        Returns:
            A tuple with the embed header and contents, in that order.
        """

        header, has_all_info = self.days.to_header_str()

        body = (f"From **{utils.format_time(self.start_time, use_text=True)}** "
                f"to **{utils.format_time(self.end_time, use_text=True)}**")

        # If missing some info in header, add it to the time range
        if not has_all_info:
            body = '(' + utils.trunc(self.days.list_days(), 50) + ')\n' + body

        # Get a formatted string with config entries
        config = self.get_config_text()
        if config is None:
            return header, body

        # Add config entries, but don't exceed the max embed value length

        # (The -1 is for the newline '\n')
        available_chars = const.EMBED_FIELD_VALUE_LENGTH - len(body) - 1

        # If there are fewer tha 10 characters left, just add an ellipsis
        if available_chars < 10:
            if available_chars == 0:
                return header, body
            else:
                return header, body + '\n…'

        trimmed = 0
        while len(config) > available_chars:
            # If the config is too long, try to remove the last line
            index = config.rfind('\n')

            # If this is the last line, just list the number of config lines
            if index == -1:
                l = len(self._config)
                config = f"*Plus {l} configuration{'' if l == 1 else 's'}*"
                if len(config) > available_chars:
                    return header, body + '\n…'
            else:
                # Remove the last line
                trimmed += 1
                config = config[:index]

        return header, body + '\n' + config

    def get_config_text(self) -> Optional[str]:
        """
        Get text for an embed that lists the config options. If there are no
        custom config settings for this schedule entry, it returns None.

        Returns:
            The config options, or None.
        """

        if not self._config:
            return None

        text = ''
        for key, value in self._config.items():
            # Add the key text
            text += f"\n**{key.replace('_', ' ').title()}:** "

            # Add the value
            if key == 'capture_interval':
                text += utils.format_duration(value)
            else:
                text += str(value)

        return text[1:] if text else None

    def runs_all_day(self) -> bool:
        """
        Check whether this runs all day: from midnight to 11:59:59 p.m.

        Returns:
            True if and only if it runs all day.
        """

        return self.start_time == self.MIDNIGHT and \
            self.end_time == self.ELEVEN_FIFTY_NINE

    def set_config_interval(self, interval: Optional[timedelta]) -> bool:
        """
        Set a config entry for a custom capture interval.

        Args:
            interval: The new interval. If this is None, any existing entry is
            removed.

        Returns:
            A boolean indicating whether anything changed.
        """

        if interval is None:
            if 'interval' in self._config:
                del self._config['capture_interval']
                return True
        elif self.get_config_interval() != interval:
            self._config['capture_interval'] = interval
            return True

        # Nothing changed
        return False

    def get_config_interval(self) -> Optional[timedelta]:
        """
        Get the config entry for a custom capture interval, if one has been set.

        Returns:
            The capture interval, or None if not set.
        """

        return self._config.get('capture_interval', None)


class Schedule(TracksChanges, Collection):
    def __init__(self):
        """
        Create a new Schedule. This is a collection of ScheduleEntries that
        coordinate a timelapse.
        """

        self._entries: ChangeTracker[list[ScheduleEntry]] = ChangeTracker([])

    @property
    def entries(self) -> list[ScheduleEntry]:
        return self._entries.current

    @entries.setter
    def entries(self, value: list[ScheduleEntry]) -> None:
        self._entries.update(value)

    def __len__(self) -> int:
        """
        Get the length of this schedule (i.e. the number of entries it
        contains).

        Returns:
            The number of entries.
        """

        return len(self.entries)

    def __iter__(self) -> Iterator[ScheduleEntry]:
        """
        Iterate over the entries in this schedule.

        Returns:
            The entries in this schedule.
        """

        return iter(self.entries)

    def __contains__(self, x, /):
        return x in self.entries

    def add_entry(self, entry: ScheduleEntry) -> None:
        """
        Validate a new entry. If it passes validation, add it to the schedule.
        This tests the following rules:

        1. The Days rule actually applies at some point in time.
        2. It doesn't explicitly refer to dates in the past.
        3. If it explicitly refers exclusively to today, the start time must
           be in the future.
        4. If the Days *exactly* match an existing entry, its time range must
           not overlap at all.

        Args:
            entry: The entry to add.

        Raises:
            ValidationError: If the validation fails in any way.
        """

        # ========== Check that it will run at least once ==========

        if not entry.days.does_ever_run():
            raise ValidationError(
                msg="This entry is invalid: it never runs. Make sure you "
                    "specify at least one day that it should run."
            )

        # ========== Check for specific dates/times in the past ==========

        days = entry.days
        if isinstance(days, Dates):
            today = date.today()
            now = datetime.now().time()
            for d in days:
                if d < today:
                    delta = (today - d).days
                    raise ValidationError(
                        msg="Specific dates can't be in the past, but "
                            f"**{d.strftime('%Y-%m-%d')}** was **{delta}** "
                            f"day{'' if delta == 1 else 's'} ago."
                    )
                elif d == today and days.is_one_date() and \
                        entry.start_time <= now:
                    start = datetime.combine(today, entry.start_time)
                    delta = utils.format_duration(datetime.now() - start)
                    raise ValidationError(
                        msg="Schedule entries for just one specific date can't "
                            "start in the past, but the rule on today, "
                            f"**{d.strftime('%Y-%m-%d')}**, starts "
                            f"at **{start.strftime('%I:%M:%S %p')}**. That "
                            f"was **{delta}** ago."
                    )

        # ========== Check for overlapping time on identical Days ==========

        matching_entries = [e for e in self.entries if e.days == entry.days]
        for e in matching_entries:
            if e.end_time > entry.start_time and e.start_time < entry.end_time:
                e_s, e_e = (utils.format_time(e.start_time),
                            utils.format_time(e.end_time))
                en_s, en_e = (utils.format_time(entry.start_time),
                              utils.format_time(entry.end_time))
                if e.start_time < entry.start_time:
                    s1, e1, s2, e2 = e_s, e_e, en_s, en_e
                else:
                    s1, e1, s2, e2 = en_s, en_e, e_s, e_e

                raise ValidationError(
                    msg="Two entries on the same exact day(s) can't have "
                        f"overlapping times. But **'{s1}'** to **'{e1}'** "
                        f"overlaps with **'{s2}'** to **'{e2}'**."
                )

        # ========== Validation passed ==========

        self.entries.append(entry)

    def remove_entry(self, index: int) -> None:
        """
        Remove an entry specified by its index.

        Args:
            index: The index of the schedule entry to remove.
        """

        del self.entries[index]

    def move_entry(self, index: int, move_up: bool) -> None:
        """
        Move an entry specified by its index either up or down.

        This raises an error if the index is invalid or if you try to move
        the first entry up or the last entry down.

        Args:
            index: The index of the entry to move.
            move_up: Whether to move it up in the list (i.e. lower index).

        Raises:
            IndexError: If the index is invalid or you try to move the first
            entry up or the last entry down.
        """

        # Check for an invalid index
        if index < 0 or index > len(self):
            raise IndexError(f"Attempted to move invalid index {index} "
                             f"for a schedule with {len(self)} "
                             f"entr{'y' if len(self) == 1 else 'ies'}")
        elif index == 0 and move_up:
            raise IndexError("Attempted to move up the entry at index 0")
        elif index == len(self) - 1 and not move_up:
            raise IndexError("Attempted to move down the last entry at "
                             f"index {index}")

        # Move the entry
        destination = index + (-1 if move_up else 1)
        swap = self.entries[destination]
        self.entries[destination] = self.entries[index]
        self.entries[index] = swap

    def get_summary_str(self,
                        max_len: int = const.EMBED_FIELD_VALUE_LENGTH) -> str:
        """
        Get a string that very succinctly summarizes this schedule. It is
        designed to fit in the body of an embed field.

        Args:
            max_len: The maximum length of the returned string, within reason.

        Returns:
            A concise summary string.
        """

        l = len(self)
        if l == 0:
            return '*No entries. Edit the schedule to add some.*'

        if l == 1:
            header, body = self.entries[0].get_embed_field_strings()
            return f"**{header}**\n{body}"

        text = ''
        for i, entry in enumerate(self):
            line, _ = entry.days.to_header_str()
            if len(text) + len(line) + 2 <= max_len:
                text += '\n- ' + line
            else:
                omitted = len(self) - i - 1
                footer = f"*(plus {omitted} more)*"
                while len(text) + len(footer) > max_len:
                    omitted += 1
                    text = text[:text.rfind('\n')]
                    footer = f"*(plus {omitted} more)*"
                text += '\n' + footer
                break

        return text[1:]

    def has_changed(self) -> bool:
        return self._entries.has_changed() or \
            any(e.has_changed for e in self.entries)


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
        except ValidationError as e:
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
            ValidationError: If the time is invalid. This explains what's wrong
            with it with a user-friendly message.
        """

        if time_str is None or not time_str.strip():
            raise ValidationError(attr=boundary + ' Time',
                                  msg='You must specify both the start and '
                                      'end time.')

        try:
            parsed_time: datetime = dateutil.parser.parse(time_str)
        except ValueError:
            clean: str = discord_utils.escape_markdown(time_str)
            raise ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time **\"{clean}\"** is invalid. "
                    "Enter a date or time in a standard format (e.g. "
                    f"'10:04 p.m.' or '22:00:31')."
            )
        except OverflowError:
            clean: str = discord_utils.escape_markdown(time_str)
            raise ValidationError(
                attr=boundary + ' Time',
                msg=f"The {boundary.lower()} time **\"{clean}\"** couldn't "
                    "be understood properly. It may have too large of numbers "
                    "or too many decimals. Please try using a standard time"
                    "format."
            )

        # The user should only give a time, not a date
        if parsed_time.date() != datetime.now().date():
            raise ValidationError(
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
            raise ValidationError(
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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the interactions, parsing and validating it and
        then running the callback function.

        This doesn't check to make sure that the user isn't adding too many
        dates. However, it does catch ValidationErrors thrown by the callback
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
        except ValidationError as e:
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
        except ValidationError as e:
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
            ValidationError: If the date is invalid. This explains what's wrong
            with it with a user-friendly message.
        """

        today: date = datetime.now().date()

        try:
            parsed: datetime = dateutil.parser.parse(date_string)
        except ValueError:
            clean: str = utils.trunc(date_string, 100, escape_markdown=True)
            raise ValidationError(
                msg=f"The date **\"{clean}\"** is invalid. Enter a date in a "
                    f"standard format, such as {self.get_examples()}."
            )
        except OverflowError:
            clean: str = utils.trunc(date_string, 100, escape_markdown=True)
            raise ValidationError(
                msg=f"The date **\"{clean}\"** couldn't be understood "
                    f"properly. It may have too large of numbers or too many "
                    "decimals. Please try using a standard date format, such "
                    f"as {self.get_examples()}."
            )

        # The user should only give a time, not a date
        if parsed.time() != time():
            raise ValidationError(
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
            raise ValidationError(
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


class ScheduleEntrySelector(BaseView):
    def __init__(self,
                 interaction: discord.Interaction,
                 schedule: Schedule,
                 mode: Literal['edit', 'move', 'remove'],
                 callback: Callable[[Literal['edit', 'remove'], int],
                 Awaitable],
                 callback_cancel: Callable[[], Awaitable]):
        """
        Initialize a schedule entry selector. This allows the user to select
        one of the schedule entries, either to edit it or delete it.

        Args:
            interaction: The interaction to edit.
            schedule: The schedule with entries to choose from. This must
            contain at least two entries; otherwise a selection menu wouldn't be
            necessary.
            mode: Whether the selected entry will be edited, moved, or removed.
            callback: The async callback function to run when the user makes
            a selection.
            callback_cancel: The async callback to run if the user clicks the
            "back" button without selecting an entry.

        Raises:
            AssertionError: If the list of entries doesn't contain at least two
            entries.
        """

        assert len(schedule.entries) >= 2
        super().__init__(interaction, callback, callback_cancel)

        self.schedule: Schedule = schedule
        self.mode: Literal['edit', 'move', 'remove'] = mode

        # Add the selection menu
        self.menu = self.create_select_menu(
            placeholder='Select a schedule entry...',
            options=list(f"{i + 1}. {entry.get_embed_field_strings()[0]}"
                         for i, entry in enumerate(schedule)),
            callback=self.on_select
        )

        # Add a back button that'll run the cancel callback
        self.button_back = self.create_button(
            label='Back',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_BACK,
            callback=lambda _: self.run_cancel_callback()
        )

        # The index selected by the user. This is only used in 'move' mode
        self.index: Optional[int] = None

        # If this is in 'move' mode, create buttons for the direction to move.
        # We'll add them later
        if mode == 'move':
            self.move_up: ui.Button = self.create_button(
                label='Move up',
                style=ButtonStyle.primary,
                emoji=settings.EMOJI_MOVE_UP,
                callback=lambda i: self.on_click_move(i, True),
                add=False
            )
            self.move_down: ui.Button = self.create_button(
                label='Move down',
                style=ButtonStyle.primary,
                emoji=settings.EMOJI_MOVE_DOWN,
                callback=lambda i: self.on_click_move(i, False),
                add=False
            )

        _log.debug(f'Created a schedule entry selector with {len(schedule)} '
                   f'entries')

    async def build_embed(self) -> Embed:
        # Set the description based on whether something is currently selected
        if self.index is None:
            desc = ('Select one of the following entries to '
                    f'{self.mode} it.')
        else:
            desc = f'Selected entry #{self.index + 1}. '
            if self.index == 0:
                desc += 'This is the first entry, so it can only be moved down.'
            elif self.index == len(self.schedule) - 1:
                desc += 'This is the last entry, so it can only be moved up.'
            else:
                desc += 'Click a button to move it up or down in the list.'

        # Create the base embed
        embed = utils.default_embed(
            title='Timelapse Schedule Editor',
            description=desc
        )

        # Add a field for each schedule entry
        for index, entry in enumerate(self.schedule):
            header, body = entry.get_embed_field_strings()
            embed.add_field(
                name=f'{index + 1}. {header}',
                value=body,
                inline=False
            )

        # Return the fully constructed embed
        return embed

    async def on_select(self, interaction: discord.Interaction) -> None:
        """
        This is the callback that runs when the user selects a schedule entry.

        Args:
            interaction: The interaction.
        """

        try:
            # -1 because in the selection menu they're 1-indexed
            index = int(self.menu.values[0].split('.')[0]) - 1
        except ValueError as e:
            # Handle the theoretically impossible error if int() fails
            await utils.handle_err(
                interaction,
                e,
                text="Unexpected error: couldn't identify the selected entry",
                log_text="Unreachable: couldn't extract index from selection "
                         f"menu value '{self.menu.values[0]}' in entry selector"
            )
            return

        # If it's not move mode, run the callback, and exit
        if not self.mode == 'move':
            self.stop()
            await self.callback(self.mode, index)
            return

        # In move mode, we need to add the up/down buttons if this is the first
        # time the user selected an entry
        if self.index is None:
            self.remove_item(self.button_back)
            self.add_items((self.move_up, self.move_down, self.button_back))

        # Update the chosen index
        self.index = index

        # Enable/disable move buttons based on the index
        if self.mode == 'move':
            self.move_up.disabled = self.index == 0
            self.move_down.disabled = self.index == len(self.schedule) - 1

        # Make sure the selected entry persists when the display is refreshed
        utils.set_menu_default(self.menu, self.menu.values[0])

        # Refresh the display
        await self.refresh_display()

    async def on_click_move(self,
                            interaction: discord.Interaction,
                            move_up: bool) -> None:
        """
        This is the callback function that runs when the user clicks either the
        up or down buttons.

        Args:
            interaction: The interaction that triggers this UI event.
            move_up: Whether the user clicked the "move up" button.
        """

        try:
            self.schedule.move_entry(self.index, move_up)
        except IndexError as e:
            await utils.handle_err(interaction, e,
                                   text='Unreachable: invalid move request')
            return

        # Update the index to the new position of the entry
        self.index += (-1 if move_up else 1)

        # Rebuild the selection menu to show the proper indices
        self.menu.options = [
            SelectOption(label=f"{i + 1}. {e.get_embed_field_strings()[0]}")
            for i, e in enumerate(self.schedule)
        ]
        self.menu.options[self.index].default = True

        # Enable/disable the move buttons based on the index
        self.move_up.disabled = self.index == 0
        self.move_down.disabled = self.index == len(self.schedule) - 1

        # Update this display
        await self.refresh_display()


class ScheduleEntryBuilder(BaseView):
    def __init__(self,
                 interaction: discord.Interaction,
                 callback: Callable[[Optional[ScheduleEntry]], Awaitable[None]],
                 entry: Optional[ScheduleEntry] = None) -> None:
        """
        Initialize a view for creating/editing a schedule entry.

        Args:
            interaction: The original interaction to edit. (Not the interaction
            requesting this builder).
            callback: The function to call when done editing.
            entry: An existing schedule entry to edit, or None to create a new
            one. Defaults to None.
        """

        super().__init__(interaction, callback)
        self.entry: Optional[ScheduleEntry] = entry

        # If there's an existing entry, use its rule type as the default
        if entry is None or entry.days is None:
            current_rule_str = None
        else:
            current_rule_str = entry.days.rule_type_str()

        # Create/add the menu for picking a Days rule
        # Note that the option strings must correspond with Days.rule_type_str()
        self.menu_rule: ui.Select = self.create_select_menu(
            placeholder='Pick a scheduling rule',
            options=['Days of the week', 'Specific dates', 'Every day'],
            defaults=[current_rule_str],
            callback=self.select_run_rule,
            row=0
        )

        # If the entry already has information, add associated components
        self.components: tuple[Union[ui.Button, ui.Select], ...] = ()

        # Create/add the set_times button
        self.button_set_times: ui.Button = self.create_button(
            label='Set Start/End Times',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            callback=self.click_button_time,
            row=1,
            auto_defer=False
        )

        # Create/add the custom_interval button
        self.button_custom_interval: ui.Button = self.create_button(
            label='Set Custom Interval',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_TIME_INTERVAL,
            callback=self.click_button_interval,
            row=1,
            auto_defer=False
        )

        # Create/add the save button
        self.button_save: ui.Button = self.create_button(
            label='Save',
            style=ButtonStyle.success,
            emoji=settings.EMOJI_SCHEDULE_DONE,
            callback=self.click_button_save,
            row=2
        )

        # Create/add the cancel button
        self.button_cancel: ui.Button = self.create_button(
            label='Cancel',
            style=ButtonStyle.danger,
            emoji=settings.EMOJI_CANCEL,
            callback=self.click_button_cancel,
            row=2
        )

        if entry is not None:
            self.components = self.add_rule_specific_components(entry.days)

    async def build_embed(self) -> Embed:
        if self.entry is None:
            description = ("Schedule when the timelapse should run.\n\nCreate "
                           "a rule to determine which days this entry should "
                           "take effect, and then set a time range to use "
                           "on those days.")
        else:
            description = 'Run the timelapse...'

        # Create the base embed
        embed = utils.default_embed(
            title=f"{'' if self.entry is None else 'Edit '}Schedule Entry",
            description=description
        )

        # Exit now if there's no rule yet
        if self.entry is None:
            return embed

        days = self.entry.days

        # Add info about the days

        if days is not None:
            if isinstance(days, Dates):
                embed.add_field(name='On select dates',
                                value=str(days),
                                inline=False)
            if isinstance(days, DaysOfWeek):
                l = len(days)
                if l == 0:
                    embed.add_field(name='Never',
                                    value='*Select week days below*',
                                    inline=False)
                elif l == 1:
                    embed.add_field(name="Once every week",
                                    value=f"On {days.first_str()}",
                                    inline=False)
                elif l == 2:
                    embed.add_field(name='Twice per week',
                                    value=utils.list_to_str(days),
                                    inline=False)
                elif l == 5 and days.is_weekdays():
                    embed.add_field(name='On weekdays',
                                    value='Monday thru Friday',
                                    inline=False)
                elif l == 7:
                    embed.add_field(name='Every Day',
                                    value='Sunday thru Saturday',
                                    inline=False)
                else:
                    if l >= 5:
                        body = 'Every day except ' + \
                               utils.list_to_str(days.excluded_days())
                    else:
                        body = utils.list_to_str(d.value[2] for d in days)

                    embed.add_field(
                        name=f"{utils.num_to_word(l)} days per week",
                        value=body,
                        inline=False
                    )

        # Add info about the time of day

        body = 'From '
        if self.entry.runs_all_day():
            header = 'All day long'
        elif self.entry.end_time <= time(hour=12):
            header = 'In the morning'
        elif self.entry.start_time >= time(hour=12):
            header = 'In the afternoon'
        else:
            header = 'Going from'
            body = ''

        s = utils.format_time(self.entry.start_time, use_text=True)
        e = utils.format_time(self.entry.end_time, use_text=True)
        body += f"**{s}** to **{e}**"

        embed.add_field(name=header,
                        value=body,
                        inline=False)

        # Add the custom configuration, if present

        config_text = self.entry.get_config_text()
        if config_text is not None:
            embed.add_field(name='Custom Configuration',
                            value=config_text,
                            inline=False)

        # Return the finished embed
        return embed

    def add_rule_specific_components(
            self,
            rule: Days,
            row: int = 1) -> tuple[Union[ui.Button, ui.Select], ...]:
        """
        Create the components used for editing the particular days rule. The
        components are automatically added to the view in the specified row.

        Args:
            rule: The rule to edit with these components.
            row: The row in which to add the components. Defaults to 1.

        Returns:
            A tuple of added components dedicated to the specified rule. These
            are given in the order that they should be added to the view.
        """

        # If there are no active components, that means this is the first time
        # add them. We need to shift a bunch of buttons down one row to make
        # space
        shifted_buttons = None
        if not self.components:
            shifted_buttons = (self.button_set_times,
                               self.button_custom_interval,
                               self.button_save,
                               self.button_cancel)
            self.remove_items(shifted_buttons)
            for btn in shifted_buttons:
                btn.row += 1

        # Use a selection menu for days of the week
        if isinstance(rule, DaysOfWeek):
            menu: ui.Select = self.create_select_menu(
                placeholder='Pick days to run',
                options=[d.name.capitalize() for d in DayOfWeekEnum],
                defaults=[d.name.capitalize() for d in rule],
                no_maximum=True,
                callback=self.select_week_days,
                row=row
            )

            if not self.components:
                self.add_items(shifted_buttons)

            return (menu,)

        # Use a set of buttons for specific dates
        elif isinstance(rule, Dates):
            add: ui.Button = self.create_button(
                label='Add',
                style=ButtonStyle.secondary,
                emoji=settings.EMOJI_ADD_SCHEDULE,
                callback=lambda i: self.click_button_update_dates(i, True),
                row=row,
                auto_defer=False
            )

            remove: ui.Button = self.create_button(
                label='Remove',
                style=ButtonStyle.secondary,
                emoji=settings.EMOJI_REMOVE_SCHEDULE,
                callback=lambda i: self.click_button_update_dates(i, False),
                disabled=len(rule) == 0,
                row=row,
                auto_defer=False
            )

            clear: ui.Button = self.create_button(
                label='Clear',
                style=ButtonStyle.secondary,
                emoji=settings.EMOJI_DELETE,
                callback=self.click_button_clear_dates,
                disabled=len(rule) == 0,
                row=row
            )

            if not self.components:
                self.add_items(shifted_buttons)

            return add, remove, clear

        # Some new unsupported Days type
        raise ValueError(f"Unexpected days rule type {type(rule)}")

    async def select_run_rule(self, _: discord.Interaction) -> None:
        """
        This is the callback for the rule selection menu.

        Change the rule, and update the view accordingly.

        Args:
            _: The interaction that triggered this callback.
        """

        # Track whether the components need to change
        change_components = True
        selection: str = self.menu_rule.values[0]

        if selection == 'Specific dates':
            # Switch to the Dates rule type
            if self.entry is None:
                self.entry = ScheduleEntry(days=Dates())
            elif isinstance(self.entry.days, Dates):
                return
            else:
                self.entry.days = Dates()
        else:
            # Switch to the DaysOfWeek rule type
            every_day = selection == 'Every day'

            if self.entry is None:
                self.entry = ScheduleEntry(days=DaysOfWeek(
                    EVERY_DAY_OF_WEEK if every_day else None
                ))
            elif isinstance(self.entry.days, DaysOfWeek):
                # If already using DaysOfWeek, the only thing to do is add every
                # day if the user chose that option
                change_components = False
                if not every_day:
                    return

            # Replace with new Rules instance that uses either every day or none
            self.entry.days = DaysOfWeek(
                EVERY_DAY_OF_WEEK if every_day else None
            )

            # If the components won't be changed next (i.e. it switched between
            # "Days of the week" and "Every day") make sure the DayOfWeek
            # dropdown menu has the right days selected
            if not change_components:
                utils.set_menu_default(
                    self.components[0],
                    tuple(d.name.capitalize() for d in self.entry.days)  # noqa
                )

        ##################################################

        # Update this menu to keep the selected open chosen
        utils.set_menu_default(self.menu_rule, self.menu_rule.values[0])

        # Replace the rule-specific components if necessary
        if change_components:
            self.remove_items(self.components)
            self.components = self.add_rule_specific_components(self.entry.days)

        # Update the display, as something will have changed (otherwise we
        # would have already returned)
        await self.refresh_display()

    async def set_start_end_time(self,
                                 start_time: time,
                                 end_time: time) -> None:
        """
        Change the start/end times of this entry, and refresh the display. If
        they didn't change, nothing is refreshed. If the entry is currently
        None, one is created.

        Args:
            start_time: The new start time.
            end_time: The new end time.
        """

        if self.entry is None:
            # Create a new schedule entry if there wasn't one
            self.entry = ScheduleEntry(start_time=start_time,
                                       end_time=end_time)
        elif self.entry.start_time == start_time and \
                self.entry.end_time == end_time:
            # No change
            return
        else:
            # At least one change
            self.entry.start_time = start_time
            self.entry.end_time = end_time

        # If reached, something changed
        self.button_set_times.label = 'Change Start/End Time'
        self.button_set_times.emoji = settings.EMOJI_CHANGE_TIME
        await self.refresh_display()

    async def set_capture_interval(self, interval: Optional[int]) -> None:
        """
        Set the new capture interval, a custom configuration for this schedule
        entry. If there is currently no entry, one is created with the default
        settings.

        Args:
            interval: The new capture interval, or None to disable it.
        """

        # If no entry exists, create one with default settings--unless this
        # did not add an interval
        if self.entry is None:
            if interval is None:
                return
            self.entry = ScheduleEntry()

        # Set button label based on whether an interval is present
        if interval is None:
            self.button_custom_interval.label = 'Set Custom Interval'
        else:
            self.button_custom_interval.label = 'Change Custom Interval'

        # Update the display if the interval changes
        if self.entry.set_config_interval(interval):
            await self.refresh_display()

    async def click_button_time(self,
                                interaction: discord.Interaction) -> None:
        """
        This is the callback for the runtime button.

        Send a modal prompting the user to update the start and end times.

        Args:
            interaction: The interaction that triggered this callback.
        """

        # Create the modal with the current values if there are any
        if self.entry is None:
            modal = ScheduleRuntimeModal(self.set_start_end_time)
        else:
            modal = ScheduleRuntimeModal(self.set_start_end_time,
                                         start_time=self.entry.start_time,
                                         end_time=self.entry.end_time)

        # Send the modal. No need to defer, as creating the modal should be fast
        await interaction.response.send_modal(modal)

    async def click_button_interval(self,
                                    interaction: discord.Interaction) -> None:
        """
        This is the callback for the custom interval button.

        Send a modal prompting the user to change the custom capture interval
        for this schedule entry.

        Args:
            interaction: The interaction that triggered this callback.
        """

        await interaction.response.send_modal(ChangeIntervalModal(
            self.set_capture_interval,
            None if self.entry is None else self.entry.get_config_interval()
        ))

    async def click_button_save(self,
                                interaction: discord.Interaction) -> None:
        """
        This is the callback for the "save" button. It runs the primary callback
        for this view, return to the schedule builder and adding the newly
        created entry.

        It is possible that said callback will raise a ValidationError when it
        attempts to add the schedule entry. If that happens, it's caught here
        and sent as a response to this interaction.

        If the callback runs successfully, this view is stopped.

        Args:
            interaction: The interaction that triggered this callback.
        """

        try:
            await self.callback(self.entry)
        except ValidationError as e:
            embed = utils.contrived_error_embed(
                title='Failed to Add Entry',
                text=e.msg
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Close this view
        self.stop()

    async def click_button_cancel(self, _: discord.Interaction) -> None:
        """
        This is the callback for the "cancel" button. It runs the primary
        callback with None, thereby not passing any entry.

        Args:
            _: The interaction that triggered this callback.
        """

        # Close this view
        await self.callback(None)
        self.stop()

    async def select_week_days(self,
                               _: discord.Interaction,
                               menu: ui.Select) -> None:
        """
        This is the callback for the days of the week selection menu.

        Change the selected days of the week, and update the view accordingly.

        Args:
            _: The interaction that triggered this callback.
            menu: The selection menu with the days of the week.
        """

        days: list[DayOfWeekEnum] = [DayOfWeekEnum.from_full_name(n)
                                     for n in menu.values]

        # Don't do anything unless this changes the selection
        entry_days = self.entry.days
        assert isinstance(entry_days, DaysOfWeek)
        if entry_days.eq_days(days):
            return

        # If all 7 days are currently selected, then this is going to de-select
        # some of them. In that case, change the rule selector from "Every day"
        # to "Days of the week"
        if len(entry_days) == 7:
            utils.set_menu_default(self.menu_rule, 'Days of the week')

        # Update the entry with new rule
        self.entry.days = DaysOfWeek(days)

        # If all 7 days are selected now, change rule selector to "Every day"
        if len(entry_days) == 7:
            utils.set_menu_default(self.menu_rule, 'Every day')

        # Make sure the currently selected values stay selected
        utils.set_menu_default(menu, menu.values)

        # Refresh to display changes to user
        await self.refresh_display()

    async def click_button_update_dates(self,
                                        interaction: discord.Interaction,
                                        add: bool) -> None:
        """
        This is the callback for the add button for specific dates.

        Open a modal prompting the user to enter a list of specific dates.

        Args:
            interaction: The interaction that triggered this callback.
            add: Whether the user wants to add dates (True) or remove them
            (False).
        """

        # Define the callback function
        async def update_dates(dates: list[date], _add: bool):
            # Update the dates
            days = self.entry.days
            assert isinstance(days, Dates)
            self.entry.days = days.add(dates) if _add else days.remove(dates)

            # Disable/enable buttons based on how many dates there are
            l = len(self.entry.days)  # noqa
            self.components[0].disabled = l == Dates.MAX_ALLOWED_DATES
            self.components[1].disabled = l == 0
            self.components[2].disabled = l == 0

            await self.refresh_display()

        # Create and send the modal for adding dates
        await interaction.response.send_modal(SpecificDatesModal(
            update_dates, add
        ))

    async def click_button_clear_dates(
            self, interaction: discord.Interaction) -> None:
        """
        This is the callback for the clear button for specific dates.

        Clear all the selected dates.

        Args:
            interaction: The interaction that triggered this callback.
        """

        days = self.entry.days
        assert isinstance(days, Dates)

        if len(days) == 0:
            # This should be unreachable
            _log.warning('Unreachable: clearing dates when there are none')
            await interaction.followup.send(
                content="There aren't any dates to clear. Add dates to "
                        "specify when this rule should apply.",
                ephemeral=True
            )
            return

        # Clear dates, and update the display
        self.entry.days = Dates()
        self.components[0].disabled = False
        self.components[1].disabled = True
        self.components[2].disabled = True
        await self.refresh_display()


class ScheduleBuilder(BaseView, TracksChanges):
    def __init__(self,
                 interaction: discord.Interaction,
                 start_time: Optional[datetime],
                 end_time: Optional[datetime],
                 total_frames: Optional[int],
                 schedule: Optional[Schedule],
                 callback: Callable[
                     [Optional[datetime], Optional[datetime],
                      Optional[int], Optional[Schedule]],
                     Awaitable
                 ],
                 cancel_callback: Callable[[], Awaitable]) -> None:
        """
        Initialize a ScheduleBuilder, a view used to construct and edit a
        timelapse Schedule.

        Args:
            interaction: The interaction to edit with this view.
            start_time: The current overall runtime start.
            end_time: The current overall runtime end.
            total_frames: The current total frame threshold for ending.
            schedule: An existing schedule, if one exists. Defaults to None.
            callback: An async function to call to save the updated schedule
            configuration. It accepts the new start time, end time, total
            frames, and schedule.
            cancel_callback: An async function to call if this is cancelled. It
            doesn't save any changes.
        """

        super().__init__(interaction, callback, cancel_callback)

        # Set the initial schedule, making a new one if necessary
        schedule = Schedule() if schedule is None else schedule
        self.schedule: ChangeTracker[Schedule] = ChangeTracker(schedule)

        # Overall runtime conditions. Track changes
        self.start_time: ChangeTracker[Optional[datetime]] = \
            ChangeTracker(start_time)
        self.end_time: ChangeTracker[Optional[datetime]] = \
            ChangeTracker(end_time)
        self.total_frames: ChangeTracker[Optional[int]] = \
            ChangeTracker(total_frames)

        # Create the buttons
        self.button_save = self.create_button(
            label='Save',
            style=ButtonStyle.success,
            emoji=settings.EMOJI_SCHEDULE_DONE,
            disabled=True,  # No changes have been made yet
            row=0,
            callback=lambda _: self.select_button_save()
        )

        self.button_info = self.create_button(
            label='Info',
            style=ButtonStyle.primary,
            emoji=settings.EMOJI_INFO,
            row=0,
            callback=self.select_button_info
        )

        self.button_cancel = self.create_button(
            label='Cancel',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CANCEL,
            row=0,
            callback=lambda _: self.run_cancel_callback()
        )

        self.button_add = self.create_button(
            label='Add',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_ADD_SCHEDULE,
            row=1,
            callback=lambda _: self.select_button_add()
        )

        self.button_edit = self.create_button(
            label='Edit',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_EDIT_SCHEDULE,
            disabled=len(self.schedule.current) == 0,
            row=1,
            callback=lambda i: self.select_button_entry(i, 'edit')
        )

        self.button_move = self.create_button(
            label='Move',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_MOVE,
            disabled=len(self.schedule.current) < 2,
            row=1,
            callback=lambda i: self.select_button_entry(i, 'move')
        )

        self.button_remove = self.create_button(
            label='Remove',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_REMOVE_SCHEDULE,
            disabled=len(self.schedule.current) == 0,
            row=1,
            callback=lambda i: self.select_button_entry(i, 'remove')
        )

        self.button_runtime = self.create_button(
            label='Set Overall Runtime',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            row=2,
            callback=lambda i: i.response.send_modal(ChangeRuntimeModal(
                self.start_time.current,
                self.end_time.current,
                self.total_frames.current,
                self.set_runtime
            )),
            auto_defer=False
        )

        # Use "Change Overall Runtime" if any of the runtime parameters are set
        self.update_runtime_button()

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
        Construct an embed with the info about this schedule. This embed is
        associated with the buttons in this view.

        Returns:
            The embed.
        """

        # Get runtime info
        runtime_text = timelapse_utils.generate_embed_runtime_text(
            self.start_time.current,
            self.end_time.current,
            self.total_frames.current
        )

        # Add a message about the schedule below (in the embed fields)
        if len(self.schedule.current) == 0:
            msg = 'Add entries below to build the timelapse schedule.'
        elif len(self.schedule.current) == 1:
            msg = 'The schedule is defined as follows:'
        else:
            msg = 'The schedule is applied in the following order:'

        # Create the base embed
        embed = utils.default_embed(
            title='Timelapse Schedule Editor',
            description=f'### Overall Runtime\n{runtime_text}\n\n{msg}'
        )

        # Add a field for each schedule entry
        for index, entry in enumerate(self.schedule.current):
            header, body = entry.get_embed_field_strings()
            embed.add_field(
                name=f'{index + 1}. {header}',
                value=body,
                inline=False
            )

        # Return the fully constructed embed
        return embed

    def has_changed(self) -> bool:
        return self.start_time.has_changed() or \
            self.end_time.has_changed() or \
            self.total_frames.has_changed() or \
            self.schedule.has_changed()

    async def set_runtime(self,
                          start_time: Optional[datetime],
                          end_time: Optional[datetime],
                          total_frames: Optional[int]) -> None:
        """
        Set new runtime parameters. If anything changed, refresh the display.

        Args:
            start_time: The new start time.
            end_time:  The new end time.
            total_frames:  The new total frame threshold.
        """

        # Update all values
        start = self.start_time.update(start_time)
        end = self.end_time.update(end_time)
        frames = self.total_frames.update(total_frames)

        if start or end or frames:
            # If any of the values changed, recalculate whether the "Save"
            # button should be enabled and "Cancel" turned red. Also update
            # the runtime button. Then refresh the display
            self.update_save_cancel_buttons()
            self.update_runtime_button()
            await self.refresh_display()

    def update_save_cancel_buttons(self) -> None:
        """
        Check whether the current schedule settings are different from their
        initial values. If so, the Save button should be enabled, and Cancel
        should be red. Otherwise, Save should be disabled, and Cancel should
        be gray.

        This does NOT refresh the display.
        """

        if self.has_changed():
            self.button_save.disabled = False
            self.button_cancel.style = ButtonStyle.danger
        else:
            self.button_save.disabled = True
            self.button_cancel.style = ButtonStyle.secondary

    def update_runtime_button(self) -> None:
        """
        Set the overall runtime button to either "Set Overall Runtime" or
        "Change Overall Runtime" based on whether the start time, end time, or
        total frames have been set.
        """
        if self.start_time is not None or self.end_time is not None or \
                self.total_frames is not None:
            self.button_runtime.label = 'Change Overall Runtime'
            self.button_runtime.emoji = settings.EMOJI_CHANGE_TIME
        elif self.start_time is None and self.end_time is None and \
                self.total_frames is None:
            self.button_runtime.label = 'Set Overall Runtime'
            self.button_runtime.emoji = settings.EMOJI_SET_RUNTIME

    async def select_button_save(self) -> None:
        """
        The callback function for the "Save" button. It runs the main callback
        function, passing the new start time, end time, total frames, and
        schedule.

        Then stop() this view, as it'll be replaced by the calling view.
        """

        # Save changes
        await self.callback(
            self.start_time.current,
            self.end_time.current,
            self.total_frames.current,
            self.schedule.current
        )

        # Stop this view
        self.stop()

    @staticmethod
    async def select_button_info(interaction: discord.Interaction) -> None:
        """
        Callback for the "Info" button. Show info about timelapse schedules.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Acknowledge
        await interaction.followup.send(content='Info!', ephemeral=True)

    async def select_button_add(self) -> None:
        """
        Create and add a new entry to the schedule.
        """

        # Define the callback function
        async def callback(entry: Optional[ScheduleEntry]) -> None:
            if entry is not None:
                self.schedule.current.add_entry(entry)

            # There's at least one entry now: enable the editing buttons
            self.button_edit.disabled = self.button_remove.disabled = False
            self.button_move.disabled = len(self.schedule.current) < 2
            self.update_save_cancel_buttons()
            await self.refresh_display()

        # Send a view for making a new entry
        await ScheduleEntryBuilder(self.interaction, callback).refresh_display()

    async def select_button_entry(
            self,
            interaction: discord.Interaction,
            mode: Literal['edit', 'move', 'remove']) -> None:
        """
        Open a view prompting the user to select an entry from the schedule so
        that it can be either edited or removed.

        Args:
            interaction: The interaction that triggered this UI event.
            mode: Whether to 'edit', 'move', or 'remove' the selected entry.
        """

        # If there aren't any entries, send an error
        count = len(self.schedule.current)
        if count == 0:
            _log.warning(f"Unreachable: user clicked the button to {mode} an "
                         "entry, but there aren't any")
            embed = utils.contrived_error_embed(
                title=f'Error: Nothing to {mode.capitalize()}',
                text=f"There are no schedule entries to {mode}. "
                     f"You can create one by clicking 'Add'.",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If there's only one entry, edit/remove it
        if count == 1:
            if mode == 'move':
                # Can't move unless there are at least 2 entries
                _log.warning(f"Unreachable: user clicked the button to move "
                             "an entry, but there's only one")
                embed = utils.contrived_error_embed(
                    title="Error: Can't Move",
                    text="There's only one schedule entry, so there's nowhere "
                         "to move it. You can remove this entry by clicking "
                         "'Remove'.",
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # (Stupid type checker; mode can't be 'move' here)
                # noinspection PyTypeChecker
                await self.entry_button_callback(mode, 0)

            return

        # Cancel callback function
        async def cancel_callback():
            self.update_save_cancel_buttons()
            await self.refresh_display()

        # There are multiple entries. Create and send a selector to pick one
        await ScheduleEntrySelector(
            self.interaction,
            self.schedule.current,
            mode,
            self.entry_button_callback,  # This is never used in 'move' mode
            cancel_callback
        ).refresh_display()

    async def entry_button_callback(self,
                                    mode: Literal['edit', 'remove'],
                                    index: int) -> None:
        """
        This is the callback for the ScheduleEntrySelector in 'edit' and
        'remove' mode.

        Args:
            mode: Whether the user wants to edit or remove an entry.
            index: The index of the selected entry.
        """

        if mode == 'edit':
            async def callback(_):
                self.update_save_cancel_buttons()
                await self.refresh_display()

            await ScheduleEntryBuilder(
                self.interaction,
                callback,
                self.schedule.current.entries[index]
            ).refresh_display()
        elif mode == 'remove':
            # Remove the selected entry
            self.schedule.current.remove_entry(index)

            # If there aren't any entries now, disable editing buttons
            if len(self.schedule.current) == 0:
                self.button_edit.disabled = self.button_remove.disabled = True

            # Move button requires at least 2 entries
            self.button_move.disabled = len(self.schedule.current) < 2

            # Update the display
            self.update_save_cancel_buttons()
            await self.refresh_display()
        else:
            raise ValidationError("Invalid mode for selection entry; expected "
                                  f"'edit' or 'remove'; got '{mode}'")
