from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from abc import ABC, abstractmethod


class Days(ABC):
    """
    A Days object constitutes the primary part of a ScheduleEntry, specifying
    the single day or multiple days that it applies.

    All Days objects must be immutable. Methods that apply "changes" should
    actually return modified copies.
    """

    UNDEFINED = "*Undefined*"

    @classmethod
    def create_rule_from_db(cls, db_str: str) -> Days:
        """
        Create a Days rule from a database string by finding the correct class
        and calling its from_db() method.

        Args:
            db_str: The database string representation. This must have been
            created from the to_db() method of some rule inheriting from Days.

        Returns:
            A new Days rule of the appropriate type.
        """

        # Extract the class name: db strings are in the form "ClassName(data)"
        class_name = db_str.split('(', maxsplit=1)[0]

        # Find the appropriate class
        for c in cls.__subclasses__():
            if c.__name__ == class_name:
                return c.from_db(db_str)

        # Couldn't find a matching class
        raise ValueError(f"No Days rule class found matching '{class_name}' "
                         f"for db_str '{db_str}'")

    #################### STRING REPRESENTATIONS ####################

    @abstractmethod
    def to_db(self) -> str:
        """
        Convert the data for this Days identifier into a string that can be used
        in the database. It must have all the information necessary to recreate
        this Days object.

        This should be the name of the class with all the relevant data in
        parentheses:
        "Days(data_here)"

        In some implementations, this might just use __repr__().

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
    def str_rule(self) -> str:
        """
        Get a user-friendly string that describes what type of rule this is.
        This is probably not dependent on the contents of the rule.

        Returns:
            What type of rule this is.
        """

        pass

    @abstractmethod
    def str_shortest(self) -> str:
        """
        Get the shortest possible user-friendly string with information about
        this rule. (Emphasis on user-friendly. This isn't necessarily the *shortest*
        possible string). If it's possible to include all information, then do
        so. Otherwise, just describe the rule type, like str_type().

        This is slightly shorter than str_header().

        If the rule is currently empty, use the `self.UNDEFINED` string.

        Returns:
            The shortest string with info about this rule.
        """

        pass

    @abstractmethod
    def str_header(self) -> tuple[str, bool]:
        """
        Get a user-friendly string describing this rule for use in an embed
        header. It should be longer than str_shortest() but not as long as
        str_long().

        If it's possible to include all the information about this rule, then
        do so. If not, try to give some description that's influenced by the
        content of the rule.

        If the rule is currently empty, use the `self.UNDEFINED` string.

        Additionally, return a boolean indicating whether the header contains
        all the information about this rule.

        (Note: This is also the default implementation for `__str__()`.)

        Returns:
            A string for use in an embed header.
        """

        pass

    @abstractmethod
    def str_long(self, max_len: Optional[int]) -> str:
        """
        Get a user-friendly string describing this rule. This is the longest
        string form of this rule, besides perhaps the one for the database,
        which much include all the information.

        This string should be condensed and user-friendly, and it should include
        as much information about the rule as possible without exceeding the
        max_len.

        This is mainly for use in an embed field (the body text, not the
        header).

        If the rule is currently empty, use the `self.UNDEFINED` string.

        Args:
            max_len: The maximum allowed length of the string. If this is None,
            there is no maximum. Defaults to None.

        Returns:
            A long string describing this embed.
        """

        pass

    def __str__(self):
        """
        Get a string representation of this rule. This is just the same as
        self.str_header() without the boolean.

        Returns:
            A user-friendly string representation.
        """

        return self.str_header()[0]

    #################### OTHER ####################

    @abstractmethod
    def runs_exactly_once(self) -> bool:
        """
        Determine whether this rule only applies to exactly one date, meaning
        it is only relevant for one day in time.

        Returns:
            Whether it applies to just one date.
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
    def does_run_on(self, d: date | datetime) -> bool:
        """
        Check whether this rule applies on the given date.

        Args:
            d: The date to check. (If this is a datetime, it's converted to a
            date before processing).

        Returns:
            True if and only if this rule applies on that date.
        """

        pass

    @abstractmethod
    def next_event_after(self, d: date | datetime) -> Optional[date]:
        """
        Get the next time that this rule changes state after the given date.
        In other words, if the rule is currently active on the given date, then
        this is the nearest date on which it is not active. Or, if it's not
        active on the given date, then this is the nearest date on which it is
        active.

        If this rule either never applies or always applies from the given date
        onwards, this returns None.

        Args:
            d: Begin checking after this date. (If this is a datetime,
            it's converted to a date before processing).

        Returns:
            The next date that this rule changes state, or None if it never
            will.
        """

        pass
