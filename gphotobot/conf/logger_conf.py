import coloredlogs
import logging.handlers
import os
from pathlib import Path

from gphotobot.conf import settings, DATA_DIR, APP_NAME


def configure():
    # Configure root logger
    root = logging.getLogger()

    # Create logs directory if it doesn't exist
    log_dir: Path = DATA_DIR / 'logs'
    log_dir.mkdir(exist_ok=True)

    # Add file handler to root
    file = logging.handlers.RotatingFileHandler(
        log_dir / (APP_NAME + '.log'),
        maxBytes=settings.LOG_MAX_SIZE * 1024,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file.setLevel(settings.LOG_LEVEL_FILE)
    file.setFormatter(logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d - %(process)05d '
            '%(threadName)-15.15s %(name)-20.20s %(levelname)-8s '
            '%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    root.addHandler(file)

    # Set colors for fields
    field_styles = {
        'asctime': {'color': 'green', 'bright': True},
        'process': {'color': 'blue'},
        'threadName': {'color': 'blue', 'bright': True},
        'levelname': {'color': 'white', 'bright': True},
        'module': {'color': 'cyan'}
    }

    # Set colors for message text at each level
    level_styles = {
        'debug': {'color': 'white', 'faint': True},
        'info': {'color': 'green', 'bright': True},
        'warning': {'color': 'yellow', 'bright': True},
        'error': {'color': 'red', 'bright': True},
        'critical': {'color': 'red', 'bold': True},
    }

    # Add console handler (with color) to root
    coloredlogs.install(
        level=settings.LOG_LEVEL_CONSOLE,
        logger=root,
        fmt='%(asctime)s %(process)d %(threadName)-10.10s '
            '%(module)-8.8s %(levelname)-8s %(message)s',
        datefmt='%H:%M:%S',
        field_styles=field_styles,
        level_styles=level_styles,
    )

    # Set global level to the broadest configured output
    root.setLevel(min(settings.LOG_LEVEL_CONSOLE,
                      settings.LOG_LEVEL_FILE))

    # Set log level for discord.py internals
    discord = logging.getLogger('discord')
    discord.setLevel(settings.DISCORD_PY_LOG_LEVEL)
