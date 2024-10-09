import logging

import discord
from discord.ext import commands
import gphoto2 as gp

from gphotobot.utils import const, utils

_log = logging.getLogger(__name__)


async def handle_gphoto_error(interaction: discord.Interaction[commands.Bot],
                              error: gp.GPhoto2Error,
                              text: str) -> None:
    """
    Nicely handle an error from gPhoto2.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction to
        which to send the error message.
        error (gp.GPhoto2Error): The error.
        text (str): Text explaining what went wrong.
    """

    # Build an embed to nicely display the error
    embed = error_embed(
        error,
        text,
        'gPhoto2 Error',
        show_details=False,
        show_traceback=False
    )

    # Add the error code and message
    embed.add_field(
        name=f'Code: {error.code}',
        value=trunc(error.string if error.string else '*[No details given]*',
                    const.EMBED_FIELD_VALUE_LENGTH),
        inline=False
    )

    await update_interaction(interaction, embed)

    # Log details
    _log.error(f"{text} (Code {error.code}): "
               f"{error.string if error.string else '[No details given]'}")
    _log.debug(f'Traceback on {gp.GPhoto2Error.__name__}:', exc_info=True)


async def handle_no_camera_error(
        interaction: discord.Interaction[commands.Bot]) -> None:
    """
    Send an error embed in response to an interaction indicating that no camera
    was found.

    Args:
        interaction (discord.Interaction[commands.Bot]): The interaction to
        which to send the error message.
    """

    _log.warning(f'Failed to get a camera when processing '
                 f'{utils.app_command_name(interaction)}')
    embed = utils.contrived_error_embed('No camera detected',
                                        'Missing Camera')
    await utils.update_interaction(interaction, embed)
