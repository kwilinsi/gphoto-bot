import logging

from discord import Color

from . import default_config_entry as dc

# The Discord API key has no applicable default
DISCORD_API_TOKEN = dc.DefaultConfigEntry('discord',
                                          has_default=False)

# The ID of the Guild (server) devoted to bot development
DEVELOPMENT_GUILD_ID = dc.DefaultConfigEntry(
    'discord',
    cast_func=int,
    expected='a Discord snowflake integer',
    has_default=False
)

# The ID of a log channel in Discord to send startup messages, etc.
LOG_CHANNEL_ID = dc.DefaultConfigEntry(
    'discord',
    cast_func=dc.to_optional_int,
    expected='a Discord snowflake integer, or empty',
)

# The minimum log level that goes to the console
LOG_LEVEL_CONSOLE = dc.DefaultConfigEntry(
    'log',
    logging.INFO,
    dc.to_log_level,
    'DEBUG, INFO, WARN, WARNING, ERROR, or CRITICAL'
)

# The minimum log level that goes to the log files
LOG_LEVEL_FILE = dc.DefaultConfigEntry(
    'log',
    logging.DEBUG,
    dc.to_log_level,
    'DEBUG, INFO, WARN, WARNING, ERROR, or CRITICAL'
)

# Max size of each log file in kilobytes (default = 5MB)
LOG_MAX_SIZE = dc.DefaultConfigEntry(
    'log',
    5120,
    dc.to_positive_int,
    'a positive integer'
)

# The number of log files to retain
LOG_BACKUP_COUNT = dc.DefaultConfigEntry(
    'log',
    5,
    dc.to_positive_int,
    'Expected an integer'
)

# Minimum log level for discord.py library internals
DISCORD_PY_LOG_LEVEL = dc.DefaultConfigEntry(
    'log',
    logging.WARNING,
    dc.to_log_level,
    'DEBUG, INFO, WARN, WARNING, ERROR, or CRITICAL'
)

# The default color of most embeds with generic info
DEFAULT_EMBED_COLOR = dc.DefaultConfigEntry(
    'messages',
    Color.teal(),
    dc.to_color,
    'Expected a color hex code'
)

# The color of embeds related to bot management
MANAGEMENT_EMBED_COLOR = dc.DefaultConfigEntry(
    'messages',
    Color.gold(),
    dc.to_color,
    'Expected a color hex code'
)

# The color of embeds with error messages
ERROR_EMBED_COLOR = dc.DefaultConfigEntry(
    'messages',
    Color(0xDA373C),
    dc.to_color,
    'Expected a color hex code'
)

# The number of lines of traceback to include in error embeds when traceback is
# enabled. If this is 0, traceback is forcibly disabled.
ERROR_TRACEBACK_LENGTH = dc.DefaultConfigEntry(
    'messages',
    4,
    dc.to_positive_int,
    'Expected an integer >=0'
)
