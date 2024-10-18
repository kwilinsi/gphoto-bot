from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from gphotobot.utils.validation_error import ValidationError
from gphotobot.utils.dates import DateString
from .days import Days


class Dates(dict[date, None], Days):
    # ISO-8601 date format
    DATE_FORMAT = '%Y-%m-%d'

    # The maximum specific dates this can have
    MAX_ALLOWED_DATES = 20

    def __init__(self, dates: Iterable[datetime | date] = ()):
        """
        Initialize a Dates rule list with zero or more dates.

        Args:
            dates: One or more dates. Duplicates are ignored. Defaults to None.

        Raises:
            ValidationError: If the number of dates exceeds the maximum allowed
            number (MAX_ALLOWED_DATES). This is intended for showing to the user
            in an embed. The attr should be used as the embed title.
        """

        date_list: set[date] = {d.date if isinstance(d, datetime) else d
                                for d in dates}

        # Validate length
        self.validate_size(len(date_list))

        # Sort the dates, and pass them to super, the actual list implementation
        super().__init__({d: None for d in sorted(date_list)})

    def add(self, new_date: date | datetime | Iterable[date | datetime]):
        """
        Add one or more dates to this list. Duplicates are ignored.

        Args:
            new_date: The date or datetime to add.

        Raises:
            ValidationError: If the number of dates would exceed the maximum
            allowed threshold (MAX_ALLOWED_DATES).
        """

        # Convert a single datetime to a date
        if isinstance(new_date, datetime):
            new_date = (new_date.date(),)
        elif isinstance(new_date, date):
            new_date = (new_date,)

        for d in new_date:
            if d not in self:
                self.validate_size(len(self) + 1)
                self[d] = None

    def remove(self, remove_date: date | datetime | Iterable[date | datetime]):
        """
        Remove one or more dates from this rule set. If they aren't in the set
        already, nothing happens.

        Args:
            remove_date: The date or datetime to remove.
        """

        # Case with a single datetime
        if isinstance(remove_date, datetime):
            remove_date = (remove_date.date(),)
        elif isinstance(remove_date, date):
            remove_date = (remove_date,)

        for d in remove_date:
            if d in self:
                del self[d]

    def __repr__(self):
        """
        Get a string representation of this Dates object. It includes each date
        in the ISO-8601 format YYYY-MM-DD, without any attempt to combine them
        for easier readability. Each date is separated by a semicolon,
        and they are all enclosed in "Dates()".

        Returns:
            String representation of this Dates object.
        """

        date_str = ';'.join(d.strftime(self.DATE_FORMAT) for d in self)
        return f"{self.__class__.__name__}({date_str})"

    #################### DAYS METHOD IMPLEMENTATIONS ####################

    # to_db alis for repr()
    to_db = __repr__

    @classmethod
    def from_db(cls, string: str) -> Dates:
        return cls(datetime.strptime(d, cls.DATE_FORMAT).date()
                   for d in string[6:-1].upper().split(';'))

    def str_rule(self) -> str:
        return 'Specific date' + ('' if len(self) == 1 else 's')

    def str_shortest(self) -> str:
        # This method returns a maximum of 17 characters in "20 specific dates".
        # Longest string with actual dates is something like "Sep 15–30, 2030"

        # If there aren't any dates, use the undefined string
        if len(self) == 0:
            return self.UNDEFINED

        s = DateString(self).to_string(max_len=17, none_on_fail=True)
        return f"{len(self)} specific dates" if s is None else s

    def str_header(self) -> tuple[str, bool]:
        # If there aren't any dates, use the undefined string
        n = len(self)
        if n == 0:
            return self.UNDEFINED, True

        # Generate the string with the dates. 35 characters should always be
        # enough to at least list one date or date range, so no need to handle
        # a case where it returns None as in str_shortest()
        string, abbreviated = DateString(self).to_string(
            max_len=35, indicate_if_abbreviated=True
        )
        return string, not abbreviated

    def str_long(self, max_len: int) -> str:
        # If there aren't any dates, use the undefined string
        n = len(self)
        if n == 0:
            return self.UNDEFINED

        return DateString(self).to_string(
            max_len=max_len,
            force_year_at=1
        )

    def runs_exactly_once(self) -> bool:
        return len(self) == 1

    def does_ever_run(self) -> bool:
        return len(self) > 0

    #################### EXTRA FUNCTIONS ####################

    def validate_size(self, n: int) -> None:
        """
        Check the n, the "would be" number of unique dates in this rule set,
        is within the maximum limit.

        If n is greater than the maximum allowed number of dates, raise a
        ValidationError with a helpful user-friendly error message. The attr
        value is intended for use as an embed title.

        Args:
            n: The number of elements to validate.

        Raises:
            ValidationError: If n exceeds the limit.
        """

        if n > self.MAX_ALLOWED_DATES:
            raise ValidationError(
                attr='Error: Too Many Dates',
                msg=f"You can't have more than "
                    f"**{Dates.MAX_ALLOWED_DATES}** specific dates in a "
                    f"schedule entry. Try creating another entry if you "
                    f"need more dates."
            )
