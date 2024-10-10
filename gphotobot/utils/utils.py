from datetime import datetime
import logging
from typing import Optional

import pytz
import re
import traceback

import discord
from discord import app_commands, utils as discord_utils
from discord.ext import commands

from gphotobot.conf import settings
from . import const

_log = logging.getLogger(__name__)


def trunc(s: str,
          n: int,
          ellipsis_str: str = '…',
          escape_markdown: bool = False) -> Optional[str]:
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

    Returns:
        str: The truncated string.
    """

    if s is None:
        return None

    if escape_markdown:
        s = discord_utils.escape_markdown(s)

    if len(s) > n:
        # Trim to length (with enough space to add the ellipsis)
        s = s[:n - len(ellipsis_str)]

        # If it ends with an odd number of backslashes, remove the last one
        if s.endswith('\\') and (len(s) - len(s.rstrip('\\'))) % 2 == 1:
            return s[:-1] + ellipsis_str
        else:
            return s + ellipsis_str
    else:
        return s


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


def format_time(seconds: float) -> str:
    """
    Take a number of seconds and format it nicely as a string.

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
        seconds (float): The number of seconds.

    Returns:
        str: The formatted time string.
    """

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

    time = ''
    if years > 0:
        time += f' {years}y'
    if days > 0:
        time += f' {days}d'
    if hours > 0:
        time += f' {hours}h'
    if minutes > 0:
        time += f' {minutes}m'
    if seconds > 0:
        time += f' {seconds}s'

    return time[1:]


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
