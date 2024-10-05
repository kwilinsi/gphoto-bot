from datetime import datetime
import logging
import pytz
import traceback

import discord
from gphoto2 import GPhoto2Error

from gphotobot.conf import settings
from . import const


_log = logging.getLogger(__name__)


def trunc(s: str, n: int, elipsis: str = '…') -> str:
    """
    Truncate a string to a maximum of n character(s).

    Args:
        s (str): The string to truncate. If this is None, it returns None.
        n (int): The maximum number of characters.
        elipsis (str, optional): The elipsis to put at the end if the string is
        too long. This is removed from the maximum length. Defaults to '…'.

    Returns:
        str: The truncated string.
    """

    if s is None:
        return None

    if len(s) > n:
        return s[:n - len(elipsis)] + elipsis
    else:
        return s


def latency(start: datetime, end: datetime = None) -> str:
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


def get_traceback(lines: int,
                  offset: int = 1,
                  max_length: str = None) -> str:
    """
    Get the last few lines of the traceback as a string.

    Args:
        lines (int): The number of lines to retrieve. If this is 0, an empty
        string is returned.
        offset (int): The number of lines to offset in the stacktrace. Should
        probably be at least 1 to omit this call. Defaults to 1.
        max_length (str, optional): The maximum number of characters in the
        stacktrace string. Lines are removed if necessary to make it fit.
        Defaults to None.

    Returns:
        str: The stacktrace as a string.
    """

    tb = traceback.extract_stack()[-(lines + offset):-offset]
    stack = '\n'.join(traceback.format_list(tb)).strip()

    while len(stack) > max_length:
        if len(tb) == 1:
            return trunc(stack, max_length)
        else:
            tb = tb[1:]
            stack = '\n'.join(traceback.format_list(tb)).strip()

    return stack


def error_embed(error: Exception,
                text: str,
                title: str = 'Error',
                show_details: bool = True,
                show_traceback: bool = False):
    """
    Generate a fancy embed with info about an error.

    Args:
        error (Exception): The error.
        text (str): Text explaining what went wrong.
        title (str): The title of the embed. Defaults to 'Error'.
        show_details (bool, optional): Whether to add a field to the embed that
        gives the exception class name and the error message. Defaults to True.
        traceback (bool, optional): Whether to include the last few lines of
        the traceback in a field. This can be enabled even when show_details is
        False. Defaults to False.
    """

    # Build the initial embed
    embed = discord.Embed(
        title=title,
        description=text,
        color=settings.ERROR_EMBED_COLOR,
        timestamp=datetime.now(pytz.utc)
    )

    # Add exception details, if enabled
    if show_details:
        embed.add_field(
            name=trunc(error.__class__.__name__,
                       const.EMBED_FIELD_NAME_LENGTH),
            value=trunc(str(error), const.EMBED_FIELD_VALUE_LENGTH)
        )

    # Add traceback, if enabled
    if show_traceback:
        stack = get_traceback(
            settings.ERROR_TRACEBACK_LENGTH,
            2,
            const.EMBED_FIELD_VALUE_LENGTH - 8
        )

        if stack:
            embed.add_field(
                name='Traceback',
                value=f'```\n{stack}\n```'
            )

    return embed


async def handle_err(interaction: discord.Interaction,
                     error: Exception,
                     text: str,
                     title: str = 'Error',
                     show_details: bool = True,
                     show_traceback: bool = False,
                     deferred: bool = False):
    """
    Nicely handle generic errors, sending some info to the user in an embed and
    logging it.

    Args:
        interaction (discord.Interaction): The interaction to which to send the
        error message.
        error (Exception): The error.
        text (str): Text explaining what went wrong.
        title (str): The title of the embed. Defaults to 'Error'.
        show_details (bool, optional): Add details. Defaults to True.
        traceback (bool, optional): Add traceback. Defaults to False.
        deferred (bool, optional): Whether the interaction was deferred.
        Defaults to False.
    """

    # Build an embed to nicely display the error
    embed = error_embed(error, text, title, show_details, show_traceback)

    # Send the error message
    if deferred:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.response.send_message(embed=embed)

    _log.error(f'{text}: {error}')


async def handle_gphoto_err(interaction: discord.Interaction,
                            error: GPhoto2Error,
                            text: str,
                            deferred: bool = False):
    """
    Nicely handle an error from gPhoto2.

    Args:
        interaction (discord.Interaction): The interaction to which to send the
        error message.
        error (GPhoto2Error): The error.
        text (str): Text explaining what went wrong.
        deferred (bool, optional): Whether the interaction was deferred.
        Defaults to False.
    """

    # Build an embed to nicely display the error
    embed = error_embed(error, text, 'gPhoto2 Error',
                        show_details=False, show_traceback=False)

    # Add the error code and message
    err_str = trunc(error.string, const.EMBED_FIELD_VALUE_LENGTH)
    embed.add_field(
        name=f'Code: {error.code}',
        value=err_str
    )

    # Send the error message
    if deferred:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.response.send_message(embed=embed)

    _log.error(f'{text} (Code {error.code}): {err_str}')
