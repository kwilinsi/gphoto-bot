from argparse import ArgumentParser, Namespace
import logging

import asyncio
import gphoto2 as gp

from . import sql
from .bot import GphotoBot
from .conf import logger_conf, settings
from .libgphoto import gmanager, NoCameraFound


def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        '--sync', '-s',
        choices=['dev', 'global'],
        default=None,
        help="Sync application commands. Use 'dev' to sync with the "
             "development guild and 'global' to sync everywhere."
    )
    return parser.parse_args()


async def main(args: Namespace):
    # Configure the logger
    logger_conf.configure()
    log = logging.getLogger(__name__)

    # Enable gPhoto2 logging
    gp.use_python_logging()

    # Create database tables
    log.info('Initialize database connection...')
    await sql.initialize()

    # Detect and cache cameras
    log.info('Loading cameras...')
    try:
        await gmanager.all_cameras(force_reload=True)
    except NoCameraFound:
        log.warning("ALERT: No cameras detected! You won't be able to take "
                    "any pictures until you connect a camera. You can reload "
                    "cameras using the '/camera list' command.")

    # Create the bot
    log.info(f'Initializing bot...')
    bot = GphotoBot(args.sync)

    # Start the bot
    log.debug(f'Starting {bot.__class__.__name__}...')
    async with bot:
        try:
            await bot.start(settings.DISCORD_API_TOKEN)
        except KeyboardInterrupt as e:
            log.warning(f'Exiting on keyboard interrupt: {e}')


if __name__ == '__main__':
    asyncio.run(main(parse_args()))
