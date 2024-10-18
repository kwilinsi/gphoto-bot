from __future__ import annotations

from enum import Enum
from functools import total_ordering


@total_ordering
class DayOfWeek(Enum):
    """
    Enum for each day of the week that associates them with a particular letter.

    I made my own enum for the calendar days because I want a particular order
    with one- and three-letter abbreviations for each day.
    """

    # Index (sorting order), single letter abbreviation, short name

    # As painful as it is, I'm starting the week with Monday because I think
    # the abbreviation MTWRFSU is slightly faster to understand than UMTWRFS
    Monday = (0, 'M', 'Mon')
    Tuesday = (1, 'T', 'Tue')
    Wednesday = (2, 'W', 'Wed')
    Thursday = (3, 'R', 'Thur')
    Friday = (4, 'F', 'Fri')
    Saturday = (5, 'S', 'Sat')
    Sunday = (6, 'U', 'Sun')

    @property
    def index(self) -> int:
        """
        Get the index of this day of the week. Monday is 0; Sunday is 6.

        Returns:
            The index.
        """

        return self.value[0]

    @property
    def letter(self) -> str:
        """
        Get the one letter abbreviation of this day of the week.

        Returns:
            The one letter abbreviation.
        """

        return self.value[1]

    @property
    def abbreviation(self) -> str:
        """
        Get the three letter abbreviation of this day of the week.

        Returns:
            The three letter abbreviation.
        """

        return self.value[2]

    # Alias for abbreviation()
    @property
    def abbr(self) -> str:
        """
        An alias for self.abbreviation.

        Returns:
            The three letter abbreviation.
        """

        return self.abbreviation

    def next_day(self) -> DayOfWeek:
        """
        Get the next day of the week after this one.

        Returns:
            The next day of the week.
        """

        if self == DayOfWeek.Monday:
            return DayOfWeek.Tuesday
        elif self == DayOfWeek.Tuesday:
            return DayOfWeek.Wednesday
        elif self == DayOfWeek.Wednesday:
            return DayOfWeek.Thursday
        elif self == DayOfWeek.Thursday:
            return DayOfWeek.Friday
        elif self == DayOfWeek.Friday:
            return DayOfWeek.Saturday
        elif self == DayOfWeek.Saturday:
            return DayOfWeek.Sunday
        elif self == DayOfWeek.Sunday:
            return DayOfWeek.Monday
        else:
            raise ValueError(f'Unreachable: unknown day {self}')

    @classmethod
    def from_abbr(cls, abbr: str) -> DayOfWeek:
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
            if abbr == day.letter:
                return day

        raise ValueError(f"No DayOfWeek matches for '{abbr}'")

    @classmethod
    def from_full_name(cls, name: str) -> DayOfWeek:
        """
        Get a day of the week from its full name as string.

        Args:
            name: The full name. This is case in-sensitive.

        Returns:
            The associated day of the week.

        Raises:
            ValueError: If there is no match for the given abbreviation.
        """

        name_upper = name.lower()
        for day in cls:
            if name_upper == day.name.lower():
                return day

        raise ValueError(f"No DayOfWeek matches for '{name}'")

    def __lt__(self, other):
        """
        Test whether this is less than the given value (presumably another
        DayOfWeek) by comparing the index associated with the day.

        Args:
            other: The other value to compare to this one.

        Returns:
            True if and only if they are both day of week enums, and this has
            a lower index.
        """

        if self.__class__ is other.__class__:
            return self.index < other.index
        return NotImplemented


# A set containing every day of the week
EVERY_DAY_OF_WEEK: set[DayOfWeek] = {
    DayOfWeek.Monday,
    DayOfWeek.Tuesday,
    DayOfWeek.Wednesday,
    DayOfWeek.Thursday,
    DayOfWeek.Friday,
    DayOfWeek.Saturday,
    DayOfWeek.Sunday
}

# A set containing the five days of the week (not weekends)
WEEK_DAYS: set[DayOfWeek] = {
    DayOfWeek.Monday,
    DayOfWeek.Tuesday,
    DayOfWeek.Wednesday,
    DayOfWeek.Thursday,
    DayOfWeek.Friday
}

WEEKENDS: set[DayOfWeek] = {
    DayOfWeek.Saturday,
    DayOfWeek.Sunday
}
