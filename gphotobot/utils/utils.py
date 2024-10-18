from datetime import datetime, time, timedelta
import logging
from pathlib import Path
import pytz
import re
import traceback
from typing import Awaitable, Callable, Collection, Iterable, Optional

import discord
from discord import app_commands, ui, utils as discord_utils
from discord.ext import commands

from gphotobot.conf import settings
from . import const

_log = logging.getLogger(__name__)

# noinspection SpellCheckingInspection
# This RegEx parses time durations written like this: "4hr 3m 2.5sec"
TIME_DELTA_REGEX = (
    r'^(?:(\d*\.?\d+|\d+\.)\s*(?:\s|y|yrs?|years?))?\s*'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:\s|ds?|dys?|days?))?\s*'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:\s|h|hours?|hrs?)?(?:\s*|:))??'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:\s|m|minutes?|mins?)?(?:\s*|:))??'
    r'(?:(\d*\.?\d+|\d+\.)\s*(?:s|seconds?|secs?)?)?$'
)


def list_to_str(items: Iterable[any],
                delimiter: str = ',',
                conjunction: Optional[str] = 'and') -> str:
    """
    Nicely combine a list of objects into a comma-separated string. This
    includes the Oxford comma. The conjunction is 'and' by default, but it can
    be changed to something else such as 'or'. All objects are converted to a
    string via str(). Make sure to implement __str__() for custom classes.

    This behaves differently based on the number of elements in the list:

    0 elements or None: "" (an empty string).
    1 element: "item1"
    2 elements: "item1 and item2"
    3+ elements: "item1, item2, and item3"

    Args:
        items: The collection of items. If this is a set, note that order of
        the returned string is not guaranteed.
        delimiter: Specify a custom delimiter (instead of the comma, in which
        case this will use an ... "Oxford delimiter"?) Defaults to a ",".
        conjunction: The conjunction to use between the last two elements
        (provided that there are at least two). This appears after the Oxford
        comma in lists of 3+ items. If this is None, no conjunction is used
        between the last item (though they are still separated by the
        delimiter). Defaults to "and".

    Returns:
        A human-friendly string with the combined elements.
    """

    if items is None:
        return ""

    if not hasattr(items, '__len__'):
        items = tuple(items)
    n = len(items)

    if n == 0:
        return ""
    elif n == 1:
        return str(next(iter(items)))
    elif n == 2:
        i1, i2 = items
        conjunction = ' ' if conjunction is None else f' {conjunction} '
        return str(i1) + conjunction + str(i2)
    else:
        conjunction = '' if conjunction is None else f'{conjunction} '
        return (delimiter + ' ').join(
            str(i) if index + 1 < n else conjunction + str(i)
            for index, i in enumerate(items)
        )


def trunc(s: str,
          n: int,
          ellipsis_str: str = '…',
          escape_markdown: bool = False,
          reverse: bool = False) -> Optional[str]:
    """
    Truncate a string to a maximum of n character(s).

    If after truncating, the string ends with an odd number of backslashes
    (before the ellipsis string), then the last backslash is also removed.
    This could put the resulting string from this method one below the
    character limit.

    When escaping Markdown is enabled, it is escaped before truncating. Note
    that a string may appear shorter in Discord than it actually is due to
    Markdown formatting.

    Args:
        s: The string to truncate. If this is None, it returns None.
        n: The maximum number of characters.
        ellipsis_str: The ellipsis character to put at the end if the string is
        This is removed from the maximum length. Defaults to '…'.
        escape_markdown: Whether to escape markdown characters. Defaults to
        False.
        reverse: Whether to put the ellipsis at the START of the string rather
        than the end. Defaults to False.

    Returns:
        str: The truncated string.
    """

    if s is None:
        return None

    if escape_markdown:
        s = discord_utils.escape_markdown(s)

    # If it meets the length requirement, return the string
    if len(s) <= n:
        return s

    # Trim to length, and add the ellipsis

    if reverse:
        # Add the ellipsis at the start
        s = s[-(n - len(ellipsis_str)):]

        # If we cut off an odd number of backslashes, remove one more char
        c = s[:n - len(ellipsis_str) - 1]
        if c.endswith('\\') and (len(c) - len(c.rstrip('\\'))) % 2 == 1:
            return ellipsis_str + s[1:]
        else:
            return ellipsis_str + s

    else:
        # Add the ellipsis at the end
        s = s[:n - len(ellipsis_str)]

        # If it ends with an odd number of backslashes, remove the last one
        if s.endswith('\\') and (len(s) - len(s.rstrip('\\'))) % 2 == 1:
            return s[:-1] + ellipsis_str
        else:
            return s + ellipsis_str


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

    end = datetime.now(pytz.utc) if end is None \
        else end.replace(tzinfo=pytz.utc)

    delta = end - start.replace(tzinfo=pytz.utc)
    sec = delta.total_seconds()

    if sec >= 10:
        return f'{sec:.1f} s'
    elif sec >= 1:
        return f'{sec:.2f} s'
    else:
        return f'{sec * 1000:.1f} ms'


def format_duration(seconds: float | timedelta,
                    always_decimal: bool = False) -> str:
    """
    Take a number of seconds or a timedelta, and format it nicely as a string.

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

    # Return the formatted string (sans the first character, a space)
    return time_str[1:]


def format_time(t: time, use_text: bool = False) -> str:
    """
    Given a `datetime.time`, format it nicely as a string.

    If the seconds are 0, the format is "%-I:%M:%S %p". If it doesn't include
    seconds, the format is the slightly simpler: "%-I:%M %p".

    If there are microseconds, those are included too.

    The formatting can also be overridden with use_text in some cases. If True,
    midnight and noon use those words rather than a time format. Notably,
    milliseconds greater than or equal to 0.9 can round up to midnight. For
    example, "23:59:59.93" is considered midnight. Note that "midnight" and
    "noon" are given in lowercase.

    Args:
        t: The time to format.
        use_text: Replace certain times (midnight and noon) with text rather
        than a time. Defaults to False.

    Returns:
        The formatted time.
    """

    # Check for midnight/noon
    if use_text:
        if (t == time() or t.hour == 23 and t.minute == 59 and
                t.second == 59 and t.microsecond >= 0.9):
            return "midnight"
        elif (t.hour == 12 and t.minute == 0 and
              t.second == 0 and t.microsecond == 0):
            return "noon"

    # Parse time like normal
    if t.second == 0 and t.microsecond == 0:
        return t.strftime('%-I:%M %p')
    elif t.microsecond == 0:
        return t.strftime('%-I:%M:%S %p')
    else:
        return t.strftime('%-I:%M:%S.%f %p')


def parse_time_delta(s: str) -> Optional[timedelta]:
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


def default_embed(**kwargs) -> discord.Embed:
    """
    Generate an embed with the default color and the current timestamp. All
    parameters are passed to discord.Embed().

    Returns:
        discord.Embed: The new embed.
    """

    return discord.Embed(
        color=settings.DEFAULT_EMBED_COLOR,
        timestamp=datetime.now(pytz.utc),
        **kwargs
    )


def app_command_name(interaction: Optional[discord.Interaction]) -> str:
    """
    Get the fully qualified name of an app command. This is equivalent to
    calling interaction.command.qualified_name, except that slash commands are
    prepended with a slash.

    If the interation is None or its associated command is None, this returns
    "[Unknown Command]".

    Args:
        interaction (Optional[discord.Interaction]): The interaction.

    Returns:
        str: The fully qualified name.
    """

    if interaction is None or interaction.command is None:
        return "[Unknown Command]"

    command = interaction.command
    name = command.qualified_name

    if isinstance(command, app_commands.ContextMenu):
        return name
    elif isinstance(command, app_commands.Command):
        return '/' + name
    else:
        _log.warning(f"Unknown interaction command type "
                     f"'{command.__class__.__name__}' for command '{name}'")
        return name


def format_traceback_frame(frame: str) -> str:
    """
    Improve the formatting of a traceback frame. This is a helper function for
    format_traceback().

    Args:
        frame (str): The frame to format.

    Returns:
        str: The formatted frame.
    """

    frame = re.sub(r'\^{5,}', '', frame)
    return frame.strip()


def format_traceback(error: Exception, lines: int) -> str:
    """
    Get a formatted code block string with the last few lines of the traceback
    that caused an error.

    Args:
        error (Exception): The error with the associated traceback.
        lines (int): The number of lines to retrieve.

    Returns:
        str: The stacktrace as a formatted string.
    """

    # Format the last lines of the stacktrace
    tb = error.__traceback__
    stack = [format_traceback_frame(l)
             for l in traceback.format_tb(tb, -lines)]

    # Count the number of frames
    frames = 0
    while tb:
        frames += 1
        tb = tb.tb_next

    # Trim down the stacktrace until it fits in a field
    while True:
        merged = '\n\n'.join(stack)

        # Make a header to show the number of omitted frames
        omitted_frames = frames - len(stack)
        if omitted_frames == 1:
            header = "[1 frame]\n\n"
        elif omitted_frames > 1:
            header = f"[{omitted_frames} frames]\n\n"
        else:
            header = ''

        # If it's too long, shorten it
        # Note: 9 == len("```\n\n```") in format string
        if len(merged) + len(header) + 8 > const.EMBED_FIELD_VALUE_LENGTH:
            # If this is the last frame left, truncate it
            if len(stack) == 1:
                merged = trunc(
                    merged,
                    const.EMBED_FIELD_VALUE_LENGTH - 8 - len(header)
                )
                break
            else:
                # Otherwise, just delete the first frame
                del stack[0]
        else:
            break

    # Return the formatted stacktrace
    return f'```\n{header}{merged}\n```'


def error_embed(error: Exception,
                text: str,
                title: str = 'Error',
                show_details: bool = True,
                show_traceback: bool = False) -> discord.Embed:
    """
    Generate a fancy embed with info about an error.

    Args:
        error (Exception): The error.
        text (str): Text explaining what went wrong.
        title (str): The title of the embed. Defaults to 'Error'.
        show_details (bool, optional): Whether to add a field to the embed that
        gives the exception class name and the error message. Defaults to True.
        show_traceback (bool, optional): Whether to include the last few
        lines of the traceback in a field. This can be enabled even when
        show_details is False. Defaults to False.

    Returns:
        discord.Embed: The embed.
    """

    # Build the initial embed
    embed = contrived_error_embed(text=text, title=title)

    # Add exception details, if enabled
    if show_details:
        err_str = str(error) if str(error) else '*[No details given]*'

        embed.add_field(
            name=trunc(error.__class__.__name__,
                       const.EMBED_FIELD_NAME_LENGTH),
            value=trunc(err_str, const.EMBED_FIELD_VALUE_LENGTH),
            inline=False
        )

    # Add traceback, if enabled
    if show_traceback:
        stack = format_traceback(
            error=error,
            lines=settings.ERROR_TRACEBACK_LENGTH
        )

        if stack:
            embed.add_field(
                name='Traceback',
                value=stack,
                inline=False
            )

    return embed


def contrived_error_embed(text: str,
                          title: str = 'Error') -> discord.Embed:
    """
    Create an embed with a contrived error message: that is, an error that did
    not originate from an actual exception. This has no exception class name,
    exception message, or stacktrace.

    Args:
        text (str): The error message.
        title (str, optional): The embed title. Defaults to 'Error'.

    Returns:
        discord.Embed: The embed.
    """

    return discord.Embed(
        title=title,
        description=text,
        color=settings.ERROR_EMBED_COLOR,
        timestamp=datetime.now(pytz.utc)
    )


async def handle_err(interaction: discord.Interaction[commands.Bot],
                     error: Exception,
                     text: str,
                     log_text: str = None,
                     title: str = 'Error',
                     show_details: bool = True,
                     show_traceback: bool = False) -> None:
    """
    Nicely handle generic errors, sending some info to the user in an embed and
    logging it.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction to
        which to send the error message.
        error (Exception): The error.
        text (str): Text explaining what went wrong.
        log_text (str): Separate text to use for the log description. If this
        is None or empty, the same text is used for the Discord error message
        and log. Defaults to None.
        title (str): The title of the embed. Defaults to 'Error'.
        show_details (bool, optional): Add details. Defaults to True.
        show_traceback (bool, optional): Add traceback. Defaults to False.
    """

    # Build an embed to nicely display the error
    embed = error_embed(
        error=error,
        text=text,
        title=title,
        show_details=show_details,
        show_traceback=show_traceback
    )

    # Send the error message
    await update_interaction(interaction, embed)

    # Log details
    log_text = log_text if log_text else text if text else '[No details given]'
    _log.error(f'{log_text}: {error}')
    _log.debug(f'Traceback on {error.__class__.__name__}:', exc_info=True)


async def update_interaction(interaction: discord.Interaction[commands.Bot],
                             embed: discord.Embed) -> None:
    # If the interaction command in None, the command is probably
    # unrecognized (due to sync not updating yet). We'll just respond normally,
    # as this is likely the first response
    if interaction.command is None:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Use extras to determine whether it's deferred and/or ephemeral
    extras = interaction.command.extras
    is_ephemeral = 'ephemeral' in extras

    # If no response was sent yet (apart from maybe deferring),
    # then send the error
    if not interaction.response.is_done():
        if 'defer' in extras:
            await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)
        else:
            await interaction.response.send_message(embed=embed,
                                                    ephemeral=is_ephemeral)
        return

    # Otherwise, edit the original message

    # Attempt to get the original message to preserve the content and
    # embeds. If that fails, replace it with the error embed
    try:
        msg = await interaction.original_response()
        embeds = msg.embeds
        if len(embeds) == const.EMBED_FIELD_MAX_COUNT:
            embeds[-1] = embed
        else:
            embeds.append(embed)
    except KeyboardInterrupt:
        raise
    except Exception:
        embeds = [embed]
        msg = None

    # Edit the original message
    if is_ephemeral:
        await interaction.edit_original_response(
            content=msg.content if msg else None,
            embeds=embeds)
    else:
        if msg is None:
            _log.error(f'Cannot update message to include error embed. '
                       f'Failed to retrieve the original response from '
                       f'the interaction {interaction}.')
        else:
            await msg.edit(content=msg.content if msg else None,
                           embeds=embeds)


def get_unique_path(path: Path, condition: Callable[[Path], bool]) -> Path:
    """
    Given some path, modify it so that it meets some condition.

    If the path already meets the condition, it is returned unchanged.
    Otherwise, it is appended with incrementing numbers until it meets that
    condition. The intended use for this is getting a file/directory that
    doesn't already exist.

    If the path has a suffix (i.e. a file extension), the incrementing number
    is placed before that extension.

    Args:
        path: The original path.
        condition: The condition that the output path must satisfy. This is a
        function that accepts and path and returns a boolean indicating whether
        it's valid.

    Returns:
        The output path, which may be the same as the input.
    """

    old: Path = path
    i: int = 0

    while not condition(path):
        i += 1
        path = old.parent / (old.stem + str(i) + old.suffix)

    return path


def get_button(parent: discord.ui.View,
               label: str) -> Optional[discord.ui.Button]:
    """
    Get the button attached to a parent view by specifying that buttons' label.

    Args:
        parent: The parent view.
        label: The current label of the desired button.

    Returns:
        The button, or None if no button with that label is found.
    """

    for child in parent.children:
        if isinstance(child, discord.ui.Button):
            if child.label == label:
                return child

    return None


def deferred(callback: Callable[[discord.Interaction, ...], Awaitable] | \
                       Callable[[discord.Interaction], Awaitable]) -> \
        Callable[[discord.Interaction], Awaitable]:
    """
    Given a callback function that accepts an interaction, wrap it such that the
    interaction is immediately deferred.

    Args:
        callback: The callback function to wrap. This must accept an
        interaction, and it can also include other arguments to pass to the
        callback function unmodified.

    Returns:
        An async wrapper around the callback that defers the interaction.
    """

    async def defer(interaction: discord.Interaction, *args, **kwargs) -> any:
        await interaction.response.defer()
        # Include *args and **kwargs just in case more arguments were given
        return await callback(interaction, *args, **kwargs)

    return defer


def num_to_word(num: int) -> str:
    """
    Converts a number to its word representation. This only works for single
    digit numbers.

    Args:
        num: The number to convert.

    Returns:
        The string representation.

    Raises:
        ValueError: If the number is out of range (only 0-9 supported).
    """

    if num == 0:
        return "Zero"
    elif num == 1:
        return "One"
    elif num == 2:
        return "Two"
    elif num == 3:
        return "Three"
    elif num == 4:
        return "Four"
    elif num == 5:
        return "Five"
    elif num == 6:
        return "Six"
    elif num == 7:
        return "Seven"
    elif num == 8:
        return "Eight"
    elif num == 9:
        return "Nine"
    else:
        raise ValueError(f"Number {num} out of range (0-9): "
                         "can't convert it to a word")


def set_menu_default(menu: ui.Select, default: str | Collection[str]):
    """
    Mark one or more entries in a dropdown menu as default, thus pre-selecting
    them. If any options are marked as default already but not in the given
    list of labels, they are unmarked. It is possible that this method will
    do nothing, if the given default labels don't match any options.

    Args:
        menu: The selection menu.
        default: One or more items to mark default, referenced by their labels.
    """

    # Encapsulate a single entry in a tuple
    if isinstance(default, str):
        default = (default,)

    # Set default options
    for option in menu.options:
        option.default = option.label in default
