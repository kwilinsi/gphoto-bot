from __future__ import annotations

from datetime import timedelta
import logging
from typing import Awaitable, Callable, Optional

import discord
from discord import ui, utils as discord_utils

from gphotobot.utils import utils

_log = logging.getLogger(__name__)


class ChangeIntervalModal(ui.Modal, title='Timelapse Interval'):
    # The interval between photos
    interval = ui.TextInput(
        label='Interval',
        required=True,
        min_length=1,
        max_length=50
    )

    def __init__(self,
                 callback: Callable[[Optional[timedelta]], Awaitable],
                 interval: Optional[timedelta] = None,
                 required: bool = True) -> None:
        """
        Initialize this modal, which prompts the user to enter a new interval
        between captures.

        Args:
            callback: The async function to call to update the interval.
            interval: The current interval, used as the pre-filled value.
            required: Whether the user is required to give a value for the
            interval. If False, they can leave it blank, and the callback
            function is sent None. If this is True, the callback is never sent
            None. Defaults to True.
        """

        super().__init__()
        self.callback: Callable[[Optional[timedelta]], Awaitable] = callback
        self.required: bool = required

        if not required:
            self.interval.required = False

        if interval is not None:
            self.interval.default = utils.format_duration(
                interval, always_decimal=True
            )

        _log.debug(f'Created a change interval modal (required={required})')

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Process the new interval request, parsing and validating it and then
        running the callback function.

        Args:
            interaction: The interaction.
        """

        # Defer a response, as we'll be editing an existing message rather than
        # sending a new one
        await interaction.response.defer()

        # If not required, except blank input, sending None to the callback
        if not self.required and not self.interval.value.strip():
            await self.callback(None)
            return

        # Parse the interval string
        interval = utils.parse_time_delta(self.interval.value)

        if interval is None:
            clean = discord_utils.escape_markdown(self.interval.value)
            embed = utils.contrived_error_embed(
                title='Error: Invalid Interval',
                text=f"Couldn't parse the interval **\"{clean}\"**. The "
                     f"capture interval must be in a supported format, like "
                     f"'5h 2m 12.8s', '8:03', or '1d 10:30s'."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await self.callback(interval)
