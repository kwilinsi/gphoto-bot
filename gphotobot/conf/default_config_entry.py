import logging
import os.path
from pathlib import Path
from typing import Callable, Optional

from discord import Color


class DefaultConfigEntry:
    def __init__(self,
                 section: str,
                 default: any = None,
                 cast_func: Callable[[str], any] | None = None,
                 expected: str | None = None,
                 has_default: bool = True):
        """
        Args:
            section (str): The name of the section in the config file
            in which this option is stored.
            default: The default value.
            cast_func: Function to cast a string value to the
            appropriate data type.
            expected: If casting fails, this string is included in
            the error message to indicate what input was expected.
            It immediately follows the word "expected."
            has_default: Whether there is a default value at all.
        """

        self.section = section
        self.value = default
        self.cast_func = cast_func
        self.expected = expected
        self.has_default = has_default

        # The value as a string for saving to the config file
        self.value_str = self.to_str(default)

    def cast(self,
             string: str,
             name: str,
             on_error: Callable[[str], None]) -> any:
        """
        Cast a string value to the appropriate data type.

        Args:
            string: The value to cast
            name: The name of this configuration.
            on_error: A function to call with an error string in
            the event that casting fails.

        Returns:
            The casted value.
        """

        try:
            if self.cast_func:
                return self.cast_func(string)
            else:
                return string
        except KeyboardInterrupt:
            raise
        except Exception as e:
            msg = f"Invalid value '{string}' for '{name}': {e}"
            if self.expected:
                msg += '. Expected ' + self.expected
            on_error(msg)

    def to_str(self, value: any) -> str:
        """
        Convert some value to a string to be saved in the config file.
        If this does not have a default value and the given value is
        None, an empty string is returned instead of "None". Also,
        if the cast function is to_log_level(), indicating that this
        is a log, then an integer value is encoded with
        logging.getLevelName().

        Args:
            value: The value to save.

        Returns:
            The value as a string.
        """

        if value is None and not self.has_default:
            return ''
        elif self.cast_func == to_log_level and \
                isinstance(value, int):
            return logging.getLevelName(value)
        else:
            return str(value)


def to_nullable_string(s: Optional[str]) -> Optional[str]:
    """
    Take a string and detect whether it is "None" (or similar). If so, return
    None. Otherwise, just return the input string unmodified.

    This recognizes the following inputs as None. Note that all comparisons are
    case-insensitive and ignore leading and trailing whitespace:

    - None (not a string)
    - 'none'
    - 'null'
    - 'nil'
    - '' (an empty string)

    Args:
        s: The input string.

    Returns:
        Either the input string or None.
    """

    if s is None or s.lower().strip() in ('none', 'null', 'nil', ''):
        return None
    else:
        return s


def to_log_level(s: str) -> int:
    """
    Cast a log level string to the appropriate integer. If the string
    casts directly to an integer, it uses that. Otherwise, it's fed
    to logging.getLevelName().

    Args:
        s: The string to cast.

    Returns:
        The integer level.
    """

    try:
        return int(s)
    except ValueError:
        return logging.getLevelName(s)


def to_int(s: Optional[str],
           min_value: Optional[int] = None,
           max_value: Optional[int] = None,
           optional: bool = False) -> Optional[int]:
    """
    Cast a string to an integer, and require it to be within the given range.
    Use None for the min or max values to disable that constraint. If both the
    min and max value are None, this is identical to casting with int().

    The integer can also be made optional altogether by specifying
    optional=True. If it's optional, then input that is empty, blank (only
    whitespace), None, or the literal strings 'none', 'null', or 'nil'
    (case in-sensitive) return None.

    Args:
        s (Optional[str]): The string to cast.
        min_value (Optional[int], optional): The minimum accepted integer
        (inclusive). If None, there is no minimum. Defaults to None.
        max_value (Optional[int], optional): The maximum accepted integer
        (inclusive). If None, there is no maximum. Defaults to None.
        optional (bool): Whether any integer is required at all. Defaults to
        False.

    Returns:
        Optional[int]: The integer. This can only be None when optional=True.

    Raises:
        ValueError: If s is not an integer.
        AssertionError: If s is not within the given range.
    """

    if optional:
        if s is None or not s.strip() or s.lower() in ('none', 'null', 'nil'):
            return None

    i = int(s)
    if min_value is not None:
        assert i >= min_value
    if max_value is not None:
        assert i <= max_value
    return i


def to_float(s: Optional[str],
             min_value: Optional[float] = None,
             max_value: Optional[float] = None,
             optional: bool = False) -> Optional[float]:
    """
    This is identical to to_int() except that it processes floats.

    Args:
        s (Optional[str]): The string to cast.
        min_value (Optional[float], optional): The minimum accepted float.
        Defaults to None.
        max_value (Optional[float], optional): The maximum accepted float.
        Defaults to None.
        optional (bool): Whether a float is required at all. Defaults to False.

    Returns:
        Optional[float]: The float, or None if no float was given.

    Raises:
        ValueError: If s is not a float.
        AssertionError: If s is not within the given range.
    """

    if optional:
        if s is None or not s.strip() or s.lower() in ('none', 'null', 'nil'):
            return None

    f = float(s)
    if min_value is not None:
        assert f >= min_value
    if max_value is not None:
        assert f <= max_value
    return f


def to_color(color: Optional[str]) -> Optional[Color]:
    """
    Attempt to parse a string with a color in it. This is similar to
    discord.Color.from_str(), except that it supports None/empty strings and
    hex codes without the # sign.

    Args:
        color (Optional[str]): The color as a string.

    Returns:
        Optional[Color]: The parsed color.
    
    Raises:
        Error: If the color is unparseable.
    """

    if not color:
        return None

    if len(color) == 6:
        try:
            return Color(int(color, 16))
        except ValueError:
            pass

    return Color.from_str(color)


def to_directory_path(directory: Optional[str]) -> Path:
    """
    Take a given directory and convert it to a Path. Ensure that it is (a)
    absolute, and (b) isn't a file. It doesn't need to exist as a directory
    yet, though.

    Args:
        directory (Optional[str]): The directory as a string.

    Returns:
        Path: The validated Path.

    Raises:
        AssertionError: If the path is relative or a file.
    """

    path = Path(directory)
    assert path.is_absolute() and not path.is_file()
    return path
