from typing import Optional

from discord import ButtonStyle, Embed, Interaction

from gphotobot.conf import settings
from .. import utils
from .view import BaseView


class ConfirmationDialog(BaseView):
    def __init__(self,
                 interaction: Interaction,
                 title: str = 'Success',
                 description: str = 'Finished Successfully',
                 **kwargs) -> None:
        """
        Create a confirmation dialog, which presents the user with a single,
        static embed and a "Done" button to dismiss it.

        Args:
            interaction: The interaction to edit.
            title: The embed title.
            description: The embed description.
            **kwargs: Additional keyword arguments passed to the embed.
        """

        super().__init__(interaction)

        # Create the static, default embed
        self.embed = utils.default_embed(
            title=title,
            description=description,
            **kwargs
        )

        # Add the close button
        self.create_button(
            label='Close',
            emoji=settings.EMOJI_CANCEL,
            style=ButtonStyle.primary,
            callback=lambda _: self.done()
        )

    async def build_embed(self) -> Optional[Embed]:
        return self.embed

    async def done(self) -> None:
        self.stop()
        await self.interaction.delete_original_response()
