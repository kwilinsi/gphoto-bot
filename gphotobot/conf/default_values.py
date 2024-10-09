from functools import partial
import logging
from pathlib import Path

from discord import Color

from . import default_config_entry as dc

# The Discord API key has no applicable default
DISCORD_API_TOKEN = dc.DefaultConfigEntry(section='discord',
                                          has_default=False)

# The ID of the Guild (server) devoted to bot development
DEVELOPMENT_GUILD_ID = dc.DefaultConfigEntry(
    section='discord',
    cast_func=partial(dc.to_int, min_value=1),
    expected='a Discord snowflake integer',
    has_default=False
)

# The ID of a log channel in Discord to send startup messages, etc.
LOG_CHANNEL_ID = dc.DefaultConfigEntry(
    'discord',
    cast_func=partial(dc.to_int, min_value=1, optional=True),
    expected='a Discord snowflake integer, or empty/none'
)

################################################################################

# Username for MariaDB database
DATABASE_USERNAME = dc.DefaultConfigEntry(
    section='db',
    has_default=False
)

# Password for MariaDB database
DATABASE_PASSWORD = dc.DefaultConfigEntry(
    section='db',
    has_default=False
)

# MariaDB host
DATABASE_HOST = dc.DefaultConfigEntry(
    section='db',
    default='localhost',
    has_default=False
)

# MariaDB port number
DATABASE_PORT = dc.DefaultConfigEntry(
    section='db',
    default=3306,
    cast_func=partial(dc.to_int, min_value=1),
    expected='a port number'
)

# MariaDB database name
DATABASE_NAME = dc.DefaultConfigEntry(
    section='db',
    has_default=False
)

################################################################################

# The minimum log level that goes to the console
LOG_LEVEL_CONSOLE = dc.DefaultConfigEntry(
    section='log',
    default=logging.INFO,
    cast_func=dc.to_log_level,
    expected='DEBUG, INFO, WARN, WARNING, ERROR, or CRITICAL'
)

# The minimum log level that goes to the log files
LOG_LEVEL_FILE = dc.DefaultConfigEntry(
    section='log',
    default=logging.DEBUG,
    cast_func=dc.to_log_level,
    expected='DEBUG, INFO, WARN, WARNING, ERROR, or CRITICAL'
)

# Max size of each log file in kilobytes (default = 5MB)
LOG_MAX_SIZE = dc.DefaultConfigEntry(
    section='log',
    default=5120,
    cast_func=partial(dc.to_int, min_value=0),
    expected='a positive integer or 0'
)

# The number of log files to retain
LOG_BACKUP_COUNT = dc.DefaultConfigEntry(
    section='log',
    default=5,
    cast_func=partial(dc.to_int, min_value=0),
    expected='a positive integer or 0'
)

# Minimum log level for discord.py library internals
DISCORD_PY_LOG_LEVEL = dc.DefaultConfigEntry(
    section='log',
    default=logging.WARNING,
    cast_func=dc.to_log_level,
    expected='DEBUG, INFO, WARN, WARNING, ERROR, or CRITICAL'
)

################################################################################

# The default color of most embeds with generic info
DEFAULT_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color.teal(),
    cast_func=dc.to_color,
    expected='Expected a color hex code'
)

DISABLED_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color.dark_gray(),
    cast_func=dc.to_color,
    expected='Expected a color hex code'
)

# The color of embeds related to bot management
MANAGEMENT_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color.gold(),
    cast_func=dc.to_color,
    expected='Expected a color hex code'
)

# The color of embeds with error messages
ERROR_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color(0xDA373C),
    cast_func=dc.to_color,
    expected='Expected a color hex code'
)

# The number of lines of traceback to include in error embeds when traceback is
# enabled. If this is 0, traceback is forcibly disabled.
ERROR_TRACEBACK_LENGTH = dc.DefaultConfigEntry(
    section='messages',
    default=4,
    cast_func=partial(dc.to_int, min_value=0),
    expected='a positive integer or 0'
)

################################################################################

# The default root directory where new timelapses are placed. This is used
# whenever the user specifies a relative path or uses the default.
DEFAULT_TIMELAPSE_ROOT_DIRECTORY = dc.DefaultConfigEntry(
    section='camera',
    cast_func=dc.to_directory_path,
    expected="An absolute directory "
             "(doesn't need to exist, but can't be a file)",
    has_default=False
)

# The number of times to retry gPhoto commands if they fail with error code -53,
# indicating a busy USB device. If 0, no retries are attempted.
GPHOTO_MAX_RETRY_ATTEMPTS_ON_BUSY_USB = dc.DefaultConfigEntry(
    section='camera',
    default=3,
    cast_func=partial(dc.to_int, min_value=0),
    expected='Expected a positive integer or 0'
)

# The time to wait (in seconds) between retrying gPhoto commands that failed. If
# the max retry attempts is 0, this doesn't do anything.
GPHOTO_RETRY_DELAY = dc.DefaultConfigEntry(
    section='camera',
    default=1.5,
    cast_func=partial(dc.to_float, min_value=0),
    expected='Expected a positive number or 0'
)
