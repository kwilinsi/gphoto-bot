from functools import partial
import logging

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
    expected='a color hex code'
)

DISABLED_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color.dark_gray(),
    cast_func=dc.to_color,
    expected='a color hex code'
)

# The color of embeds related to bot management
MANAGEMENT_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color.gold(),
    cast_func=dc.to_color,
    expected='a color hex code'
)

# The color of embeds with error messages
ERROR_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color(0xDA373C),
    cast_func=dc.to_color,
    expected='a color hex code'
)

# The color of embeds with error messages that have been disabled
DISABLED_ERROR_EMBED_COLOR = dc.DefaultConfigEntry(
    section='messages',
    default=Color(0x40191b),
    cast_func=dc.to_color,
    expected='a color hex code'
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

# The number of times to retry gPhoto commands if they fail with error code -53,
# indicating a busy USB device. If 0, no retries are attempted.
GPHOTO_MAX_RETRY_ATTEMPTS_ON_BUSY_USB = dc.DefaultConfigEntry(
    section='camera',
    default=3,
    cast_func=partial(dc.to_int, min_value=0),
    expected='a positive integer or 0'
)

# The time to wait (in seconds) between retrying gPhoto commands that failed. If
# the max retry attempts is 0, this doesn't do anything.
GPHOTO_RETRY_DELAY = dc.DefaultConfigEntry(
    section='camera',
    default=1.5,
    cast_func=partial(dc.to_float, min_value=0),
    expected='a positive number or 0'
)

################################################################################

# The default root directory where new timelapses are placed. This is used
# whenever the user specifies a relative path or uses the default.
DEFAULT_TIMELAPSE_ROOT_DIRECTORY = dc.DefaultConfigEntry(
    section='timelapse',
    cast_func=dc.to_directory_path,
    expected="an absolute directory "
             "(doesn't need to exist, but can't be a file)",
    has_default=False
)

# The timelapse coordinator coordinates the execution of timelapses. This delay
# controls how often (in minutes) it refreshes the list of timelapses from the
# database. (It also updates when a user specifically modifies a timelapse.
# This is just a fail-safe in case the database itself was modified).
TIMELAPSE_COORDINATOR_REFRESH_DELAY = dc.DefaultConfigEntry(
    section='timelapse',
    cast_func=partial(dc.to_float, min_value=1),
    expected="a time in minutes (at least 1)",
    default=15
)

################################################################################

# The emoji for use in a Done/Confirm button
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:check_circle:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=check&icon.size=24&icon.color=%23edeff2
EMOJI_DONE_CHECK = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for use in a Save button
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:save:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=save&icon.size=24&icon.color=%23edeff2
EMOJI_SAVE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for use in an Info button
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:info:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=info&icon.size=24&icon.color=%23edeff2
EMOJI_INFO = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='ℹ'
)

# The emoji for use in a Cancel button. Note that this usually appears on top of
# a red button, which makes it difficult, as Discord doesn't have a white X
# emoji. Use None to disable the emoji (as is default).
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:cancel:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=canc&icon.size=24&icon.color=%23edeff2
EMOJI_CANCEL = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for use in a Close button
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:close:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=cancel&icon.size=24&icon.color=%23edeff2
EMOJI_CLOSE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for use in an Edit/Change/Modify button
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:edit:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=edit&icon.size=24&icon.color=%23edeff2
EMOJI_EDIT = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for use in a button to set/change a directory
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:folder_open:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=file&icon.size=24&icon.color=%23edeff2
EMOJI_DIRECTORY = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='📁'
)

# The emoji for setting a timelapse interval
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:timelapse:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=time&icon.size=24&icon.color=%23edeff2
EMOJI_TIME_INTERVAL = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='⏱️'
)

# The emoji for picking a camera
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:photo_camera:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=camera&icon.size=24&icon.color=%23edeff2
EMOJI_CAMERA = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for a preview image
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:preview:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=preview&icon.size=24&icon.color=%23edeff2
EMOJI_PREVIEW_IMAGE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for setting a start/end time
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:schedule:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=time&icon.size=24&icon.color=%23edeff2
EMOJI_SET_RUNTIME = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='🕓'
)

# The emoji for changing an existing start/end time
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:update:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=time&icon.size=24&icon.color=%23edeff2
EMOJI_CHANGE_TIME = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='🕓'
)

# The emoji for creating a timelapse schedule
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:calendar_month:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=schedule&icon.size=24&icon.color=%23edeff2
EMOJI_CREATE_SCHEDULE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='🗓️'
)

# The emoji for removing a timelapse schedule
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:calendar_add_on:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=schedule&icon.size=24&icon.color=%23edeff2
EMOJI_ADD_SCHEDULE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for editing an existing timelapse schedule
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:edit_calendar:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=schedule&icon.size=24&icon.color=%23edeff2
EMOJI_EDIT_SCHEDULE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='🗓️'
)

# The emoji for removing a timelapse schedule
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:event_busy:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=calendar&icon.size=24&icon.color=%23edeff2
EMOJI_REMOVE_SCHEDULE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for removing a timelapse schedule
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:event_available:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=schedule&icon.size=24&icon.color=%23edeff2
EMOJI_SCHEDULE_DONE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for deleting something
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:delete:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=delete&icon.size=24&icon.color=%23edeff2
EMOJI_DELETE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='🗑'
)

# The emoji for a back button
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:arrow_back:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=back&icon.size=24&icon.color=%23edeff2
EMOJI_BACK = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='◀'
)

# The emoji for moving/swapping something around in a list
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:swap_vert:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=arrow&icon.size=24&icon.color=%23edeff2
EMOJI_MOVE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

# The emoji for moving something up in a list
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:move_up:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=move&icon.size=24&icon.color=%23edeff2
EMOJI_MOVE_UP = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='⬆'
)

# The emoji for moving something down in a list
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:move_down:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=move&icon.size=24&icon.color=%23edeff2
EMOJI_MOVE_DOWN = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='⬇'
)

# The emoji for starting a timelapse that's run manually
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:not_started:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=start&icon.size=24&icon.color=%23edeff2
EMOJI_START = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='▶'
)

# The emoji for stopping a timelapse that is triggered manually
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:stop_circle:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=pause&icon.size=24&icon.color=%23edeff2
EMOJI_STOP = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='⏹'
)

# The emoji for continuing a finished timelapse past when it stopped
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:not_started:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=start&icon.size=24&icon.color=%23edeff2
EMOJI_CONTINUE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='▶'
)

# The emoji for pausing a running timelapse
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:pause_circle:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=pause&icon.size=24&icon.color=%23edeff2
EMOJI_PAUSE = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='⏸'
)

# The emoji for resuming a paused timelapse
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:resume:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=resume&icon.size=24&icon.color=%23edeff2
EMOJI_RESUME = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default='▶'
)

# The emoji for accessing the gallery for a particular timelapse
# Recommended custom emoji: https://fonts.google.com/icons?selected=Material+Symbols+Outlined:imagesmode:FILL@0;wght@300;GRAD@200;opsz@24&icon.query=images&icon.size=24&icon.color=%23edeff2
EMOJI_GALLERY = dc.DefaultConfigEntry(
    section='emoji',
    cast_func=dc.to_nullable_string,
    default=None
)

################################################################################

SOURCE_CODE_LINK = dc.DefaultConfigEntry(
    section='miscellaneous',
    default='https://github.com/kwilinsi/gphoto-bot',
)
