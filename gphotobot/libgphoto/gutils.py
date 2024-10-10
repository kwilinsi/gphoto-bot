import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands
from PIL import Image
import gphoto2 as gp

from gphotobot.libgphoto.rotation import Rotation
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
    embed: discord.Embed = utils.error_embed(
        error,
        text,
        'gPhoto2 Error',
        show_details=False,
        show_traceback=False
    )

    # Add the error code and message
    embed.add_field(
        name=f'Code: {error.code}',
        value=utils.trunc(
            error.string if error.string else '*[No details given]*',
            const.EMBED_FIELD_VALUE_LENGTH
        ),
        inline=False
    )

    await utils.update_interaction(interaction, embed)

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


async def rotate_image(path: Path, rotation: Rotation) -> None:
    """
    Rotate the given image in place using Pillow. This is performed
    asynchronously to avoid blocking.

    Args:
        path: The path to the image to rotate.
        rotation: The amount to rotate it.
    """

    await asyncio.to_thread(_rotate_image_blocking, path, rotation)


def _rotate_image_blocking(path: Path, rotation: Rotation) -> None:
    """
    Rotate the given image using Pillow in place, overwriting the original
    file. This is a blocking operation.

    Args:
        path: The path to the image to rotate.
        rotation: The amount to rotate it.
    """

    if rotation != Rotation.DEGREE_0:
        image = Image.open(path)
        rotated_image = image.rotate(360 - rotation.value, expand=True)
        rotated_image.save(path)
