import os
import sys

from platformdirs import PlatformDirs

from .config import Config

# The name and author of the program. Used to get the data directory
APP_NAME = 'gPhoto'
APP_AUTHOR = 'gphoto-bot'
_CONFIGURATION_FILE_NAME = 'config.ini'

_PLATFORM_DIRS = PlatformDirs('gphoto-bot', ensure_exists=True)
CONFIG_DIR = _PLATFORM_DIRS.user_config_dir
DATA_DIR = _PLATFORM_DIRS.user_data_dir

# Ensure platform dirs exist
if not os.path.isdir(CONFIG_DIR):
    sys.exit("Error: Could not create configuration directory at "
             f"'{CONFIG_DIR}'")
if not os.path.isdir(DATA_DIR):
    sys.exit("Error: Could not create data directory at "
             f"'{DATA_DIR}'")

settings = Config(os.path.join(CONFIG_DIR, _CONFIGURATION_FILE_NAME))
