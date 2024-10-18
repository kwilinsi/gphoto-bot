import logging

from gphotobot.bot import GphotoBot

from .timelapse_cog import TimelapseCog

_log = logging.getLogger(__name__)


async def setup(bot: GphotoBot):
    await bot.add_cog(TimelapseCog(bot))
    _log.info('Loaded Timelapse cog')
