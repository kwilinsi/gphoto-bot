import asyncio
import datetime
import logging
from typing import Literal

import discord
from discord import Message
from discord.ext import commands

from .conf import settings
from gphotobot import cogs

_log = logging.getLogger(__name__)


class GphotoBot(commands.Bot):
    def __init__(self, sync_scope: Literal['dev', 'global', None]):
        """
        Initialize the bot.

        Args:
            sync (bool): Control whether to sync application commands.
            If 'dev', commands are synced with the development
            server. If 'global', they are synced with all servers.
            Otherwise, no syncing takes place.
        """

        super().__init__(
            command_prefix='!',
            intents=discord.Intents.default(),
            activity=discord.Activity(
                name='your webcam', type=discord.ActivityType.watching)
        )

        self.sync_scope = sync_scope

    async def setup_hook(self) -> None:
        _log.info(f"Logged on as {self.user} (ID: {self.user.id})")

        # Load extensions with cogs, sync application commands, and send the
        # startup message.
        extensions = [self.load_extension(ext.value)
                      for ext in cogs.Extensions]

        # noinspection PyTypeChecker
        await asyncio.gather(
            *extensions,
            self.startup_message(),
            self.sync_app_commands(self.sync_scope)
        )

    async def sync_app_commands(self,
                                scope: Literal['dev', 'global', None]) -> str:
        """
        Sync application commands, if enabled from command line --sync
        argument at runtime.

        Args:
            scope (str): Whether to sync globally ('global') or only with the
            development server ('dev') or not at all (None).

        Returns:
            str: The log message indicating what was synced (if anything).
        """

        if scope == 'dev':
            dev_guild = discord.Object(
                id=settings.DEVELOPMENT_GUILD_ID
            )
            self.tree.copy_global_to(guild=dev_guild)
            await self.tree.sync(guild=dev_guild)
            msg = (f'Synced application commands with dev guild '
                   f'(`id={dev_guild.id}`)')
        elif scope == 'global':
            await self.tree.sync()
            msg = 'Synced global application commands'
        else:
            msg = 'Syncing disabled'
            _log.debug(msg)
            return msg

        _log.info(msg)
        return msg

    async def startup_message(self) -> None:
        """
        Send a startup message to the log channel, if enabled.
        """

        if settings.LOG_CHANNEL_ID is not None:
            log_channel = self.get_channel(settings.LOG_CHANNEL_ID)
            if log_channel is None:
                log_channel = await self.fetch_channel(settings.LOG_CHANNEL_ID)

            time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            await log_channel.send(f'Started at {time}')

            _log.debug(f'Sent startup message ({time}) to '
                       f'{settings.LOG_CHANNEL_ID}')
