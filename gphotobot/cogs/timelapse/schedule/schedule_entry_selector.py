from collections.abc import Awaitable, Callable
import logging
from typing import Literal, Optional

from discord import ButtonStyle, Embed, Interaction, Message, SelectOption, ui

from gphotobot import GphotoBot, settings, utils
from .schedule import Schedule

_log = logging.getLogger(__name__)


class ScheduleEntrySelector(utils.BaseView):
    def __init__(self,
                 parent: Interaction[GphotoBot] | utils.BaseView | Message,
                 schedule: Schedule,
                 mode: Literal['edit', 'move', 'remove'],
                 callback: Callable[[Literal['edit', 'remove'], int],
                 Awaitable],
                 callback_cancel: Callable[[], Awaitable]):
        """
        Initialize a schedule entry selector. This allows the user to select
        one of the schedule entries, either to edit it or delete it.

        Args:
            parent: The interaction, view, or message to use when refreshing
            the display.
            schedule: The schedule with entries to choose from. This must
            contain at least two entries; otherwise a selection menu wouldn't be
            necessary.
            mode: Whether the selected entry will be edited, moved, or removed.
            callback: The async callback function to run when the user makes
            a selection.
            callback_cancel: The async callback to run if the user clicks the
            "back" button without selecting an entry.

        Raises:
            AssertionError: If the list of entries doesn't contain at least two
            entries.
        """

        assert len(schedule) >= 2
        super().__init__(
            parent=parent,
            callback=callback,
            callback_cancel=callback_cancel,
            permission_error_msg='Create a new timelapse with `/timelapse '
                                 'create` to build a custom schedule.'
        )

        self.schedule: Schedule = schedule
        self.mode: Literal['edit', 'move', 'remove'] = mode

        # Add the selection menu
        self.menu = self.create_select_menu(
            placeholder='Select a schedule entry...',
            options=list(f"{i + 1}. {entry.get_embed_field_strings()[0]}"
                         for i, entry in enumerate(schedule)),
            callback=self.on_select
        )

        # Add a back button that'll run the cancel callback
        self.button_back = self.create_button(
            label='Back',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_BACK,
            callback=lambda _: self.run_cancel_callback()
        )

        # The index selected by the user. This is only used in 'move' mode
        self.index: Optional[int] = None

        # If this is in 'move' mode, create buttons for the direction to move.
        # We'll add them later
        if mode == 'move':
            self.move_up: ui.Button = self.create_button(
                label='Move up',
                style=ButtonStyle.primary,
                emoji=settings.EMOJI_MOVE_UP,
                callback=lambda i: self.on_click_move(i, True),
                add=False
            )
            self.move_down: ui.Button = self.create_button(
                label='Move down',
                style=ButtonStyle.primary,
                emoji=settings.EMOJI_MOVE_DOWN,
                callback=lambda i: self.on_click_move(i, False),
                add=False
            )

        _log.debug(f'Created a schedule entry selector with {len(schedule)} '
                   f'entries')

    async def build_embed(self, *args, **kwargs) -> Embed:
        # Set the description based on whether something is currently selected
        if self.index is None:
            desc = ('Select one of the following entries to '
                    f'{self.mode} it.')
        else:
            desc = f'Selected entry #{self.index + 1}. '
            if self.index == 0:
                desc += 'This is the first entry, so it can only be moved down.'
            elif self.index == len(self.schedule) - 1:
                desc += 'This is the last entry, so it can only be moved up.'
            else:
                desc += 'Click a button to move it up or down in the list.'

        # Create the base embed
        embed = utils.default_embed(
            title='Timelapse Schedule Editor',
            description=desc
        )

        # Add a field for each schedule entry
        for index, entry in enumerate(self.schedule):
            header, body = entry.get_embed_field_strings()
            embed.add_field(
                name=f'{index + 1}. {header}',
                value=body,
                inline=False
            )

        # Return the fully constructed embed
        return embed

    async def on_select(self, interaction: Interaction) -> None:
        """
        This is the callback that runs when the user selects a schedule entry.

        Args:
            interaction: The interaction.
        """

        try:
            # -1 because in the selection menu they're 1-indexed
            index = int(self.menu.values[0].split('.')[0]) - 1
        except ValueError as e:
            # Handle the theoretically impossible error if int() fails
            await utils.handle_err(
                interaction,
                e,
                text="Unexpected error: couldn't identify the selected entry",
                log_text="Unreachable: couldn't extract index from selection "
                         f"menu value '{self.menu.values[0]}' in entry selector"
            )
            return

        # If it's not move mode, run the callback, and exit
        if not self.mode == 'move':
            self.stop()
            await self.callback(self.mode, index)
            return

        # In move mode, we need to add the up/down buttons if this is the first
        # time the user selected an entry
        if self.index is None:
            self.remove_item(self.button_back)
            self.add_items((self.move_up, self.move_down, self.button_back))

        # Update the chosen index
        self.index = index

        # Enable/disable move buttons based on the index
        if self.mode == 'move':
            self.move_up.disabled = self.index == 0
            self.move_down.disabled = self.index == len(self.schedule) - 1

        # Make sure the selected entry persists when the display is refreshed
        utils.set_menu_default(self.menu, self.menu.values[0])

        # Refresh the display
        await self.refresh_display()

    async def on_click_move(self,
                            interaction: Interaction,
                            move_up: bool) -> None:
        """
        This is the callback function that runs when the user clicks either the
        up or down buttons.

        Args:
            interaction: The interaction that triggers this UI event.
            move_up: Whether the user clicked the "move up" button.
        """

        try:
            self.schedule.move_entry(self.index, move_up)
        except IndexError as e:
            await utils.handle_err(interaction, e,
                                   text='Unreachable: invalid move request')
            return

        # Update the index to the new position of the entry
        self.index += (-1 if move_up else 1)

        # Rebuild the selection menu to show the proper indices
        self.menu.options = [
            SelectOption(label=f"{i + 1}. {e.get_embed_field_strings()[0]}")
            for i, e in enumerate(self.schedule)
        ]
        self.menu.options[self.index].default = True

        # Enable/disable the move buttons based on the index
        self.move_up.disabled = self.index == 0
        self.move_down.disabled = self.index == len(self.schedule) - 1

        # Update this display
        await self.refresh_display()
