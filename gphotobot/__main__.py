from argparse import ArgumentParser, Namespace
import logging

import asyncio
import gphoto2 as gp

from .conf import settings, APP_NAME, logger_conf
from .bot import GphotoBot
from . import sql


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

    # Create the bot
    log.info(f'Starting {APP_NAME}...')
    log.debug(f'Initializing bot...')
    bot = GphotoBot(args.sync)

    # Start the bot
    log.debug(f'Starting {bot.__class__.__name__}...')
    await bot.start(settings.DISCORD_API_TOKEN)


if __name__ == '__main__':
    asyncio.run(main(parse_args()))
