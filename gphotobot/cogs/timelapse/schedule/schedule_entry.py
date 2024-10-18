from datetime import time, timedelta
from typing import Optional

from gphotobot.utils import const, utils
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
                 days: Optional[Days] = None,
                 start_time: time = MIDNIGHT,
                 end_time: time = ELEVEN_FIFTY_NINE,
                 config: Optional[dict[str, any]] = None):
        """
        Initialize an entry for a schedule.

        Args:
            days: The day (or days) this applies. If None, this defaults to
            every day of the week. Defaults to None.
            start_time: The time of day this rule starts. Defaults to midnight.
            end_time: The time of day this rule ends. Defaults to 11:59:59 p.m.
            config: Timelapse configuration specific to this schedule entry.
        """

        self._days: ChangeTracker[Days] = ChangeTracker(
            DaysOfWeek.every_day() if days is None else days
        )
        self._start_time: ChangeTracker[time] = ChangeTracker(start_time)
        self._end_time: ChangeTracker[time] = ChangeTracker(end_time)
        self._config: ChangeTracker[dict[str, any]] = ChangeTracker(
            {} if config is None else config
        )

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

    @property
    def config(self) -> dict[str, any]:
        return self._config.current

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

    def get_config_text(self) -> Optional[str]:
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
            if 'capture_interval' in self.config:
                del self.config['capture_interval']
                return True
        elif self.get_config_interval() != interval:
            self.config['capture_interval'] = interval
            return True

        # Nothing changed
        return False

    def get_config_interval(self) -> Optional[timedelta]:
        """
        Get the config entry for a custom capture interval, if one has been set.

        Returns:
            The capture interval, or None if not set.
        """

        return self.config.get('capture_interval', None)
