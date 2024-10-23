from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Awaitable, Callable, Collection, Iterable, Optional

from discord import (app_commands, Embed, Interaction,
                     ui, utils as discord_utils)
from discord.ext import commands

from gphotobot import settings
from . import const

_log = logging.getLogger(__name__)


def list_to_str(items: Iterable[any],
                delimiter: str = ',',
                conjunction: Optional[str] = 'and',
                omit_empty: bool = False) -> str:
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
        omit_empty: Whether to ignore any items that are empty/None.
        Specifically, any items that don't resolve to the boolean True are
        skipped. (As in "if not item: skip it"). Defaults to False.

    Returns:
        A human-friendly string with the combined elements.
    """

    if items is None:
        return ""

    if not hasattr(items, '__len__'):
        items = tuple(items)

    if omit_empty:
        items = tuple(i for i in items if i)

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


def default_embed(**kwargs) -> Embed:
    """
    Generate an embed with the default color and the current timestamp. All
    parameters are passed to discord.Embed().

    Returns:
        discord.Embed: The new embed.
    """

    return Embed(
        color=settings.DEFAULT_EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
        **kwargs
    )


def app_command_name(interaction: Interaction | None) -> str:
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


async def update_interaction(interaction: Interaction[commands.Bot],
                             embed: Embed) -> None:
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


def get_button(parent: ui.View,
               label: str) -> Optional[ui.Button]:
    """
    Get the button attached to a parent view by specifying that buttons' label.

    Args:
        parent: The parent view.
        label: The current label of the desired button.

    Returns:
        The button, or None if no button with that label is found.
    """

    for child in parent.children:
        if isinstance(child, ui.Button):
            if child.label == label:
                return child

    return None


def deferred(callback: Callable[[Interaction, ...], Awaitable] | \
                       Callable[[Interaction], Awaitable]) -> \
        Callable[[Interaction], Awaitable]:
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

    async def defer(interaction: Interaction, *args, **kwargs) -> any:
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
