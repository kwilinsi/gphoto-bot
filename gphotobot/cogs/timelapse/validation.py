import logging
import os
from pathlib import Path
import re
from typing import Literal, Optional

from discord import Embed
from sqlalchemy import func, select

from gphotobot import settings, utils
from gphotobot.sql import async_session_maker
from gphotobot.sql.models.timelapses import (Timelapse, NAME_MAX_LENGTH,
                                             DIRECTORY_MAX_LENGTH)

_log = logging.getLogger(__name__)


class InvalidTimelapseNameError(Exception):
    def __init__(self,
                 name: str,
                 problem: Literal['taken', 'taken_case', 'length',
                 'char', 'start_char'],
                 is_shortened: bool):
        """
        Initialize an exception that explains what's wrong about a particular
        user-attempted name.

        The recognized problems are:
        - 'taken': This name is already used by another timelapse in the db.
        - 'taken_case': The same as 'taken' except that the names are
        capitalized differently.
        - 'length': The name exceeds the maximum length.
        - 'char': The name uses one or more invalid characters.
        - 'start_char': The name starts with an invalid character.

        Args:
            name: The name the user attempted to use. More specifically, the
            name that makes the most sense for explaining the issue to the
            user. If the name had consecutive underscores, this may or may not
            have them removed.
            problem: The reason the name is invalid.
            is_shortened: Whether consecutive hyphens/underscores were
            shortened into a single character.
        """

        super().__init__()
        self.name = name
        self.problem = problem
        self.is_shortened = is_shortened

    def build_embed(self) -> Embed:
        """
        Build an embed that explains in user-friendly terms what's wrong with
        the name they tried to use.

        Returns:
            A new embed.
        """

        # Build a user-friendly message explaining what they did wrong

        if self.problem == 'taken' or self.problem == 'taken_case':
            msg = (f"Sorry, there is already a timelapse called "
                   f"**\"{self.name}\"** in the database. You must "
                   f"choose a unique name to create a timelapse.")
            if self.problem == 'taken_case':
                msg += ("\n\nDifferent capitalization doesn't count: \"name\" "
                        "and \"NaMe\" are not sufficiently unique.")
        elif self.problem == 'too_long':
            name_trunc = utils.trunc(self.name, NAME_MAX_LENGTH,
                                     escape_markdown=True)
            msg = (f"Sorry, your timelapse name **\"{name_trunc}**\" is too "
                   f"long. Timelapse names can't be longer than "
                   f"{NAME_MAX_LENGTH} characters.")
        elif self.problem == 'char':
            # Explain which characters are allowed. Include the lines about
            # starting with a letter and not having spaces only if the user
            # violated those parts

            name_esc = utils.trunc(self.name, NAME_MAX_LENGTH,
                                   escape_markdown=True)
            msg = (f"Sorry, your timelapse name **\"{name_esc}\"** isn't "
                   "valid. Names can only use letters, numbers, hyphens, and "
                   "underscores.")
            if not self.name[0].isalpha():
                msg = msg[:-1] + ', and they must start with a letter.'
            if re.search(r'\s', self.name):
                msg += ' Spaces are not allowed.'
        elif self.problem == 'start_char':
            msg = (f"Sorry, your timelapse name **\"{self.name}\"** "
                   "isn't valid. Names must __start with a letter__ and use "
                   "only letters, numbers, hyphens, and underscores.")
        else:
            raise ValueError(f"Unreachable: problem='{self.problem}'")

        # Put the error message in an embed
        embed = utils.contrived_error_embed(
            text=msg,
            title='Error: Invalid Name'
        )

        # If the user had multiple hyphens/underscores, add a note about that
        if self.is_shortened:
            embed.add_field(
                name='Note',
                value='Multiple consecutive hyphens/underscores '
                      'are automatically shortened to just one.',
                inline=False
            )

        return embed


async def validate_name(name: str) -> str:
    """
    Validate a new timelapse name and return it.

    Args:
        name: The name to validate.

    Returns:
        The validated name. This may be different from the input name.

    Raises:
        InvalidTimelapseNameError: If the name is invalid.
    """

    # Consolidate consecutive hyphens/underscores
    n = re.sub(r'([_-])[-_]+', r'\1', name)
    is_shortened = name != n

    if len(n) > NAME_MAX_LENGTH or len(n) < 1:
        raise InvalidTimelapseNameError(n, 'length', is_shortened)

    if re.search(r'[^\w-]', n):
        raise InvalidTimelapseNameError(name, 'char', is_shortened)

    if not n[0].isalpha():
        raise InvalidTimelapseNameError(name, 'start_char', is_shortened)

    # Check database for duplicate name
    async with async_session_maker() as session:  # read-only session
        stmt = (select(Timelapse)
                .where(func.lower(Timelapse.name) == n.lower()))
        result: Timelapse = (await session.scalars(stmt)).first()
        if result is not None:
            raise InvalidTimelapseNameError(
                n, 'taken' if result.name == n else 'taken_case', is_shortened
            )

    return n


def validate_directory(directory: str) -> Path:
    """
    Validate a new directory path, and return it as a pathlib Path. If the input
    directory isn't absolute, it is appended to the default timelapse directory
    root.

    Args:
        directory: The directory to validate.

    Returns:
        The validated name.

    Raises:
        ValidationError: If the directory is invalid.
    """

    if not directory:
        raise utils.ValidationError(msg='You must specify a directory.')

    # Record whether it's already too long; might use this later. (Note that
    # this function is not structured optimally for speed. It's meant to give
    # the most helpful error message).
    base_is_too_long: bool = len(directory) > DIRECTORY_MAX_LENGTH

    # If it's not absolute, resolve it from the default timelapse root dir
    directory = Path(directory)
    if directory.is_absolute():
        note = ''
    else:
        note = (" (Note: relative paths are resolved from the default "
                "timelapse root directory: "
                f"`{settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY}`).")
        directory = settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY / directory

    # Can't be a file
    if directory.is_file():
        ext = utils.trunc(directory.suffix, 50, escape_markdown=True)
        name = utils.trunc(
            directory.name, 100, ellipsis_str=ext, escape_markdown=True
        )
        raise utils.ValidationError(
            msg=f"**{name}** is a file, not a directory." + note
        )

    # Can't have stuff in it
    if directory.is_dir() and any(directory.iterdir()):
        # Get a string pointing to the last bit of the path
        root: Path = Path(directory.root)
        if directory == root:
            name, reverse = str(directory), False
        elif directory.parent == root or directory.parent.parent == root:
            name, reverse = str(directory), True
        else:
            name = os.path.join('…', directory.parent.name, directory.name)
            reverse = True

        name = utils.trunc(name, 100, escape_markdown=True, reverse=reverse)
        n = len(list(directory.iterdir()))

        raise utils.ValidationError(
            msg=f"The timelapse directory must be empty, but **{name}** "
                f"contains {n} item{'' if n == 1 else 's'}." + note
        )

    # Can't be too long
    if len(str(directory)) > DIRECTORY_MAX_LENGTH:
        raise utils.ValidationError(
            msg=f"The directory path must not exceed {DIRECTORY_MAX_LENGTH} "
                "characters." + ('' if base_is_too_long else note)
        )

    return directory


def determine_default_directory(name: str) -> Optional[Path]:
    """
    Given a timelapse name, pick a default directory in which to store its
    pictures. The directory is not created, but it may already exist. However,
    if it does exist, it's guaranteed to be empty.

    The path must fit within the DIRECTORY_MAX_LENGTH. If no directory can be
    found that meets this condition, the default directory will be None.

    Args:
        name: The name of the timelapse.

    Returns:
        The path to the automatically chosen directory. Or, if it's impossible
        to pick a directory without exceeding the maximum length, None.
    """

    root: Path = settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY

    # If the timelapse root doesn't exist, it's guaranteed that 'root / name'
    # doesn't have anything in it
    if not root.exists():
        d = root / name
        return d if len(str(d)) <= DIRECTORY_MAX_LENGTH else None

    # This shouldn't ever happen, but it's possible that the default timelapse
    # root dir was created as a file since the program started
    new: Path = utils.get_unique_path(root, lambda p: not p.is_file())
    if new != root:
        _log.warning(f"The default timelapse directory is a file: '{root}'. "
                     f"Changing it to '{new}'")
        settings.DEFAULT_TIMELAPSE_ROOT_DIRECTORY = new
        root = new

    # Try using the timelapse name as a directory name. If that doesn't work,
    # keep adding numbers to it until it does.
    d = utils.get_unique_path(
        root / name,
        lambda p: not p.exists() or  # Either doesn't exist, or
                  (p.is_dir() and not any(p.iterdir()))  # empty directory
    )

    return d if len(str(d)) <= DIRECTORY_MAX_LENGTH else None
