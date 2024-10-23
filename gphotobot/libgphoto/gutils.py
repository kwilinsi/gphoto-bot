import asyncio
import contextlib
from datetime import datetime
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import Embed, File
from discord.ext import commands
import gphoto2 as gp
from PIL import Image

from gphotobot import const, settings, utils
from .rotation import Rotation

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
        interaction: discord.Interaction[commands.Bot],
        message: Optional[str] = None) -> None:
    """
    Send an error embed in response to an interaction indicating that no camera
    was found.

    Args:
        interaction: The interaction to which to send the error message.
        message: A custom error message to use instead of the default generic
        message. Defaults to None.
    """

    if message is None:
        message = 'No camera detected'

    _log.warning(f'Error processing {utils.app_command_name(interaction)}: '
                 f'{message.lower()}')
    embed = utils.contrived_error_embed(message, 'Missing Camera')
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


@contextlib.asynccontextmanager
async def preview_image_embed(camera) -> tuple[Embed, File]:
    """
    Take a preview photo with the given camera, and return an embed and the
    file to attach. This implementation uses a context manager to manage
    resources.

    The preview image is captured and saved to tmp storage, then used to
    construct an embed. After the embed and file are consumed and sent to
    Discord, exit the context manager, at which point the image is
    automatically deleted from tmp storage.

    Access this via:
    async with preview_image_embed(camera) as (embed, file):
        # send to discord

    Args:
        camera: The camera to use for the preview image.

    Returns:
        A tuple with the embed and the file.

    Raises:
        GPhoto2Error: if there's an error capturing the preview image.
    """

    # Take a photo
    path, rotation = await camera.preview_photo()

    # Create the result embed
    embed = discord.Embed(
        title='Camera Preview',
        description=f'Preview image from **{camera}**',
        color=settings.DEFAULT_EMBED_COLOR,
        timestamp=datetime.now()
    )

    # Add the preview image to the embed
    file = discord.File(path, filename=f'preview.{path.suffix}')
    embed.set_image(url=f'attachment://{file.filename}')
    if rotation != Rotation.DEGREE_0:
        embed.set_footer(text=f'(Preview rotated {str(rotation).lower()})')

    # Yield the embed
    try:
        yield embed, file
    finally:
        # Delete the preview image
        try:
            await asyncio.to_thread(path.unlink)
            _log.debug(f'Deleted preview photo: {path}')
        except OSError as e:
            _log.warning(f"Attempted to delete preview photo, but it didn't "
                         f"exist for some reason: path='{path}', {e}")
