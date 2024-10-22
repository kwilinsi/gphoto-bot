import logging

from gphotobot.bot import GphotoBot
from .timelapse_cog import TimelapseCog
from .execute.coordinator import Coordinator
from . import execute

_log = logging.getLogger(__name__)


async def setup(bot: GphotoBot):
    await bot.add_cog(TimelapseCog(bot))
    _log.info('Loaded Timelapse cog')

    execute.TIMELAPSE_COORDINATOR = Coordinator(bot)
    await bot.add_cog(execute.TIMELAPSE_COORDINATOR)
    _log.info('Loaded timelapse Coordinator cog')


async def teardown(_: GphotoBot):
    _log.info('Tearing down timelapse extension')
    await execute.TIMELAPSE_COORDINATOR.clean_up()
    execute.TIMELAPSE_COORDINATOR.cancel()
    execute.TIMELAPSE_COORDINATOR = None
