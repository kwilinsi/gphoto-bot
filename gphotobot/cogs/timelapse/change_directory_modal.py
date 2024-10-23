from collections.abc import Awaitable, Callable
import logging
from pathlib import Path
from typing import Optional

from discord import Interaction, ui

from gphotobot import utils
from gphotobot.sql.models.timelapses import DIRECTORY_MAX_LENGTH
from .validation import validate_directory

_log = logging.getLogger(__name__)


class ChangeDirectoryModal(ui.Modal, title='Timelapse Directory'):
    directory = ui.TextInput(
        label='Directory',
        required=True,
        min_length=1,
        max_length=DIRECTORY_MAX_LENGTH
    )

    def __init__(self,
                 callback: Callable[[Path], Awaitable[None]],
                 directory: Optional[Path]) -> None:
        """
        Initialize this modal, which prompts the user to enter a new directory
        for the timelapse files.

        Args:
            callback: The async function to call with the validated directory.
            directory: The current directory, used as a pre-filled value.
        """

        super().__init__()
        self.callback: Callable[[Path], Awaitable[None]] = callback
        if directory is not None:
            self.directory.default = str(directory)

        _log.debug("Created a change directory modal on timelapse creator")

    async def on_submit(self, interaction: Interaction) -> None:
        """
        Process the new directory request, validating it and then changing it if
        it's valid.

        Args:
            interaction: The interaction.
        """

        # Defer a response, as we'll be editing an existing message rather than
        # sending a new one
        await interaction.response.defer(ephemeral=True)

        # Validate the directory
        try:
            await self.callback(validate_directory(self.directory.value))
        except utils.ValidationError as error:
            embed = utils.contrived_error_embed(
                title='Error: Invalid Directory',
                text=error.msg
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
