from configparser import ConfigParser
from collections import defaultdict
import os
import sys
import traceback

from .default_config_entry import DefaultConfigEntry
from . import default_values

# Move all the defaults into a dictionary
DEFAULTS: dict[str, DefaultConfigEntry] = {
    d: getattr(default_values, d) for d in dir(default_values)
    if isinstance(getattr(default_values, d), DefaultConfigEntry)
}


class Config:
    """
    A loader for program configuration. Checks environment variables
    followed by the config file. Loads configuration only on request,
    and then caches it.
    """

    def __init__(self, file):
        self.file = file
        self.cache: dict[str, any] = {}
        self.config: ConfigParser | None = None

    def __getattr__(self, key: str) -> any:
        """
        Get some configuration, and then cache it. This checks
        sources in the following order until finding a value:

        1. The cache of already-obtained configurations.
        2. Environment variables.
        3. The config file (loading that file if it was not
           already loaded).
        4. The defaults.

        If it's still not found (which should only be possible for
        settings that don't have a default value, such as the API
        key), this logs an error and exits.

        Args:
            key (str): The desired configuration.

        Returns:
            any: The value of the specified configuration.
        """

        if key in self.cache:
            return self.cache.get(key)

        # Ensure this is a valid config key
        if key in DEFAULTS:
            default = DEFAULTS[key]
        else:
            self._log_exit(f"Invalid configuration key '{key}'")
            return  # stops linter from complaining about 'default'

        # Check environment variables
        env = os.getenv(key)
        if env is not None:
            val = default.cast(env, key, self._log_exit)
            self.cache[key] = val
            return val

        # Check config file
        if self.config is None:
            self.reload()
        if self.config.has_option(default.section, key):
            val = self.config.get(default.section, key)
            # An empty string indicates the value is unset
            if val != '':
                val = default.cast(val, key, self._log_exit)
                self.cache[key] = val
                return val

        # Check defaults
        if default.has_default:
            self.cache[key] = default.value
            return default.value

        # Error and exit
        self._log_exit(f"Missing configuration for '{key}'. You "
                       "must specify a value in the config file: "
                       f"'{self.file}'")

    def reload(self, clear_cache=False):
        """
        Reload the configuration file. This will not affect
        processes that have already obtained configurations; only
        subsequent calls are affected.

        If self.file is not a valid file, it is created via
        self.save_file().

        Args:
            clear_cache (bool, optional): Clear the cache of
            already-obtained configurations.
        """

        if os.path.isfile(self.file):
            self.config = ConfigParser()
            self.config.read(self.file)
        else:
            self.config = self.save_file()

        if clear_cache:
            self.cache.clear()

    def save_file(self) -> ConfigParser:
        """
        Overwrite (or, more likely, create) the config file using
        all currently cached values and all default values.

        If self.file exists but is not a file, this logs an error
        and exits immediately.

        Returns:
            ConfigParser: The saved defaulted configuration.
        """

        if os.path.exists(self.file) and \
                not os.path.isfile(self.file):
            self._log_exit("Invalid configuration file at "
                           f"'{self.file}'. Is it a directory?")

        # Group defaults by section, and track whether this isn't
        # just the default configuration
        non_default = False
        sections = defaultdict(dict)
        for d, v in DEFAULTS.items():
            if d in self.cache:
                s = v.to_str(self.cache[d])
                non_default = non_default or s != v.value_str
            else:
                s = v.value_str

            sections[v.section][d] = s

        cfg = ConfigParser()
        for section, values in sections.items():
            cfg[section] = values

        # Write default configuration to file
        with open(self.file, 'w') as f:
            cfg.write(f)

        msg = (f"Saved the {'current' if non_default else 'default'} "
               f"configuration to '{self.file}'")
        if 'gphotobot.utils.logger' in sys.modules:
            from gphotobot.conf.logger_conf import log
            log.info(msg)
        else:
            print(msg)

        return cfg

    @staticmethod
    def _log_exit(msg: str) -> None:
        """
        Log some message, and then terminate the program. If the
        logger has been initialized, it is used. Otherwise,
        this just prints the message through sys.exit().

        Args:
            msg: The error message.

        Returns:
            None
        """

        if 'gphotobot.utils.logger' in sys.modules:
            from gphotobot.conf.logger_conf import log
            log.error(msg, stack_info=True, stacklevel=3)
            sys.exit(1)
        else:
            traceback.print_stack()
            sys.exit(msg)
