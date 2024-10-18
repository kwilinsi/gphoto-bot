from pathlib import Path
import sys
import traceback

from platformdirs import PlatformDirs

from .config import Config

# The name and author of the program. Used to get the data directory
APP_NAME = 'gPhoto'
APP_AUTHOR = 'gphoto-bot'
_CONFIGURATION_FILE_NAME = 'config.ini'

_PLATFORM_DIRS = PlatformDirs('gphoto-bot', ensure_exists=True)
CONFIG_DIR = Path(_PLATFORM_DIRS.user_config_dir)
DATA_DIR = Path(_PLATFORM_DIRS.user_data_dir)
TMP_DATA_DIR = DATA_DIR / 'tmp'

# Ensure platform dirs exist
if not CONFIG_DIR.is_dir():
    sys.exit("Error: Could not create configuration directory at "
             f"'{CONFIG_DIR}'")
if not DATA_DIR.is_dir():
    sys.exit("Error: Could not create data directory at "
             f"'{DATA_DIR}'")

# Make the 'tmp' directory
try:
    TMP_DATA_DIR.mkdir(exist_ok=True)
except OSError as e:
    traceback.print_exc()
    sys.exit(f"Failed to created tmp data directory at '{TMP_DATA_DIR}': {e}")

# Initialize the settings
settings = Config(CONFIG_DIR / _CONFIGURATION_FILE_NAME)
