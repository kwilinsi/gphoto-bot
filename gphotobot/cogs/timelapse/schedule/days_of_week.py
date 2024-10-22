from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Optional

from gphotobot.utils import utils
from gphotobot.utils.days_of_week import (EVERY_DAY_OF_WEEK, WEEK_DAYS,
                                          WEEKENDS, DayOfWeek as DayEnum)
from .days import Days


class DaysOfWeek(set[DayEnum], Days):
    def __init__(self, days: Iterable[DayEnum] = ()):
        """
        Initialize a DaysOfWeek rule set with zero or more days of the week.

        Args:
            days: Zero or more day of the week. Duplicates are ignored. Defaults
            to an empty tuple.
        """

        super().__init__(days)

    @classmethod
    def every_day(cls) -> DaysOfWeek:
        return DaysOfWeek(EVERY_DAY_OF_WEEK)

    def __repr__(self):
        """
        This representation uses the single letter abbreviations of each day
        of the week to construct a string for this object.

        This is designed to be easily parsed.

        Returns:
            "DaysOfWeek([abbreviations])"
        """

        return self.__class__.__name__ + \
            '(' + self.single_letter_abbreviations() + ')'

    def __eq__(self, other):
        if type(other) is type(self):
            return super().__eq__(other)

        return NotImplemented

    #################### DAYS METHOD IMPLEMENTATIONS ####################

    # to_db alis for repr()
    to_db = __repr__

    @classmethod
    def from_db(cls, string: str) -> DaysOfWeek:
        return cls(DayEnum.from_abbr(d) for d in string[11:-1].upper())

    def str_rule(self) -> str:
        return 'Every day' if len(self) == 7 else 'Days of the week'

    def str_shortest(self) -> str:
        # For 0 days, use *N/A* as required
        if len(self) == 0:
            return self.UNDEFINED

        # For 1-2 days, use three letter abbreviations for readability
        if len(self) <= 2:
            return '/'.join(d.abbreviation for d in self)

        # For 3-4 days, use single letter with slashes for readability
        if len(self) <= 4:
            return '/'.join(d.letter for d in self)

        # For 5-7 days, just use single letters
        return self.single_letter_abbreviations()

    def str_header(self) -> tuple[str, bool]:
        """
        Get a user-friendly string listing the days of the week included in this
        set. It uses one of the following formats based on the number of days
        it contains:

        0 Days: `self.UNDEFINED`.

        1 Day: The full name of the day.
            - "Monday"

        2 Days: The abbreviated names with an ampersand. Or, if the days are
        Saturday and Sunday, then the string "Weekends".
            - "Tue & Sat"
            - "Weekends"

        3-6 Days: Abbreviations with ampersand and commas. Ranges of 3+ days are
        combined with an en dash and put first in the list. Or, if this is the
        five weekdays, then the string "Weekdays".
            - "Wed, Fri, & Sat"
            - "Mon, Tue, Thu, & Fri"
            - "Mon–Wed & Thur"
            - "Sat–Mon, Wed, & Thu"
            - "Sun–Fri"
            - "Weekdays"

        7 Days: "Every day"

        Returns:
            A short, string representation of the days of the week, and the
            boolean True (indicating that this header contains all the
            information about the rule).
        """

        if len(self) == 0:
            return self.UNDEFINED, True
        elif len(self) == 1:
            return next(iter(self)).name, True
        elif len(self) == 2:
            return ' & '.join(d.abbreviation for d in sorted(self)), True
        elif len(self) == 7:
            return "Every day", True

        # From here on, there are 3-6 days
        day_range, other_days = self.group_by_range()

        # Convert all the abbreviated names, joining them into one
        # comma-separated string
        day_range = ((day_range[0].abbr + '–' + day_range[1].abbr,)
                     if day_range else ())
        return utils.list_to_str(
            day_range + tuple(d.abbreviation for d in other_days)
        ), True

    def str_long(self, max_len: Optional[int],
                 use_abbreviations: bool = False) -> str:
        """
        Get a long-form string representation of this rule.

        Args:
            max_len: The max allowed length. This is implemented somewhat
            half-heartily. If the length is exceeded, this calls itself again
            with use_abbreviations turned on. If it's still too long, it uses
            the output of str_shortest(). If None, this is ignored. Defaults to
            None.
            use_abbreviations: Whether to abbreviate where possible: using
            three-letter name abbreviations for days of the week, an ampersand
            (&) instead of "and", and an en dash instead of "to" or "through".
            Defaults to False.

        Returns:
            A long form string representation of this rule.
        """

        # Helper function to catch and shorten strings that are too long
        def return_str(s: str) -> str:
            if max_len is None or len(s) <= max_len:
                return s
            elif use_abbreviations:
                return self.str_shortest()
            else:
                return self.str_long(max_len, True)

        # Helper function to get name or abbreviation based on the setting
        def name(d: DayEnum) -> str:
            return d.abbreviation if use_abbreviations else d.name

        # Test simple cases with 0–2, 6, or 7 days
        if len(self) == 0:
            return return_str(self.UNDEFINED)
        elif len(self) <= 2:
            return return_str(
                (' & ' if use_abbreviations else ' and ')
                .join(name(d) for d in sorted(self))
            )
        elif len(self) == 6:
            return return_str("Every day except " +
                              name(self.excluded_days()[0]))
        elif len(self) == 7:
            return return_str("Sun–Sat" if use_abbreviations
                              else "Sunday through Saturday")

        # From here on, there are 3-5 days
        day_range, other_days = self.group_by_range()

        # Convert all the days to their full names, joining them into one
        # comma-separated string
        day_range = (name(day_range[0]) +
                     ('–' if use_abbreviations else ' to ') +
                     name(day_range[1]),) if day_range else ()
        return return_str(utils.list_to_str(
            day_range +
            tuple(name(d) for d in other_days)
        ))

    def runs_exactly_once(self) -> bool:
        # This is always False, because it either applies never or at least
        # once per week
        return False

    def does_ever_run(self) -> bool:
        return len(self) > 0

    def does_run_on(self, d: date | datetime) -> bool:
        # Convert d to a date (if it's a datetime), and get .weekday(), an
        # int from 0 to 6. Then compare to the indices of the days in this rule
        return (d.date() if isinstance(d, datetime) else d).weekday() \
            in tuple(day.index for day in self)

    def next_event_after(self, d: date | datetime) -> Optional[date]:
        if len(self) == 7 or len(self) == 0:
            return None  # Never changes if this includes every day or no days

        # Get the day of the week for the given date
        weekday: DayEnum = DayEnum.from_index(
            (d.date() if isinstance(d, datetime) else d).weekday()
        )
        contained: bool = weekday in self

        # Find the next date where the state changes
        while weekday in self == contained:
            weekday = weekday.next_day()
            d += timedelta(days=1)

        return d

    #################### EXTRA FUNCTIONS ####################

    def single_letter_abbreviations(self) -> str:
        """
        Get a string containing the single letter abbreviations of each day
        in this rule. For example, "MWF" or "MTWRFSU". If there are no days,
        this is an empty string.

        This is used by __repr__() to store this rule in the database.

        Returns:
            A string with the single letter abbreviation for each day.
        """

        return ''.join(d.letter for d in sorted(self))

    def group_by_range(self) -> \
            tuple[Optional[tuple[DayEnum, DayEnum]], list[DayEnum]]:
        """
        Take all the days in this set, and look for a range of 3 or more
        consecutive days. (There can't be more than one).

        Then return a tuple with two elements: first, the range of consecutive
        days, if one exists. This is a tuple with the first and last days in
        that range. Second, a list of all the other days that are not part of
        the range but are included in this set.

        This function assumes as a precondition that there are between 3 and 6
        days in this DaysOfWeek set.

        Returns:
            A range of days (if one exists), and all the other included days.

        Raises:
            AssertionError: If there are not between 3 and 6 days in this set.
        """

        # Sort the days in this set
        days: list[DayEnum] = sorted(self)
        n: int = len(days)
        assert 3 <= n <= 6

        # Find the longest range of consecutive days, if there is one
        start = end = 0
        longest: tuple[int, int] = (0, 0)

        # Loop over the list twice to catch wraparound ranges (e.g. Sat-Tue)
        for i in range(1, n * 2):
            if days[end % n].next_day() == days[i % n]:
                end = i
                continue
            elif end - start >= 2:
                if end - start > longest[1] - longest[0]:
                    longest = (start, end)
                if i >= n:
                    break  # no more ranges possible when starting
            start = end = i

        if end - start >= max(2, longest[1] - longest[0]):
            longest = (start, end)

        # Return the output, based on whether there's a range
        if longest == (0, 0):
            return None, days
        else:
            other = [days[i % n] for i in range(longest[1] + 1, n + longest[0])]
            return (days[longest[0] % n], days[longest[1] % n]), other

    def descriptive_header(self) -> str:
        """
        Get a string that describes this rule without actually naming the days
        of the week that it includes. Instead, it uses phrases like "Twice per
        week" and "On weekends".

        This is designed for use in an embed field where the value is determined
        by another one of the str() functions.

        Returns:
            A string describing this rule.
        """

        n = len(self)
        if n == 0:
            return 'Never'
        elif n == 1:
            return 'Once every week'
        elif n == 2:
            return 'On weekends' if self == WEEKENDS else 'Twice per week'
        elif n == 5 and self == WEEK_DAYS:
            return 'On weekdays'
        elif n == 7:
            return 'Every day'
        else:
            return f'{utils.num_to_word(n)} days per week'

    def excluded_days(self) -> list[DayEnum]:
        """
        Get the days of the week not included in this rule.

        Returns:
            A list of days (in order).
        """

        return sorted(EVERY_DAY_OF_WEEK - self)
