from datetime import datetime
import logging
import pytz
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from gphotobot.bot import GphotoBot
from gphotobot.utils import utils
from gphotobot.conf import APP_NAME, settings
from . import Extensions

_log = logging.getLogger(__name__)


@app_commands.guilds(settings.DEVELOPMENT_GUILD_ID)
class Manager(commands.GroupCog,
              group_name='manage',
              group_description=f'Manage {APP_NAME}'):
    def __init__(self, bot: GphotoBot):
        self.bot: GphotoBot = bot

    @staticmethod
    def make_embed(name: str,
                   description: str,
                   **kwargs) -> discord.Embed:
        """
        Make an embed designed for management messages. A timestamp with the
        current time is added automatically.

        Args:
            name (str): The name to put after "Management |" in the title.
            description (str): The body text.

        Returns:
            discord.Embed: The embed.
        """

        return discord.Embed(
            title=f'Management | {name}',
            color=settings.MANAGEMENT_EMBED_COLOR,
            description=description,
            timestamp=datetime.now(pytz.utc),
            **kwargs
        )

    @app_commands.command(extras={'defer': True},
                          description='Sync application commands with Discord')
    @app_commands.describe(scope='Whether to sync command globally or '
                                 'only with the dev guild')
    async def sync(self,
                   interaction: discord.Interaction[commands.Bot],
                   scope: Literal['global', 'dev']):
        """
        Sync application commands (either globally or only to the development
        server) with Discord.

        Args:
            interaction (discord.Interaction[commands.Bot]): The interaction.\
            scope (Literal['global', 'dev']): Whether to sync commands globally
            or only with the development guild.
        """

        # Defer a response (syncing could take a little while)
        await interaction.response.defer(thinking=True)

        # Sync app commands
        msg = await self.bot.sync_app_commands(scope)

        # Send success message
        await interaction.followup.send(embed=self.make_embed('Sync', msg))

    @app_commands.command(extras={'defer': True},
                          description='Reload a bot extension')
    @app_commands.describe(extension='The name of the extension to reload')
    async def reload(self,
                     interaction: discord.Interaction[commands.Bot],
                     extension: Extensions):

        # Defer a response
        await interaction.response.defer(thinking=True)

        # Reload the extension
        try:
            await self.bot.reload_extension(extension.value)

            # Return success message
            await interaction.followup.send(embed=self.make_embed(
                'Reload',
                f"Successfully reloaded `{extension.name}` extension."
            ))
            return

        except commands.ExtensionFailed as e:
            text = (f"Failed to reload `{extension.name}` extension. The "
                    f"`setup()` function encountered an error. Bot reverted "
                    f"to original state.")
            error = e.original
            traceback = True
        except commands.ExtensionNotFound as e:
            text = (f"Unexpected error: couldn't find the `{extension.name}` "
                    f"extension. Bot reverted to original state.")
            error = e
            traceback = False
        except commands.NoEntryPointError as e:
            text = (f"Failed to reload `{extension.name}` extension: it's "
                    f"missing a `setup()` function.")
            error = e
            traceback = False
        except commands.ExtensionNotLoaded as e:
            text = f"Failed to reload `{extension.name}` extension."
            error = e
            traceback = False

        # Send an error message
        await utils.handle_err(
            interaction=interaction,
            error=error,
            text=text,
            log_text=text[:-1],
            title='Error Reloading',
            show_traceback=traceback
        )


async def handle_app_command_error(
        interaction: discord.Interaction[commands.Bot],
        error: app_commands.AppCommandError) -> None:
    """
    This function handles errors from all app commands across all cogs. It
    is activated by cog_load() on this manager cog.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction.
        error (app_commands.AppCommandError): The error.
    """

    # Get the command name
    command = utils.app_command_name(interaction)

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
    except KeyboardInterrupt:
        raise
    except:
        # If there's an error handling the error, we have big problems
        _log.critical(
            f"Failed to handle an {error.__class__.__name__} error "
            f"raised while processing '{command}'",
            exc_info=True
        )


async def setup(bot: GphotoBot):
    """
    Setup this extension. Add the Manager cog, and implement global error
    handling for app commands.

    Args:
        bot (GphotoBot): The bot.
    """

    await bot.add_cog(Manager(bot))
    _log.info('Loaded Manager cog')

    bot.old_tree_error = bot.tree.on_error
    bot.tree.on_error = handle_app_command_error


async def teardown(bot: GphotoBot):
    """
    Runs when this extension is unloaded. Revert error handling to default.

    Args:
        bot (GphotoBot): The bot.
    """

    _log.info('Unloaded Manager cog')
    bot.tree.on_error = bot.old_tree_error
