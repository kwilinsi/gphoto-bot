from collections.abc import Awaitable, Callable
from datetime import date, time, timedelta
import logging
from typing import Optional, Union

from discord import ButtonStyle, Embed, Interaction, Message, ui

from gphotobot import GphotoBot, settings, utils
from gphotobot.utils import DayOfWeek as DayEnum
from ..interval_modal import ChangeIntervalModal
from .dates import Dates
from .days import Days
from .days_of_week import DaysOfWeek
from .schedule_entry import ScheduleEntry
from .schedule_modals import ScheduleRuntimeModal, SpecificDatesModal

_log = logging.getLogger(__name__)


class ScheduleEntryBuilder(utils.BaseView):
    def __init__(self,
                 parent: Interaction[GphotoBot] | utils.BaseView | Message,
                 callback: Callable[[Optional[ScheduleEntry]], Awaitable[None]],
                 index: int | None = None,
                 entry: ScheduleEntry | None = None) -> None:
        """
        Initialize a view for creating/editing a schedule entry.

        Args:
            parent: The interaction, view, or message to use when refreshing
            the display.
            callback: The function to call when done editing.
            index: The index of the entry. If omitted, this defaults to the
            index of the existing entry. Either the entry or the index must be
            given. Defaults to None.
            entry: An existing schedule entry to edit, or None to create a new
            one. Defaults to None.

        Raises:
            ValueError: If both the entry and index are None, or if they have
            different indices.
        """

        # Validate index/entry input
        if index is None and entry is None:
            raise ValueError('You must specify either an existing entry or '
                             'the index for a new one.')
        elif index is not None and entry is not None and index != entry.index:
            raise ValueError(f"The entry index {entry.index} doesn't match "
                             f"the given index {index}. Either they need to "
                             f"match exactly, or one must be None.")

        # Initialize the base view
        super().__init__(
            parent=parent,
            callback=callback,
            permission_error_msg='Create a new timelapse with `/timelapse '
                                 'create` to build a custom schedule.'
        )

        # Set the index and entry. If index is omitted, use the entry value
        self.index: int = entry.index if index is None else index
        self.entry: ScheduleEntry | None = entry

        # If there's an existing entry, use its rule type as the default
        if entry is None or entry.days is None:
            current_rule_str = None
        else:
            current_rule_str = entry.days.str_rule()

        # Create/add the menu for picking a Days rule
        # Note that the option strings must correspond with Days.rule_type_str()
        self.menu_rule: ui.Select = self.create_select_menu(
            placeholder='Pick a scheduling rule',
            options=['Days of the week', 'Specific dates', 'Every day'],
            defaults=[current_rule_str],
            callback=self.select_run_rule,
            row=0
        )

        # If the entry already has information, add associated components
        self.components: tuple[Union[ui.Button, ui.Select], ...] = ()

        # Create/add the set_times button
        self.button_set_times: ui.Button = self.create_button(
            label='Set Start/End Times',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            callback=self.click_button_time,
            row=1,
            auto_defer=False
        )

        # Create/add the custom_interval button
        self.button_custom_interval: ui.Button = self.create_button(
            label='Set Custom Interval',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_TIME_INTERVAL,
            callback=self.click_button_interval,
            row=1,
            auto_defer=False
        )

        # Create/add the save button
        self.button_save: ui.Button = self.create_button(
            label='Save',
            style=ButtonStyle.success,
            emoji=settings.EMOJI_SCHEDULE_DONE,
            callback=self.click_button_save,
            row=2
        )

        # Create/add the cancel button
        self.button_cancel: ui.Button = self.create_button(
            label='Cancel',
            style=ButtonStyle.danger,
            emoji=settings.EMOJI_CANCEL,
            callback=self.click_button_cancel,
            row=2
        )

        if entry is not None:
            self.components = self.add_rule_specific_components(entry.days)

        _log.debug(f'Created schedule entry builder on entry {entry}')

    async def build_embed(self, *args, **kwargs) -> Embed:
        if self.entry is None:
            description = ("Schedule when the timelapse should run.\n\nCreate "
                           "a rule to determine which days this entry should "
                           "take effect, and then set a time range to use "
                           "on those days.")
        else:
            description = 'Run the timelapse...'

        # Create the base embed
        embed = utils.default_embed(
            title=f"{'' if self.entry is None else 'Edit '}Schedule Entry",
            description=description
        )

        # Exit now if there's no rule yet
        if self.entry is None:
            return embed

        days = self.entry.days

        # Add info about the days

        if days is not None:
            if isinstance(days, Dates):
                embed.add_field(name='On select dates',
                                value=str(days),
                                inline=False)
            if isinstance(days, DaysOfWeek):
                embed.add_field(name=days.descriptive_header(),
                                value=days.str_long(None),
                                inline=False)

        # Add info about the time of day

        body = 'From '
        if self.entry.runs_all_day():
            header = 'All day long'
        elif self.entry.end_time <= time(hour=12):
            header = 'In the morning'
        elif self.entry.start_time >= time(hour=17):
            header = 'In the evening'
        elif self.entry.start_time >= time(hour=12):
            header = 'In the afternoon'
        else:
            header = 'Going from'
            body = ''

        s = utils.format_time(self.entry.start_time, use_text=True)
        e = utils.format_time(self.entry.end_time, use_text=True)
        body += f"**{s}** to **{e}**"

        embed.add_field(name=header,
                        value=body,
                        inline=False)

        # Add the custom configuration, if present

        config_text = self.entry.get_config_text()
        if config_text is not None:
            embed.add_field(name='Custom Configuration',
                            value=config_text,
                            inline=False)

        # Return the finished embed
        return embed

    def add_rule_specific_components(
            self,
            rule: Days,
            row: int = 1) -> tuple[Union[ui.Button, ui.Select], ...]:
        """
        Create the components used for editing the particular days rule. The
        components are automatically added to the view in the specified row.

        Args:
            rule: The rule to edit with these components.
            row: The row in which to add the components. Defaults to 1.

        Returns:
            A tuple of added components dedicated to the specified rule. These
            are given in the order that they should be added to the view.
        """

        # If there are no active components, that means this is the first time
        # add them. We need to shift a bunch of buttons down one row to make
        # space
        shifted_buttons = None
        if not self.components:
            shifted_buttons = (self.button_set_times,
                               self.button_custom_interval,
                               self.button_save,
                               self.button_cancel)
            self.remove_items(shifted_buttons)
            for btn in shifted_buttons:
                btn.row += 1

        # Use a selection menu for days of the week
        if isinstance(rule, DaysOfWeek):
            menu: ui.Select = self.create_select_menu(
                placeholder='Pick days to run',
                options=[d.name.capitalize() for d in DayEnum],
                defaults=[d.name.capitalize() for d in rule],
                no_maximum=True,
                callback=self.select_week_days,
                row=row
            )

            if not self.components:
                self.add_items(shifted_buttons)

            return (menu,)

        # Use a set of buttons for specific dates
        elif isinstance(rule, Dates):
            add: ui.Button = self.create_button(
                label='Add',
                style=ButtonStyle.secondary,
                emoji=settings.EMOJI_ADD_SCHEDULE,
                callback=lambda i: self.click_button_update_dates(i, True),
                row=row,
                auto_defer=False
            )

            remove: ui.Button = self.create_button(
                label='Remove',
                style=ButtonStyle.secondary,
                emoji=settings.EMOJI_REMOVE_SCHEDULE,
                callback=lambda i: self.click_button_update_dates(i, False),
                disabled=len(rule) == 0,
                row=row,
                auto_defer=False
            )

            clear: ui.Button = self.create_button(
                label='Clear',
                style=ButtonStyle.secondary,
                emoji=settings.EMOJI_DELETE,
                callback=self.click_button_clear_dates,
                disabled=len(rule) == 0,
                row=row
            )

            if not self.components:
                self.add_items(shifted_buttons)

            return add, remove, clear

        # Some new unsupported Days type
        raise ValueError(f"Unexpected days rule type {type(rule)}")

    async def select_run_rule(self, _: Interaction) -> None:
        """
        This is the callback for the rule selection menu.

        Change the rule, and update the view accordingly.

        Args:
            _: The interaction that triggered this callback.
        """

        # Track whether the components need to change
        change_components = True
        selection: str = self.menu_rule.values[0]

        if selection == 'Specific dates':
            # Switch to the Dates rule type
            if self.entry is None:
                self.entry = ScheduleEntry(index=self.index, days=Dates())
            elif isinstance(self.entry.days, Dates):
                return
            else:
                self.entry.days = Dates()
        else:
            # Switch to the DaysOfWeek rule type
            every_day = selection == 'Every day'

            if self.entry is None:
                self.entry = ScheduleEntry(
                    index=self.index,
                    days=DaysOfWeek(
                        utils.EVERY_DAY_OF_WEEK if every_day else ()
                    )
                )
            elif isinstance(self.entry.days, DaysOfWeek):
                change_components = False

                if every_day:
                    # It's already using the DaysOfWeek dropdown. The user
                    # switched to 'Every Day', so add all the days of the week
                    self.entry.days.update(utils.EVERY_DAY_OF_WEEK)  # noqa
                    utils.set_menu_default(
                        self.components[0],
                        tuple(d.name.capitalize()
                              for d in self.entry.days)  # noqa
                    )
                else:
                    # The user went from 'Every day' to 'Days of the week'.
                    # No changes are necessary at all
                    pass
            else:
                # Replace with new Rules instance that uses every day or
                self.entry.days = DaysOfWeek(
                    utils.EVERY_DAY_OF_WEEK if every_day else ()
                )

        ##################################################

        # Update this menu to keep the selected open chosen
        utils.set_menu_default(self.menu_rule, self.menu_rule.values[0])

        # Replace the rule-specific components if necessary
        if change_components:
            self.remove_items(self.components)
            self.components = self.add_rule_specific_components(self.entry.days)

        # Update the display, as something will have changed (otherwise we
        # would have already returned)
        await self.refresh_display()

    async def set_start_end_time(self,
                                 start_time: time,
                                 end_time: time) -> None:
        """
        Change the start/end times of this entry, and refresh the display. If
        they didn't change, nothing is refreshed. If the entry is currently
        None, one is created.

        Args:
            start_time: The new start time.
            end_time: The new end time.
        """

        if self.entry is None:
            # Create a new schedule entry if there wasn't one
            self.entry = ScheduleEntry(index=self.index,
                                       start_time=start_time,
                                       end_time=end_time)
            utils.set_menu_default(self.menu_rule, self.entry.days.str_rule())
            self.components = self.add_rule_specific_components(self.entry.days)
        elif self.entry.start_time == start_time and \
                self.entry.end_time == end_time:
            # No change
            return
        else:
            # At least one change
            self.entry.start_time = start_time
            self.entry.end_time = end_time

        # If reached, something changed
        self.button_set_times.label = 'Change Start/End Time'
        self.button_set_times.emoji = settings.EMOJI_CHANGE_TIME
        await self.refresh_display()

    async def set_capture_interval(self, interval: Optional[timedelta]) -> None:
        """
        Set the new capture interval, a custom configuration for this schedule
        entry. If there is currently no entry, one is created with the default
        settings.

        Args:
            interval: The new capture interval, or None to disable it.
        """

        # If no entry exists, create one with default settings--unless this
        # did not add an interval
        if self.entry is None:
            if interval is None:
                return

            # Create a default entry, so we can set its interval
            self.entry = ScheduleEntry(index=self.index)
            utils.set_menu_default(self.menu_rule, self.entry.days.str_rule())
            self.components = self.add_rule_specific_components(self.entry.days)

        # Set button label based on whether an interval is present
        if interval is None:
            self.button_custom_interval.label = 'Set Custom Interval'
        else:
            self.button_custom_interval.label = 'Change Custom Interval'

        # Update the display if the interval changes
        if self.entry.set_config_interval(interval):
            await self.refresh_display()

    async def click_button_time(self, interaction: Interaction) -> None:
        """
        This is the callback for the runtime button.

        Send a modal prompting the user to update the start and end times.

        Args:
            interaction: The interaction that triggered this callback.
        """

        # Create the modal with the current values if there are any
        if self.entry is None:
            modal = ScheduleRuntimeModal(self.set_start_end_time)
        else:
            modal = ScheduleRuntimeModal(self.set_start_end_time,
                                         start_time=self.entry.start_time,
                                         end_time=self.entry.end_time)

        # Send the modal. No need to defer, as creating the modal should be fast
        await interaction.response.send_modal(modal)

    async def click_button_interval(self, interaction: Interaction) -> None:
        """
        This is the callback for the custom interval button.

        Send a modal prompting the user to change the custom capture interval
        for this schedule entry.

        Args:
            interaction: The interaction that triggered this callback.
        """

        await interaction.response.send_modal(ChangeIntervalModal(
            self.set_capture_interval,
            None if self.entry is None else self.entry.get_config_interval(),
            required=False
        ))

    async def click_button_save(self, interaction: Interaction) -> None:
        """
        This is the callback for the "save" button. It runs the primary callback
        for this view, return to the schedule builder and adding the newly
        created entry.

        It is possible that said callback will raise a ValidationError when it
        attempts to add the schedule entry. If that happens, it's caught here
        and sent as a response to this interaction.

        If the callback runs successfully, this view is stopped.

        Args:
            interaction: The interaction that triggered this callback.
        """

        try:
            await self.callback(self.entry)
        except utils.ValidationError as e:
            embed = utils.contrived_error_embed(
                title='Failed to Add Entry',
                text=e.msg
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Close this view
        self.stop()

    async def click_button_cancel(self, _: Interaction) -> None:
        """
        This is the callback for the "cancel" button. It runs the primary
        callback with None, thereby not passing any entry.

        Args:
            _: The interaction that triggered this callback.
        """

        # Close this view
        await self.callback(None)
        self.stop()

    async def select_week_days(self, _: Interaction, menu: ui.Select) -> None:
        """
        This is the callback for the days of the week selection menu.

        Change the selected days of the week, and update the view accordingly.

        Args:
            _: The interaction that triggered this callback.
            menu: The selection menu with the days of the week.
        """

        days: set[DayEnum] = {DayEnum.from_full_name(n) for n in menu.values}

        # Don't do anything unless this changes the selection
        entry_days = self.entry.days
        assert isinstance(entry_days, DaysOfWeek)
        if entry_days == days:
            return

        # If all 7 days are currently selected, then this is going to de-select
        # some of them. In that case, change the rule selector from "Every day"
        # to "Days of the week"
        if len(entry_days) == 7:
            utils.set_menu_default(self.menu_rule, 'Days of the week')

        # Update the entry with new rule
        self.entry.days = DaysOfWeek(days)

        # If all 7 days are selected now, change rule selector to "Every day"
        if len(days) == 7:
            utils.set_menu_default(self.menu_rule, 'Every day')

        # Make sure the currently selected values stay selected
        utils.set_menu_default(menu, menu.values)

        # Refresh to display changes to user
        await self.refresh_display()

    async def click_button_update_dates(self,
                                        interaction: Interaction,
                                        add: bool) -> None:
        """
        This is the callback for the add button for specific dates.

        Open a modal prompting the user to enter a list of specific dates.

        Args:
            interaction: The interaction that triggered this callback.
            add: Whether the user wants to add dates (True) or remove them
            (False).
        """

        # Define the callback function
        async def update_dates(dates: list[date], _add: bool):
            # Update the dates
            days = self.entry.days
            assert isinstance(days, Dates)
            days.add(dates) if _add else days.remove(dates)

            # Disable/enable buttons based on how many dates there are
            n = len(days)
            self.components[0].disabled = n == Dates.MAX_ALLOWED_DATES
            self.components[1].disabled = n == 0
            self.components[2].disabled = n == 0

            await self.refresh_display()

        # Create and send the modal for adding dates
        await interaction.response.send_modal(SpecificDatesModal(
            update_dates, add
        ))

    async def click_button_clear_dates(self, interaction: Interaction) -> None:
        """
        This is the callback for the clear button for specific dates.

        Clear all the selected dates.

        Args:
            interaction: The interaction that triggered this callback.
        """

        days = self.entry.days
        assert isinstance(days, Dates)

        if len(days) == 0:
            # This should be unreachable
            _log.warning('Unreachable: clearing dates when there are none')
            await interaction.followup.send(
                content="There aren't any dates to clear. Add dates to "
                        "specify when this rule should apply.",
                ephemeral=True
            )
            return

        # Clear dates, and update the display
        self.entry.days = Dates()
        self.components[0].disabled = False
        self.components[1].disabled = True
        self.components[2].disabled = True
        await self.refresh_display()
