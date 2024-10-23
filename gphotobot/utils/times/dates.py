from collections.abc import Sequence, Iterable
from datetime import date, datetime, timedelta
from typing import Optional, Union

from .. import utils

# Fixed 1-day offset
ONE_DAY = timedelta(days=1)


class DateSegment:
    def __init__(self,
                 dates: Union[date,
                 tuple[date, date | None],
                 Iterable[date | tuple[date, date | None]]]):
        """
        Initialize this date segment. A date segment contains a sequence of
        dates that are either (a) all within the same month of the same year or
        (b) span a single range of consecutive dates.

        For example the range [Jan 4, 2020] to [Apr 18th, 2053] (stored as a
        single tuple with those two dates) might constitute an entire segment
        (nothing else could be added unless it extended that range with more
        consecutive days).

        Or it might contain [Jun 10, 2025] to [Jun 18, 2025], as well as
        [Jun 23, 2025] and [Jun 28, 2025] to [Jun 30, 2025]. All of these (two
        ranges and one standalone date) could all be in the same segment.

        Args:
            dates: The dates from which to construct this segment.
        """

        # This is a list of dates that are a part of the segment. Each is given
        # as a range from date1 to date2. If the second date is None, then it's
        # just a single date rather than a range.

        self.dates: list[tuple[date, date | None]]

        # Coerce the given dates into the desired format
        if isinstance(dates, date):
            self.dates = [(dates, None)]  # single date
        elif isinstance(dates, tuple):
            self.dates = [dates]  # single range (or single date)
        else:
            self.dates = []
            for d in dates:  # iterable with multiple dates/ranges
                if isinstance(d, date):
                    self.dates.append((d, None))
                else:
                    self.dates.append(d)  # noqa

    def spans_months(self) -> bool:
        """
        Check whether this segment spans multiple months.

        Returns:
            True if and only if it spans more than one month.
        """

        # Can't have multiple months if multiple dates/ranges were given
        if len(self.dates) != 1:
            return False

        d1, d2 = self.dates[0]
        return d2 is not None and (d1.year != d2.year or d1.month != d2.month)

    def multiple_parts(self) -> bool:
        """
        Check whether this segment has multiple parts (i.e. has multiple dates
        or ranges).

        Returns:
            True if and only if it contains more than one part.
        """

        return len(self.dates) > 1

    def is_range(self, index: int) -> bool:
        """
        Check whether the entry at the specified index is a range of consecutive
        dates (as opposed to a single date).

        Args:
            index: The index to check (0-indexed). Use -1 to get the last entry,
            following normal Python indexing.

        Returns:
            True if and only if the entry at that index contains multiple dates.
        """

        return self.dates[index][1] is not None

    def to_string(self,
                  long: bool = False,
                  force_year: bool = False) -> str:
        if len(self.dates) == 0:
            return ""

        # Get the first date/range
        d1, d2 = self.dates[0]

        # If there's only one date/range, it might span multiple months/years
        if len(self.dates) == 1:
            if self.spans_months():
                # The range spans multiple months
                if d1.year == d2.year:
                    # Dates are in the same year. Just put it once at the end
                    return (fmt_date(d1, long=long) + ' – ' +
                            fmt_date(d2, long=long) +
                            f", {d1.year}" if force_year else "")
                else:
                    # Dates are in different years: include both of them
                    return (fmt_date(d1, long=long, year=True) + ' to ' +
                            fmt_date(d2, long=long, year=True))
            elif d2 is None:
                # There's just one date in this whole segment
                return fmt_date(d1, long=long, year=force_year)
            else:
                # There's just one range in one month. List the month once
                return (fmt_date(d1, long=long, ordinal=False) + '–' +
                        fmt_date(d2, month=False, year=force_year))

        # If this is reached, then there are two or more dates/ranges,
        # and they're all within the same month of the same year. Build each
        # part one at a time

        parts: list[str] = []

        # Add each date/range. The first one includes the month name
        for i, (d1, d2) in enumerate(self.dates):
            if d2 is None:
                parts.append(fmt_date(d1, long=long, month=i == 0))
            else:
                parts.append(
                    fmt_date(d1, ordinal=False, month=i == 0, long=long) +
                    '–' + fmt_date(d2, month=False)
                )

        # Add the year, if forced. Figure out whether to preface the year with
        # "of" or a comma based on how many entries there have been
        if force_year:
            if len(self.dates) > 3 or \
                    (len(self.dates) == 2 and self.is_range(-1)):
                parts[-1] += f' of {self.dates[-1][0].year}'
            else:
                parts[-1] += f', {self.dates[-1][0].year}'

        # Combine all the parts, and return the final string
        return utils.list_to_str(parts, conjunction='&')


class DateString:
    def __init__(self, dates: Iterable[date]) -> None:
        """
        Taken a SORTED list of UNIQUE dates, and format them into a
        user-friendly string. First, they are parsed into segments and tokens,
        and those can later be rendered as a string.

        Args:
            dates: The dates to parse and format.
        """

        self.dates: tuple[date, ...]
        if isinstance(dates, tuple):
            self.dates = dates
        else:
            self.dates = tuple(dates)

        self.segments: list[DateSegment] = self._build_segments()

    def _build_segments(self) -> list[DateSegment]:
        """
        Take the list of dates, and separate them into separate segments for
        formatting later.

        Returns:
            The list of segments.
        """

        segments: list[DateSegment] = []

        if len(self.dates) == 0:
            return segments
        elif len(self.dates) == 1:
            segments.append(DateSegment(self.dates[0]))
            return segments

        # Identify and merge consecutive dates
        ranges: list[tuple[date, date | None]] = group_ranges(self.dates)

        # Create segments from the ranges. If two ranges are entirely within
        # the same month, then they're part of the same segment
        start = 0
        start_date = ranges[start][0]

        for i in range(1, len(ranges)):
            l = ranges[i][0] if ranges[i][1] is None else ranges[i][1]
            if start_date.month != l.month or start_date.year != l.year:
                segments.append(DateSegment(ranges[start:i]))
                start = i
                start_date = ranges[start][0]

        # Add the last segment
        segments.append(DateSegment(ranges[start:]))

        # Return completed segments
        return segments

    def to_string(self,
                  max_len: Optional[int] = None,
                  none_on_fail: bool = False,
                  force_year_at: int = 0,
                  indicate_if_abbreviated: bool = False) -> \
            Union[Optional[str], Optional[tuple[str, bool]]]:
        """
        Build the final string from all the date segments.

        Args:
            max_len: The maximum allowed length of the returned string. If the
            full string would exceed this length, segments are dropped one at
            a time until it fits. None to disable this. Defaults to None.
            none_on_fail: Whether to return None if it's impossible to build
            the string with the given length restriction. If False, it'll return
            a single ellipsis character instead (if that fits). Note that this
            does not prevent the string from being abbreviated. Defaults to
            False.
            force_year_at: If the number of segments is less than or equal to
            this threshold, the year will always be included (even if it's 
            otherwise not necessary). Use 0 to never force. Defaults to 0.
            indicate_if_abbreviated: Whether to return, in addition to the
            formatted a string, a boolean that indicates whether said string was
            truncated due to not having enough space. Defaults to False.

        Returns:
            The built string listing the dates. This can only ever be None if
            the max_len is 0 or none_on_fail is True.
        """

        # Determine whether the year must be included in every segment, or only
        # at the start/end of the string, or not at all
        first_year = self.dates[0].year
        if len(self.dates) <= force_year_at:
            requires_year = True
            append_year = False
        elif all(d.year == first_year for d in self.dates[1:]):
            requires_year = False
            append_year = first_year != datetime.now().year
        else:
            requires_year = True
            append_year = False

        # Figure out whether semicolons are required as delimiters between
        # segments (instead of commas). This is true if any segments span
        # multiple months, or any have multiple dates/ranges, or we need to
        # list the year in each component
        if requires_year or any(s.spans_months() for s in self.segments) or \
                any(s.multiple_parts() for s in self.segments):
            delimiter = ';'
        else:
            delimiter = ','

        # Prepare to convert segments to strings, saved as `parts`
        n = len(self.segments)
        parts: list[str] = []

        # If we need to append the year, determine whether to use a prefix
        prefix = ''
        if append_year:
            if n > 1:
                prefix = f'All {first_year}: '
            else:
                requires_year = True

        length = len(prefix)
        conjunction = 'and'

        # Add each segment one at a time until the max_len is reached
        for i, segment in enumerate(self.segments):
            # Try with long month name only for one segment
            seg_str = segment.to_string(long=n == 1, force_year=requires_year)
            new_length = length + len(seg_str) + 2

            if max_len is not None:
                # Go back to short month name if it exceeds the max len
                if new_length > max_len and n == 1:
                    seg_str = segment.to_string(force_year=requires_year)
                    new_length = length + len(seg_str) + 2

                # If it still exceeds the length, and this is the last entry,
                # what if we replace "and" with "&" to save 2 characters?
                if i + 1 == n and new_length > max_len >= new_length - 2:
                    new_length -= 2
                    conjunction = '&'

                if new_length > max_len:
                    # If there aren't any entries yet, give up
                    if len(parts) == 0:
                        s = None if max_len < 1 or none_on_fail else '…'
                        return s, True if indicate_if_abbreviated else s

                    # We'll be exiting the loop now. Disable the conjunction,
                    # as we won't get to the last item
                    conjunction = None

                    # Otherwise, see if we can fit an ellipsis
                    if length + 3 > max_len:
                        parts.append('…')
                        break

                    # Try removing the last item and then adding the ellipsis
                    del parts[-1]
                    if len(parts) == 0:
                        # Oh well ¯\_(ツ)_/¯
                        s = None if max_len < 1 or none_on_fail else '…'
                        return s, True if indicate_if_abbreviated else s
                    else:
                        parts.append('…')
                        break

            # Add this segment, and update the length (+2 for the delimiter)
            parts.append(seg_str)
            length += len(seg_str) + (0 if i == 0 else 2)

            # Add 4 more to the length if we're going into the last entry, to
            # account for the "and"
            if i + 2 == n:
                length += 4

        # Combine all the parts using the delimiter
        s = prefix + utils.list_to_str(
            parts,
            delimiter=delimiter,
            conjunction=conjunction
        )

        # The conjunction being changed to None is an effective proxy for
        # whether the string was abbreviated
        return (s, conjunction is None) if indicate_if_abbreviated else s


def group_ranges(dates: Sequence[date]) -> list[tuple[date, date | None]]:
    """
    Given a sequence of unique dates in chronological order, identify groups
    of consecutive dates (i.e. ranges), and return those groups.

    Args:
        dates: The sequence of dates to process.

    Returns:
        A list of tuples with two elements. If the second element is None, then
        that tuple represents a single date; otherwise, it's a range of
        consecutive dates.
    """

    ranges: list[tuple[date, date | None]] = []

    # Use a start/end index to build ranges one at a time
    start = end = dates[0]
    for i in range(1, len(dates)):
        if end + ONE_DAY == dates[i]:
            end = dates[i]
        else:
            ranges.append((start, None if start == end else end))
            start = end = dates[i]

    # Add the last range
    ranges.append((start, None if start == end else end))

    return ranges


def add_ordinal(d: date) -> str:
    """
    Convert a date to a string with just the day of the month and the
    appropriate ordinal. The day is not zero-padded, and the month is not
    included. The output will look like "4th" or "22nd".

    Args:
        d: The date to format.

    Returns:
        The formatted string.
    """

    day = d.day
    suffix = "th" if 11 <= day <= 13 else \
        {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def fmt_date(d: date,
             ordinal: bool = True,
             month: bool = True,
             long: bool = False,
             year: bool = False) -> str:
    """
    Format one date in a succinct, user-friendly way.

    Args:
        d: The date to format.
        ordinal: Whether to include the ordinal (e.g. "15th", "21st", etc.).
        Defaults to True.
        month: Whether to include the month. If this is False, `long` (for a
        long month name) is ignored. Defaults to True.
        long: Whether to use the full month name (e.g. "September" instead of
        "Sep"). Defaults to False.
        year: Whether to include the year. Defaults to False.

    Returns:
        A formatted string with this single date.
    """

    m = d.strftime(f"%{'B' if long else 'b'} ") if month else ""
    day = add_ordinal(d) if ordinal else str(d.day)
    y = f', {d.year}' if year else ''

    # Assemble day/month/year components
    return m + day + y
