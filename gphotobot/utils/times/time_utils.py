from datetime import datetime, time, timedelta, timezone
import re

# noinspection SpellCheckingInspection
# This RegEx parses time durations written like this: "4hr 3m 2.5sec"
TIME_DELTA_REGEX = (
    r'^(?:(\d*\.?\d+|\d+\.)\s*(?:\s|y|yrs?|years?))?\s*'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:\s|ds?|dys?|days?))?\s*'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:\s|h|hours?|hrs?)?(?:\s*|:))??'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:\s|m|minutes?|mins?)?(?:\s*|:))??'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:s|seconds?|secs?)?)?$'
)


def format_duration(seconds: float | timedelta,
                    always_decimal: bool = False,
                    spaces: bool = True) -> str:
    """
    Take a timedelta or a float in seconds, and format it nicely as a string.

    If less than 1 second: "0.00s"
    If less than 10 seconds: "0.0s"

    Otherwise, it's separated into years, days, hours, minutes, and seconds.
    Any unit with a value >0 is included. Examples:
        - "3h 7m 6s"
        - "1d 5s"
        - "7y 71d 10h 2m 55s"
        - "9d"

    Note that by the time you get to years, this isn't super accurate. It
    assumes each year is exactly 365 days.

    Args:
        seconds: The number of seconds or a timedelta.
        always_decimal: Whether to always include a decimal number of seconds,
        if applicable. Maximum 3 decimal places. Defaults to False.
        spaces: Whether to include spaces in the output string between each
        unit of time. Defaults to True.

    Returns:
        str: The formatted time string.
    """

    # If it's a timedelta, convert to seconds
    if isinstance(seconds, timedelta):
        seconds = seconds.total_seconds()

    # Separate rounding if always_decimal is disabled
    if not always_decimal:
        if seconds < 1:
            return f'{seconds:.2f}s'
        elif seconds < 10:
            return f'{seconds:.1f}s'

        # Omit decimals after the 10-second mark
        seconds = int(seconds)

    # Split units
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    years, days = divmod(days, 365)

    # If always_decimal is enabled, everything is currently a float
    if always_decimal:
        years = int(years)
        days = int(days)
        hours = int(hours)
        minutes = int(minutes)
        if int(seconds) == seconds:
            seconds = int(seconds)
        else:
            seconds = round(seconds, 4)

    # Build the formatted string
    time_str = ''
    if years > 0:
        time_str += f' {years}y'
    if days > 0:
        time_str += f' {days}d'
    if hours > 0:
        time_str += f' {hours}h'
    if minutes > 0:
        time_str += f' {minutes}m'
    if seconds > 0:
        time_str += f' {seconds}s'

    # Return the formatted string (sans the first character, a space) or with
    # all spaces removed, if spaces == False
    return time_str[1:] if spaces else time_str.replace(' ', '')


def format_time(t: time | datetime | None = None,
                use_text: bool = False) -> str:
    """
    Given a `datetime.time`, format it nicely as a string. (This does not
    include the date portion if a datetime is given).

    This uses the simplest available format that includes all the time
    information (though notably it uses AM/PM and not military time):
    - If the minutes, seconds, and microseconds are all 0, it uses the simple
      format "%-I%p".
    - If there are minutes, but the seconds and microseconds are 0, it uses
      "%-I:%M %p".
    - If there are seconds but no microseconds, the format is "%-I:%M:%S %p".
    - And with microseconds, it's "%-I:%M:%S.%f %p"

    The formatting can also be overridden with use_text in some cases. If True,
    midnight and noon use those words rather than a time format. Notably,
    milliseconds greater than or equal to 0.5 can round up to midnight. For
    example, "23:59:59.52" is considered midnight. Note that "midnight" and
    "noon" are given in lowercase.

    Args:
        t: The time to format. If None, the current time is used. Defaults to
        None.
        use_text: Replace certain times (midnight and noon) with text rather
        than a time. Defaults to False.

    Returns:
        The formatted time.
    """

    # If not given a time, use the current one. If given a datetime, convert it
    if t is None:
        t: time = datetime.now().time()
    elif isinstance(t, datetime):
        t: time = t.time()

    # Check for midnight/noon
    if use_text:
        if (t == time() or t.hour == 23 and t.minute == 59 and
                t.second == 59 and t.microsecond >= 0.5):
            return "midnight"
        elif (t.hour == 12 and t.minute == 0 and
              t.second == 0 and t.microsecond == 0):
            return "noon"

    # Parse time like normal, with preference to simpler formats
    if t.microsecond != 0:
        return t.strftime('%-I:%M:%S.%f %p')
    elif t.second != 0:
        return t.strftime('%-I:%M:%S %p')
    elif t.minute != 0:
        return t.strftime('%-I:%M %p')
    else:
        return t.strftime('%-I%p')


def parse_time_delta(s: str) -> timedelta | None:
    """
    Take a string representing a duration of time, parse it, and return an
    appropriate timedelta. It is case-insensitive.

    If the string is unparseable, it returns None. This shouldn't raise any
    exceptions.

    Note that this uses the conversion 1 year = 365 days. It does not take into
    account leap years. (But if you're making a timelapse that takes one photo
    every year, should you really be using a Discord bot to control it?)

    This supports strings in a few formats, such as:
    - "1y 2d 40h 2m 1s"
    - "5.2 yrs 18ds 0.001seconds"
    - "8:23m"
    - "1:05sec"
    - "30:00" (30 minutes, not 30 hours)

    Args:
        s: The string to parse.

    Returns:
        The parsed timedelta, or None if the string cannot be parsed.
    """

    if not s:
        return None

    match = re.match(TIME_DELTA_REGEX, s.strip().lower(), re.IGNORECASE)

    if not match:
        return None

    # Extract units
    y = match.group(1)
    d = match.group(2)
    h = match.group(3)
    m = match.group(4)
    s = match.group(5)

    # Combine into a timedelta
    return timedelta(
        days=float(y if y else 0) * 365 + float(d if d else 0),
        hours=float(h if h else 0),
        minutes=float(m if m else 0),
        seconds=float(s if s else 0)
    )


def latency(start: datetime, end: datetime = None) -> str:
    """
    Calculate latency, and format it nicely as a string.

    Args:
        start (datetime): The start time.
        end (datetime, optional): The end time. If None, the current time is
        used. Defaults to None.

    Returns:
        str: The latency as a nicely formatted string.
    """

    end = datetime.now(timezone.utc) if end is None \
        else end.replace(tzinfo=timezone.utc)

    delta = end - start.replace(tzinfo=timezone.utc)
    sec = delta.total_seconds()

    if sec >= 10:
        return f'{sec:.1f} s'
    elif sec >= 1:
        return f'{sec:.2f} s'
    else:
        return f'{sec * 1000:.1f} ms'
