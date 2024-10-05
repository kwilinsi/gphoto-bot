import logging

import discord
from discord.app_commands.errors import AppCommandError
from discord.ext import commands

from gphotobot.utils import utils

_log = logging.getLogger(__name__)


class Manager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot


async def handle_app_command_error(
        interaction: discord.Interaction[commands.Bot],
        error: AppCommandError) -> None:
    """
    This function handles errors from all app commands across all cogs. It
    is activated by cog_load() on this manager cog.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction.
        error (AppCommandError): The error.
    """

    # Get the slash command
    command = '/' + interaction.command.name

    try:
        # Switch to the original error if available
        if isinstance(error, discord.app_commands.CommandInvokeError):
            error = error.original

        # Send an error response in Discord, and log the error and stacktrace
        await utils.handle_err(
            interaction,
            error,
            f"Unexpected error while processing `{command}`.",
            log_text=f"Error processing '{command}'",
            show_details=True,
            show_traceback=True
        )
    except:
        # If there's an error handling the error, we have big problems
        _log.critical(
            f"Failed to handle an {error.__class__.__name__} error "
            f"raised while processing '{command}'",
            exc_info=True
        )


async def setup(bot: commands.Bot):
    """
    Setup this extension. Add the Manager cog, and implement global error
    handling for app commands.

    Args:
        bot (commands.Bot): The bot.
    """

    await bot.add_cog(Manager(bot))
    _log.debug('Loaded Manager cog')

    bot.old_tree_error = bot.tree.on_error
    bot.tree.on_error = handle_app_command_error


async def teardown(bot: commands.Bot):
    """
    Runs when this extension is unloaded. Revert error handling to default.

    Args:
        bot (commands.Bot): The bot.
    """

    bot.tree.on_error = bot.old_tree_error
