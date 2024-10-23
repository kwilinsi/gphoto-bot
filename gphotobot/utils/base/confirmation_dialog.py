from discord import ButtonStyle, Embed, Interaction, Message
from discord.ext.commands import Bot

from gphotobot import settings
from .. import utils
from .view import BaseView


class ConfirmationDialog(BaseView):
    def __init__(self,
                 parent: Interaction[Bot] | BaseView | Message,
                 title: str = 'Success',
                 description: str = 'Finished Successfully',
                 **kwargs) -> None:
        """
        Create a confirmation dialog, which presents the user with a single,
        static embed and a "Done" button to dismiss it.

        Args:
            parent: The interaction, view, or message to use when refreshing
            the display.
            title: The embed title.
            description: The embed description.
            **kwargs: Additional keyword arguments passed to the embed.
        """

        super().__init__(parent=parent)

        # Create the static, default embed
        self.embed: Embed = utils.default_embed(
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

    async def build_embed(self, *args, **kwargs) -> Embed:
        return self.embed

    async def done(self) -> None:
        self.stop()
        await self.delete_original_message()
