import logging
from typing import Optional

from discord import ButtonStyle, Embed, Interaction, ui

from gphotobot.conf import settings
from gphotobot.utils.base.view import BaseView
from .new_name_modal import NewNameModal
from .timelapse_creator import TimelapseCreator
from .validation import InvalidTimelapseNameError

_log = logging.getLogger(__name__)


class TimelapseInvalidNameView(BaseView):
    # The maximum number of attempts the user can make with the same problem
    # before this view is auto cancelled
    MAX_CONSECUTIVE_ATTEMPTS: int = 5

    def __init__(self,
                 interaction: Interaction,
                 error: InvalidTimelapseNameError):
        """
        Initialize an invalid name taken view to tell the user that they need
        to pick a different name (and help them do so).

        Args:
            interaction: The interaction that triggered this view.
            error: The error with info on why the name is invalid.
        """

        super().__init__(interaction)
        self.error: InvalidTimelapseNameError = error
        self.name = error.name

        # The number of consecutive times the user has given an invalid name
        # with the same problem
        self.attempt: int = 1

    async def build_embed(self) -> Optional[Embed]:
        return NotImplemented

    async def new_invalid_name(self, error: InvalidTimelapseNameError) -> None:
        """
        Call this when the user gives another invalid name.

        Args:
            error: The new error.
        """

        if error.problem == self.error.problem:
            self.attempt += 1
            cancelled = self.attempt == self.MAX_CONSECUTIVE_ATTEMPTS

            header = (f'Still Invalid (Attempt '
                      f'{self.attempt}/{self.MAX_CONSECUTIVE_ATTEMPTS})')
            if error.name == self.error.name:
                text = "That name is still invalid."
                if not cancelled:
                    text += " Please try again with a **new** name."
            else:
                self.error = error
                text = "This name is invalid for the same reason."

            embed: Embed = self.error.build_embed()
            embed.add_field(name=header, value=text, inline=False)

            if cancelled:
                embed.add_field(
                    name='Max Attempts Reached',
                    value='Timelapse creation automatically cancelled.',
                    inline=False
                )
                # Disable all buttons
                for child in self.children:
                    if hasattr(child, 'disabled'):
                        child.disabled = True

                # Show embed is disabled
                embed.color = settings.DISABLED_ERROR_EMBED_COLOR  # noqa

                # Stop listening to interactions on this view
                self.stop()
        else:
            # Otherwise, this is a new error
            self.attempt = 1
            self.error = error
            embed = self.error.build_embed()

        await self.interaction.edit_original_response(
            embed=embed, view=self
        )

    @ui.button(label='Change Name', style=ButtonStyle.primary,
               emoji=settings.EMOJI_EDIT)
    async def input_new_name(self,
                             interaction: Interaction,
                             _: ui.Button) -> None:
        """
        Show a modal prompting the user to enter a new name.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_modal(NewNameModal(
            self.on_valid_name,
            True,
            on_error=lambda _, n: self.new_invalid_name(n)
        ))

    async def on_valid_name(self, name: str) -> None:
        """
        This is the callback function for when (if?) the user enters a valid
        timelapse name. It opens a timelapse creator view and stops this one.

        Args:
            name: The pre-validated timelapse name.
        """

        await TimelapseCreator.create_new(
            self.interaction,
            name,
            do_validate=False
        )
        self.stop()

    @ui.button(label='Cancel', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_CANCEL)
    async def cancel(self,
                     interaction: Interaction,
                     _: ui.Button) -> None:
        """
        Cancel creating a timelapse.

        Args:
            interaction: The interaction.
            _: This button.
        """

        self.stop()
        await interaction.response.defer()  # acknowledge the interaction
        await self.interaction.delete_original_response()
