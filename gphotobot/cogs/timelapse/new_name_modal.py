import logging
from collections.abc import Awaitable, Callable

from discord import Interaction, ui

from gphotobot.sql.models.timelapses import NAME_MAX_LENGTH
from .validation import InvalidTimelapseNameError, validate_name

_log = logging.getLogger(__name__)


class NewNameModal(ui.Modal, title='Timelapse Name'):
    # The timelapse name
    name = ui.TextInput(
        label='Name',
        required=True,
        min_length=1,
        max_length=NAME_MAX_LENGTH
    )

    def __init__(self,
                 callback: Callable[[str], Awaitable[None]],
                 previously_invalid: bool,
                 on_error: Callable[
                     [Interaction, InvalidTimelapseNameError],
                     Awaitable[None]
                 ]) -> None:
        """
        Initialize this modal, which prompts the user to enter a new name for
        a timelapse.

        The parent view is either an invalid name view, meaning the user
        tried to create a timelapse with an invalid name, or it's an existing
        creator, meaning that the user is changing the name they entered.

        Args:
            callback: The async function to call if a valid name is given. No
            need to validate the string passed to this callback.
            previously_invalid: Whether the user previously gave an invalid
            name and this is a second (or third, etc.) attempt.
            on_error: The async function to call to handle an invalid name
            error. It passes the interaction that provided the invalid name
            and the error with detailed info about what went wrong.

        """

        super().__init__()
        self.callback: Callable[[str], Awaitable[None]] = callback
        self.on_error: Callable[
            [Interaction, InvalidTimelapseNameError],
            Awaitable[None]
        ] = on_error

        # If the user previously gave an invalid name, add a little reminder
        self.name.placeholder = ('Enter a new, valid name' if previously_invalid
                                 else 'Enter a new name')

        _log.debug(
            f'Created a new name modal to set a timelapse name' +
            (' after a previously invalid one' if previously_invalid else '')
        )

    async def on_submit(self, interaction: Interaction) -> None:
        """
        Process the new name, validating it and proceeding to the next stage
        if the name is good.

        Args:
            interaction: The interaction.
        """

        # Defer a response, as we'll be editing an existing message rather than
        # sending a new one
        await interaction.response.defer()

        # Validate the user's timelapse name
        try:
            validated_name = await validate_name(self.name.value)
        except InvalidTimelapseNameError as error:
            await self.on_error(interaction, error)
            return

        # Pass the now-validated name to the callback
        await self.callback(validated_name)
