from collections.abc import Awaitable, Callable
from datetime import datetime
import logging
from typing import Literal, Optional

from discord import ButtonStyle, Embed, Interaction

from gphotobot.conf import settings
from gphotobot.utils import utils
from gphotobot.utils.validation_error import ValidationError
from gphotobot.utils.base.view import BaseView
from ..runtime_modal import ChangeRuntimeModal
from .. import timelapse_utils
from .change_tracker import ChangeTracker, TracksChanges
from .schedule import Schedule
from .schedule_entry import ScheduleEntry
from .schedule_entry_builder import ScheduleEntryBuilder
from .schedule_entry_selector import ScheduleEntrySelector

_log = logging.getLogger(__name__)


class ScheduleBuilder(BaseView, TracksChanges):
    def __init__(self,
                 interaction: Interaction,
                 start_time: Optional[datetime],
                 end_time: Optional[datetime],
                 total_frames: Optional[int],
                 schedule: Optional[Schedule],
                 callback: Callable[
                     [Optional[datetime], Optional[datetime],
                      Optional[int], Optional[Schedule]],
                     Awaitable[None]
                 ],
                 cancel_callback: Callable[[], Awaitable]) -> None:
        """
        Initialize a ScheduleBuilder, a view used to construct and edit a
        timelapse Schedule.

        Args:
            interaction: The interaction to edit with this view.
            start_time: The current overall runtime start.
            end_time: The current overall runtime end.
            total_frames: The current total frame threshold for ending.
            schedule: An existing schedule, if one exists. Defaults to None.
            callback: An async function to call to save the updated schedule
            configuration. It accepts the new start time, end time, total
            frames, and schedule.
            cancel_callback: An async function to call if this is cancelled. It
            doesn't save any changes.
        """

        super().__init__(
            interaction=interaction,
            callback=callback,
            callback_cancel=cancel_callback,
            permission_error_msg='Create a new timelapse with `/timelapse '
                                 'create` to build a custom schedule.'
        )

        # Set the initial schedule, making a new one if none was given
        s = Schedule() if schedule is None else schedule
        self.schedule: ChangeTracker[Schedule] = ChangeTracker(s)

        # Overall runtime conditions. Track changes
        self.start_time: ChangeTracker[Optional[datetime]] = \
            ChangeTracker(start_time)
        self.end_time: ChangeTracker[Optional[datetime]] = \
            ChangeTracker(end_time)
        self.total_frames: ChangeTracker[Optional[int]] = \
            ChangeTracker(total_frames)

        # Create the buttons
        self.button_save = self.create_button(
            label='Save',
            style=ButtonStyle.success,
            emoji=settings.EMOJI_SCHEDULE_DONE,
            disabled=True,  # No changes have been made yet
            row=0,
            callback=lambda _: self.select_button_save()
        )

        self.button_info = self.create_button(
            label='Info',
            style=ButtonStyle.primary,
            emoji=settings.EMOJI_INFO,
            row=0,
            callback=self.select_button_info
        )

        self.button_cancel = self.create_button(
            label='Cancel',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CANCEL,
            row=0,
            callback=lambda _: self.run_cancel_callback()
        )

        self.button_add = self.create_button(
            label='Add',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_ADD_SCHEDULE,
            row=1,
            callback=lambda _: self.select_button_add()
        )

        self.button_edit = self.create_button(
            label='Edit',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_EDIT_SCHEDULE,
            disabled=len(self.schedule.current) == 0,
            row=1,
            callback=lambda i: self.select_button_entry(i, 'edit')
        )

        self.button_move = self.create_button(
            label='Move',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_MOVE,
            disabled=len(self.schedule.current) < 2,
            row=1,
            callback=lambda i: self.select_button_entry(i, 'move')
        )

        self.button_remove = self.create_button(
            label='Remove',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_REMOVE_SCHEDULE,
            disabled=len(self.schedule.current) == 0,
            row=1,
            callback=lambda i: self.select_button_entry(i, 'remove')
        )

        self.button_runtime = self.create_button(
            label='Set Overall Runtime',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            row=2,
            callback=lambda i: i.response.send_modal(ChangeRuntimeModal(
                self.start_time.current,
                self.end_time.current,
                self.total_frames.current,
                self.set_runtime
            )),
            auto_defer=False
        )

        # Use "Change Overall Runtime" if any of the runtime parameters are set
        self.update_runtime_button()

    async def build_embed(self) -> Embed:
        """
        Construct an embed with the info about this schedule. This embed is
        associated with the buttons in this view.

        Returns:
            The embed.
        """

        # Get runtime info
        runtime_text = timelapse_utils.generate_embed_runtime_text(
            self.start_time.current,
            self.end_time.current,
            self.total_frames.current
        )

        # Add a message about the schedule below (in the embed fields)
        if len(self.schedule.current) == 0:
            msg = 'Add entries below to build the timelapse schedule.'
        elif len(self.schedule.current) == 1:
            msg = 'The schedule is defined as follows:'
        else:
            msg = 'The schedule is applied in the following order:'

        # Create the base embed
        embed = utils.default_embed(
            title='Timelapse Schedule Editor',
            description=f'### Overall Runtime\n{runtime_text}\n\n{msg}'
        )

        # Add a field for each schedule entry
        for index, entry in enumerate(self.schedule.current):
            header, body = entry.get_embed_field_strings()
            embed.add_field(
                name=f'{index + 1}. {header}',
                value=body,
                inline=False
            )

        # Return the fully constructed embed
        return embed

    def has_changed(self) -> bool:
        return self.start_time.has_changed() or \
            self.end_time.has_changed() or \
            self.total_frames.has_changed() or \
            self.schedule.has_changed()

    async def set_runtime(self,
                          start_time: Optional[datetime],
                          end_time: Optional[datetime],
                          total_frames: Optional[int]) -> None:
        """
        Set new runtime parameters. If anything changed, refresh the display.

        Args:
            start_time: The new start time.
            end_time:  The new end time.
            total_frames:  The new total frame threshold.
        """

        # Update all values
        start = self.start_time.update(start_time)
        end = self.end_time.update(end_time)
        frames = self.total_frames.update(total_frames)

        if start or end or frames:
            # If any of the values changed, recalculate whether the "Save"
            # button should be enabled and "Cancel" turned red. Also update
            # the runtime button. Then refresh the display
            self.update_save_cancel_buttons()
            self.update_runtime_button()
            await self.refresh_display()

    def update_save_cancel_buttons(self) -> None:
        """
        Check whether the current schedule settings are different from their
        initial values. If so, the Save button should be enabled, and Cancel
        should be red. Otherwise, Save should be disabled, and Cancel should
        be gray.

        This does NOT refresh the display.
        """

        if self.has_changed():
            self.button_save.disabled = False
            self.button_cancel.style = ButtonStyle.danger
        else:
            self.button_save.disabled = True
            self.button_cancel.style = ButtonStyle.secondary

    def update_runtime_button(self) -> None:
        """
        Set the overall runtime button to either "Set Overall Runtime" or
        "Change Overall Runtime" based on whether the start time, end time, or
        total frames have been set.
        """

        if self.start_time is not None or self.end_time is not None or \
                self.total_frames is not None:
            self.button_runtime.label = 'Change Overall Runtime'
            self.button_runtime.emoji = settings.EMOJI_CHANGE_TIME
        elif self.start_time is None and self.end_time is None and \
                self.total_frames is None:
            self.button_runtime.label = 'Set Overall Runtime'
            self.button_runtime.emoji = settings.EMOJI_SET_RUNTIME

    async def select_button_save(self) -> None:
        """
        The callback function for the "Save" button. It runs the main callback
        function, passing the new start time, end time, total frames, and
        schedule.

        Then stop() this view, as it'll be replaced by the calling view.
        """

        # Save changes
        await self.callback(
            self.start_time.current,
            self.end_time.current,
            self.total_frames.current,
            self.schedule.current
        )

        # Stop this view
        self.stop()

    @staticmethod
    async def select_button_info(interaction: Interaction) -> None:
        """
        Callback for the "Info" button. Show info about timelapse schedules.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Acknowledge
        await interaction.followup.send(content='Info!', ephemeral=True)

    async def select_button_add(self) -> None:
        """
        Create and add a new entry to the schedule.
        """

        # Define the callback function
        async def callback(entry: Optional[ScheduleEntry]) -> None:
            if entry is not None:
                self.schedule.current.append(entry)

            # There's at least one entry now: enable the editing buttons
            self.button_edit.disabled = self.button_remove.disabled = False
            self.button_move.disabled = len(self.schedule.current) < 2
            self.update_save_cancel_buttons()
            await self.refresh_display()

        # Send a view for making a new entry
        await ScheduleEntryBuilder(self.interaction, callback).refresh_display()

    async def select_button_entry(
            self,
            interaction: Interaction,
            mode: Literal['edit', 'move', 'remove']) -> None:
        """
        Open a view prompting the user to select an entry from the schedule so
        that it can be either edited or removed.

        Args:
            interaction: The interaction that triggered this UI event.
            mode: Whether to 'edit', 'move', or 'remove' the selected entry.
        """

        # If there aren't any entries, send an error
        count = len(self.schedule.current)
        if count == 0:
            _log.warning(f"Unreachable: user clicked the button to {mode} an "
                         "entry, but there aren't any")
            embed = utils.contrived_error_embed(
                title=f'Error: Nothing to {mode.capitalize()}',
                text=f"There are no schedule entries to {mode}. "
                     f"You can create one by clicking 'Add'.",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # If there's only one entry, edit/remove it
        if count == 1:
            if mode == 'move':
                # Can't move unless there are at least 2 entries
                _log.warning(f"Unreachable: user clicked the button to move "
                             "an entry, but there's only one")
                embed = utils.contrived_error_embed(
                    title="Error: Can't Move",
                    text="There's only one schedule entry, so there's nowhere "
                         "to move it. You can remove this entry by clicking "
                         "'Remove'.",
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # (Stupid type checker; mode can't be 'move' here)
                # noinspection PyTypeChecker
                await self.entry_button_callback(mode, 0)

            return

        # Cancel callback function
        async def cancel_callback():
            self.update_save_cancel_buttons()
            await self.refresh_display()

        # There are multiple entries. Create and send a selector to pick one
        await ScheduleEntrySelector(
            self.interaction,
            self.schedule.current,
            mode,
            self.entry_button_callback,  # This is never used in 'move' mode
            cancel_callback
        ).refresh_display()

    async def entry_button_callback(self,
                                    mode: Literal['edit', 'remove'],
                                    index: int) -> None:
        """
        This is the callback for the ScheduleEntrySelector in 'edit' and
        'remove' mode.

        Args:
            mode: Whether the user wants to edit or remove an entry.
            index: The index of the selected entry.
        """

        if mode == 'edit':
            async def callback(_):
                self.update_save_cancel_buttons()
                await self.refresh_display()

            await ScheduleEntryBuilder(
                self.interaction,
                callback,
                self.schedule.current[index]
            ).refresh_display()
        elif mode == 'remove':
            # Remove the selected entry
            del self.schedule.current[index]

            # If there aren't any entries now, disable editing buttons
            if len(self.schedule.current) == 0:
                self.button_edit.disabled = self.button_remove.disabled = True

            # Move button requires at least 2 entries
            self.button_move.disabled = len(self.schedule.current) < 2

            # Update the display
            self.update_save_cancel_buttons()
            await self.refresh_display()
        else:
            raise ValidationError("Invalid mode for selection entry; expected "
                                  f"'edit' or 'remove'; got '{mode}'")
