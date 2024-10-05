import datetime
import logging
from typing import Literal

import discord
from discord import Message
from discord.ext import commands

from .conf import settings

_log = logging.getLogger(__name__)


class GphotoBot(commands.Bot):
    def __init__(self, sync: Literal['dev', 'global', None]):
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
            activity=discord.Activity(name='your webcam', type=discord.ActivityType.watching)
        )

        self.sync = sync

    async def setup_hook(self) -> None:
        _log.info(f"Logged on as {self.user} (ID: {self.user.id})")

        # Load extensions with cogs
        await self.load_extension('gphotobot.cogs.ping')
        await self.load_extension('gphotobot.cogs.camera')

        # Sync application commands specified at runtime
        if self.sync == 'dev':
            dev_guild = discord.Object(
                id=settings.DEVELOPMENT_GUILD_ID
            )
            _log.info('Syncing application commands with dev guild '
                      f'(id={dev_guild.id})')
            self.tree.copy_global_to(guild=dev_guild)
            await self.tree.sync(guild=dev_guild)
        elif self.sync == 'global':
            _log.info('Syncing global application commands')
            await self.tree.sync()
        else:
            _log.debug('Syncing disabled')

        # Send a startup message to the log channel, if enabled
        if settings.LOG_CHANNEL_ID is not None:
            _log.debug(f'Sending startup message to {settings.LOG_CHANNEL_ID}')
            log_channel = self.get_channel(settings.LOG_CHANNEL_ID)
            if log_channel is None:
                log_channel = await self.fetch_channel(settings.LOG_CHANNEL_ID)
            
            time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            await log_channel.send(f'Started at {time}')
