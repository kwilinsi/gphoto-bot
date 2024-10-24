from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from typing import Optional

from gphotobot import const, utils
from gphotobot.sql import ScheduleEntry as SQLScheduleEntry
from .change_tracker import ChangeTracker, TracksChanges
from .days import Days
from .days_of_week import DaysOfWeek


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
                 index: int,
                 days: Days | None = None,
                 start_time: time = MIDNIGHT,
                 end_time: time = ELEVEN_FIFTY_NINE,
                 config: Optional[dict[str, any]] = None,
                 db_record: SQLScheduleEntry | None = None):
        """
        Initialize an entry for a schedule.

        Args:
            index: The index of this entry within the schedule.
            days: The day (or days) this applies. If None, this defaults to
            every day of the week. Defaults to None.
            start_time: The time of day this rule starts. Defaults to midnight.
            end_time: The time of day this rule ends. Defaults to 11:59:59 p.m.
            config: Timelapse configuration specific to this schedule entry.
            db_record: An optional database record to associated with this
            entry.
        """

        # Schedule entry attributes
        self._index: ChangeTracker[int] = ChangeTracker(index)
        self._days: ChangeTracker[Days] = ChangeTracker(
            DaysOfWeek.every_day() if days is None else days
        )
        self._start_time: ChangeTracker[time] = ChangeTracker(start_time)
        self._end_time: ChangeTracker[time] = ChangeTracker(end_time)
        self._config: ChangeTracker[dict[str, any]] = ChangeTracker(
            {} if config is None else config
        )

        # Optional database record if this was made from an existing db entry
        self._db_record: SQLScheduleEntry | None = db_record

    @classmethod
    def from_db(cls, record: SQLScheduleEntry) -> ScheduleEntry:
        """
        Construct a new schedule entry from a database record.

        Args:
            record: A SQL database record.

        Returns:
            A new schedule entry.
        """

        return cls(
            index=record.index,
            days=Days.create_rule_from_db(record.days),
            start_time=record.start_time,
            end_time=record.end_time,
            config=cls.config_from_db(record.config),
            db_record=record
        )

    @property
    def index(self) -> int:
        return self._index.current

    @index.setter
    def index(self, i: int) -> None:
        self._index.update(i)

        # Update db entry if present
        if self.db_record is not None:
            self.db_record.index = i

    @property
    def days(self) -> Days:
        return self._days.current

    @days.setter
    def days(self, d: Days) -> None:
        self._days.update(d)

        # Update db entry if present
        if self.db_record is not None:
            self.db_record.days = d.to_db()

    @property
    def start_time(self) -> time:
        return self._start_time.current

    @start_time.setter
    def start_time(self, t: time) -> None:
        self._start_time.update(t)

        # Update db entry if present
        if self.db_record is not None:
            self.db_record.start_time = t

    @property
    def end_time(self) -> time:
        return self._end_time.current

    @end_time.setter
    def end_time(self, t: time) -> None:
        self._end_time.update(t)

        # Update db entry if present
        if self.db_record is not None:
            self.db_record.end_time = t

    @property
    def config(self) -> dict[str, any]:
        return self._config.current

    def set_config_entry(self, key: str, value: any) -> bool:
        """
        Add the specified key/value pair to the config dict.

        Args:
            key: The key to add.
            value: The value to pair with the key.

        Returns:
            True if and only if something changed. False if the key was already
            paired with the given value in the config dict.
        """

        cfg = self._config.current

        # Make sure the key isn't already paired with this value
        if key not in cfg or cfg[key] != value:
            cfg[key] = value

            # Update db entry if present
            if self.db_record is not None:
                self.db_record.config = self.config_to_db()

            return True

        # Nothing changed; the key was already paired with that value
        return False

    def delete_config_entry(self, key: str) -> bool:
        """
        Remove the specified key and its associated value from the config
        dict.

        Args:
            key: The key to remove.

        Returns:
            True if and only if the key was removed.
        """

        cfg = self._config.current

        # Make sure the key is in there first
        if key in cfg:
            del cfg[key]

            # Update db entry if present
            if self.db_record is not None:
                self.db_record.config = self.config_to_db()

            return True

        # Nothing changed; key wasn't in the config to begin with
        return False

    @property
    def db_record(self) -> SQLScheduleEntry | None:
        return self._db_record

    def __str__(self):
        """
        Get a string with some basic information about this schedule entry. This
        tries to be reasonably succinct. The output format looks something like
        this:

        "entry(Mon/Wed; 4–8:30 PM; 1cfg)"

        Returns:
            A string with basic info.
        """

        start = utils.format_time(self.start_time)
        end = utils.format_time(self.end_time)

        # If the start and end are on the same side of the meridian, remove
        # the meridiem indicator (i.e. AM/PM)
        if start[-2:] == end[-2:]:
            start = start[:-2].replace(' ', '')

        return (f'entry({self.days.str_shortest()}; '
                f'{start}–{end}; {len(self.config)}cfg)')

    def __eq__(self, other):
        if type(self) == type(other):
            return self.days == other.days and \
                self.start_time == other.start_time and \
                self.end_time == other.end_time and \
                self.config == other.config

        return NotImplemented

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

        header, has_all_info = self.days.str_header()

        body = (f"From **{utils.format_time(self.start_time, use_text=True)}** "
                f"to **{utils.format_time(self.end_time, use_text=True)}**")

        # If missing some info in header, add it to the time range
        if not has_all_info:
            body = '(' + self.days.str_long(75) + ')\n' + body

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
                l = len(self.config)
                config = f"*Plus {l} configuration{'' if l == 1 else 's'}*"
                if len(config) > available_chars:
                    return header, body + '\n…'
            else:
                # Remove the last line
                trimmed += 1
                config = config[:index]

        return header, body + '\n' + config

    def get_config_text(self) -> str | None:
        """
        Get text for an embed that lists the config options. If there are no
        custom config settings for this schedule entry, it returns None.

        Returns:
            The config options, or None.
        """

        if not self.config:
            return None

        text = ''
        for key, value in self.config.items():
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

        return self.start_time == self.MIDNIGHT and self.ends_at_midnight()

    def set_config_interval(self, interval: timedelta | None) -> bool:
        """
        Set a config entry for a custom capture interval.

        Args:
            interval: The new interval. If this is None, any existing entry is
            removed.

        Returns:
            A boolean indicating whether anything changed.
        """

        if interval is None:
            return self.delete_config_entry('capture_interval')
        else:
            return self.set_config_entry('capture_interval', interval)

    def get_config_interval(self) -> timedelta | None:
        """
        Get the config entry for a custom capture interval, if one has been set.

        Returns:
            The capture interval, or None if not set.
        """

        return self.config.get('capture_interval', None)

    def config_to_db(self) -> str | None:
        """
        Get a string that contains the config record ready for use in the
        database. This must be reversible with config_from_db(). Ideally, this
        is human-readable for someone accessing the database.

        Returns:
            A string storing the config information, or None if self.config is
            None or empty.
        """

        if not self.config:
            return None

        str_mapping: dict[str, str] = {}

        # Build the string with one entry at a time
        for key, value in self.config.items():
            # Add the value based on what key it is, as values will have
            # different data types
            if key == 'capture_interval':
                str_mapping[key] = utils.format_duration(value)
            elif isinstance(value, str):
                # Some other string
                str_mapping[key] = (value.encode('unicode_escape')
                                    .decode("utf-8"))
            else:
                # Some other value. This probably should never be reached
                str_mapping[key] = (repr(value).encode('unicode_escape')
                                    .decode("utf-8"))

        return '\n'.join(f"{k}: {v}" for k, v in str_mapping.items())

    @staticmethod
    def config_from_db(config_str: str | None) -> Optional[dict[str, any]]:
        """
        Given a string created with config_to_db() that encodes the custom
        configuration for a schedule entry in the database, parse it into a
        config dict.

        Args:
            config_str: The database config string to parse.

        Returns:
            The parsed config dictionary, or None if the input string is None.
        """

        if not config_str:
            return None

        config = {}
        for line in config_str.split('\n'):
            key, value = line.split(': ', 1)

            if key == 'capture_interval':
                # capture_interval is a timedelta
                config[key] = utils.parse_time_delta(value)
            else:
                # Some other value
                config[key] = value.encode('utf-8').decode('unicode_escape')

        return config

    def to_db(self,
              timelapse_id: int | None = None,
              force_copy: bool = False) -> SQLScheduleEntry:
        """
        Convert this schedule entry to a record that can be added to the
        database.

        If this entry is already associated with a record, the existing record
        is returned.

        Args:
            timelapse_id: The id of the timelapse to which this schedule entry
            is attached. This is optional. Defaults to None.
            force_copy: Whether to create a new database record even if there's
            an existing one. Defaults to False.

        Returns:
            A database record for this entry.
        """

        # Use existing record if present
        if self.db_record is not None:
            return deepcopy(self.db_record) if force_copy else self.db_record

        # Otherwise, make a new one
        return SQLScheduleEntry(
            timelapse_id=timelapse_id,
            index=self.index,
            start_time=self.start_time,
            end_time=self.end_time,
            days=self.days.to_db(),
            config=self.config_to_db()
        )

    def ends_at_midnight(self) -> bool:
        """
        Check whether the end time for this schedule entry is effectively
        midnight. Technically, it can't be exactly the base time() with 0 hours,
        0 minutes, and 0 seconds (only the start time can exactly equal
        midnight). But if the end time is within one second of midnight, that's
        considered effectively midnight.

        This is important because if the end time is midnight, then this entry
        does not stop at the end of the day: it goes straight on to the next
        day. And if it also starts at midnight, then, this schedule entry may
        apply 24/7 or overnight.

        Returns:
            True if and only if the end time is in the range
            [23:59:59, 00:00:00).
        """

    def is_active_at(self, dt: datetime) -> bool:
        """
        Check whether this scheduling rule applies at the given date/time. If
        this exactly matches when the rule starts, this returns True. If it
        exactly matches the time this rule ends, this returns False.

        Args:
            dt: The date/time to check.

        Returns:
            True if and only if this rule is in effect at the given time.
        """

        t = dt.time()
        return self.days.does_run_on(dt) and \
            self.start_time <= t and \
            (self.ends_at_midnight() or t < self.end_time)

    def next_event_after(self, dt: datetime) -> tuple[Optional[datetime], bool]:
        """
        Determine the next time that this entry will either become active or
        cease being active, after the given datetime.

        For example, say this rule applies from 8 a.m. to 5 p.m. on Mondays,
        and you pass the datetime "2024-10-21 12:00 p.m.", which is noon on
        a Monday. This will return ("2024-10-21 5 p.m.", False), meaning that
        at 5 p.m. on 2024-10-21, this entry is no longer active.

        If you passed "2024-10-28 5 a.m.", which is 5 a.m. on the following
        Monday, this will return ("2024-10-28 8 a.m.", True), which is the
        next time that it *becomes* active. (Note that this returns actual
        datetime objects, not strings).

        If this entry never changes state again, the datetime is None. And the
        boolean indicates whether it would become active/inactive if it *did*
        change (though it won't). That is, it'll return (None, False) if it'll
        never turn off and (None, True) if it'll never turn on.

        Args:
            dt: The date time to start from. The returned time is always AFTER
            this time (never equal to it).

        Returns:
            The next datetime that this schedule entry changes state, along with
            a boolean indicating whether it becomes active (True) or inactive
            (False). Or, if it never changes state, then None (no time), and
            a boolean indicating what state it *would* change to if it did
            change.
        """

        # (Note: in these comments, by "now"/"today" I mean the value of `dt`).

        # First, determine whether it's active today and/or right now
        d, t = dt.date(), dt.time()
        runs_today: bool = self.days.does_run_on(d)
        runs_now: bool = runs_today and self.start_time <= t and \
                         (self.ends_at_midnight() or t < self.end_time)

        # If it runs today, see whether it's going to start/end soon
        if runs_today:
            # Check if it hasn't started yet
            if t < self.start_time:
                return datetime.combine(d, self.start_time), True

            # Check if it's running now
            if runs_now:
                # If it runs all day long, then it'll stop running at midnight
                # on the next day the Days rule changes
                if self.runs_all_day():
                    next_change: Optional[date] = self.days.next_event_after(d)
                    if next_change is None:
                        return None, False  # It'll never turn off
                    else:
                        # It'll turn off at midnight on the earliest day that
                        # the rule no longer takes effect
                        return (datetime.combine(next_change, self.MIDNIGHT),
                                False)
                else:
                    # Otherwise it'll stop today at the end time
                    return datetime.combine(d, self.end_time), False

        # At this point, we know it's not currently running. So it'll start
        # running at the start_time on the first day it takes effect again
        next_change: Optional[date] = self.days.next_event_after(d)
        if next_change is None:
            return None, True  # It'll never turn on
        else:
            return datetime.combine(next_change, self.start_time), True
