from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Optional

from discord import (ButtonStyle, Embed, Interaction, Member,
                     ui, User, utils as discord_utils)

from gphotobot.conf import settings
from gphotobot.libgphoto import GCamera, gmanager, NoCameraFound
from gphotobot.utils import utils
from gphotobot.utils.base.view import BaseView
from gphotobot.cogs.timelapse import timelapse_utils
from ..helper.camera_selector import CameraSelector
from .change_directory_modal import ChangeDirectoryModal
from .interval_modal import ChangeIntervalModal
from .new_name_modal import NewNameModal
from .runtime_modal import ChangeRuntimeModal
from .schedule.schedule import Schedule
from .schedule.schedule_builder import ScheduleBuilder
from .validation import (InvalidTimelapseNameError, validate_name,
                         determine_default_directory)

_log = logging.getLogger(__name__)


class TimelapseCreator(BaseView):
    def __init__(self,
                 interaction: Interaction,
                 name: str,
                 camera: Optional[GCamera],
                 directory: Optional[Path]):
        """
        Create a new view for helping the user make a timelapse.

        Args:
            interaction: The interaction that led to this view. This is used to
            get the original message to edit it as changes are made.
            name: The already-validated name of the timelapse.
            camera: The camera to use for the timelapse.
            directory: The directory for storing timelapse photos.
        """

        super().__init__(interaction)
        self._name = name
        self.user: User | Member = interaction.user
        self._camera: Optional[GCamera] = camera
        self._directory: Optional[Path] = directory

        # If the camera is already set, change button label
        if self._camera is not None:
            utils.get_button(self, 'Set Camera').label = 'Change Camera'

        # Retrieve the directory button, storing a reference to it. Change it
        # to 'Set Directory' if the directory is currently unset
        self.button_directory = utils.get_button(self, 'Change Directory')
        if directory is None:
            self.button_directory.label = 'Set Directory'

        # Default interval
        self._interval: Optional[timedelta] = None

        # Start runtime conditions
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._total_frames: Optional[int] = None

        # A timelapse schedule
        self._schedule: Optional[Schedule] = None

        # Create the interval button
        self.button_interval = self.create_button(
            label='Set Interval',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_TIME_INTERVAL,
            callback=self.select_button_interval,
            auto_defer=False,
            row=2
        )

        # Get runtime button
        self.button_runtime = self.create_button(
            label='Set Runtime' if self._start_time is None and
                                   self._end_time is None
            else 'Change the Runtime',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            callback=self.select_button_runtime,
            auto_defer=False,
            row=3,
        )

        # Create the schedule button
        self.button_schedule = self.create_button(
            label='Create a Schedule' if self._schedule is None
            else 'Edit the Schedule',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CREATE_SCHEDULE,
            callback=lambda _: self.select_button_schedule(),
            row=3
        )

        _log.info(f"Starting a new timelapse creator called {name}")

    @classmethod
    async def create_new(cls,
                         interaction: Interaction,
                         name: str,
                         do_validate: bool = True) -> None:
        """
        Create a new timelapse creator view. This gets some default values and
        builds the initial timelapse creation panel.

        Args:
            interaction: The interaction requesting to make a timelapse.
            name: The name of the timelapse.
            do_validate: Whether to validate the timelapse name before
            using it. Only disable if already validated. Defaults to True.

        Raises:
            InvalidTimelapseNameError: If the given name is not valid.
        """

        # Validate the input name if enabled
        if do_validate:
            name = await validate_name(name)

        # Determine the default directory
        directory: Optional[Path] = determine_default_directory(name)

        # Get a default camera
        try:
            camera = await gmanager.get_default_camera()
        except NoCameraFound:
            camera = None  # Worry about this later

        # Build and send the timelapse creator view
        await cls(interaction, name, camera, directory).refresh_display()

    async def refresh_display(self) -> None:
        """
        Edit the original interaction response message, updating it with this
        view and embed.
        """

        await self.interaction.edit_original_response(
            content='', embed=self.build_embed(), view=self
        )

    def build_embed(self) -> Embed:
        """
        Construct an embed with the info about this timelapse. This embed is
        associated with the buttons in this view.

        Returns:
            The embed.
        """

        # Escape markdown in the name
        safe_name = discord_utils.escape_markdown(self._name)

        # Get the camera name
        if self._camera is None:
            camera = '*undefined*'
        else:
            camera = utils.trunc(self._camera.name, 75, escape_markdown=True)

        # Create the base embed
        embed = utils.default_embed(
            title='Create a Timelapse',
            description=f"**Name:** {safe_name}\n"
                        f"**Creator:** {self.user.mention}\n"
                        f"**Camera:** {camera}"
        )

        # Add directory info
        if self._directory is None:
            # The directory can never be removed. If missing, it was never
            # chosen due to being too long
            directory = '*[Undefined: default path was too long]*'
        else:
            directory = f'`{self._directory}`'

        embed.add_field(name='Directory', value=directory, inline=False)

        # Add interval
        if self._interval is None:
            interval = '*Undefined*'
        else:
            interval = utils.format_duration(self._interval,
                                             always_decimal=True)

        embed.add_field(name='Capture Interval', value=interval, inline=False)

        # Add runtime info
        runtime_text = timelapse_utils.generate_embed_runtime_text(
            self._start_time,
            self._end_time,
            self._total_frames
        )
        embed.add_field(name='Runtime', value=runtime_text, inline=False)

        # Add schedule
        if self._schedule is not None:
            embed.add_field(
                name='Schedule',
                value=self._schedule.get_summary_str(),
                inline=False
            )

        # Return finished embed
        return embed

    async def set_directory(self, directory: Path) -> None:
        """
        Change the directory. If the directory is currently unset, this has the
        side effect of renaming the "Set Directory" button back to "Change
        Directory".

        If the directory changes, this also refreshes the display.

        Args:
            directory: The new directory.
        """

        if self._directory is None:
            self.button_directory.label = 'Change Directory'
            self._directory = directory
        elif self._directory != directory:
            self._directory = directory
            await self.refresh_display()

    async def set_interval(self, interval: timedelta) -> None:
        """
        Change the interval. If the interval is currently unset, this has the
        side effect of renaming the "Set Interval" to "Change Interval".

        If the interval changes, this also refreshes the display.

        Args:
            interval: The new interval.
        """

        if self._interval is None:
            utils.get_button(self, 'Set Interval').label = \
                'Change Interval'
        elif self._interval == interval:
            return

        self._interval = interval
        await self.refresh_display()

    async def set_runtime(self,
                          start_time: Optional[datetime],
                          end_time: Optional[datetime],
                          total_frames: Optional[int]) -> None:
        """
        Change the start/end time and/or the total frames. This has the side
        effect of possibly changing the label and emoji on the associated
        button.

        Args:
            start_time: The new start time.
            end_time: The new end time.
            total_frames:  The new total frame count.
        """

        # Change the button label, if applicable
        if start_time is not None or end_time is not None or \
                total_frames is not None:
            self.button_runtime.label = 'Change Runtime'
            self.button_runtime.emoji = settings.EMOJI_CHANGE_TIME
        elif start_time is None and end_time is None and total_frames is None:
            self.button_runtime.label = 'Set Runtime'
            self.button_runtime.emoji = settings.EMOJI_SET_RUNTIME

        # Update and display the configuration if it changed
        if total_frames != self._total_frames or \
                start_time != self._start_time or \
                end_time != self._end_time:
            self._start_time = start_time
            self._end_time = end_time
            self._total_frames = total_frames
            await self.refresh_display()

    @ui.button(label='Create', style=ButtonStyle.success,
               emoji=settings.EMOJI_DONE_CHECK, row=0)
    async def select_button_create(self,
                                   interaction: Interaction,
                                   _: ui.Button) -> None:
        """
        Create this timelapse, and add it to the database. Switch to a new
        display for controlling the created timelapse.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_message(content='Create!',
                                                ephemeral=True)
        await self.refresh_display()
        self.stop()

    @ui.button(label='Info', style=ButtonStyle.primary,
               emoji=settings.EMOJI_INFO, row=0)
    async def select_button_info(self,
                                 interaction: Interaction,
                                 _: ui.Button) -> None:
        """
        Show the user information about timelapses, as if they had run the
        `/timelapse info` command.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_message(
            content='This is some info on timelapses!',
            ephemeral=True
        )

    @ui.button(label='Cancel', style=ButtonStyle.danger,
               emoji=settings.EMOJI_CANCEL, row=0)
    async def select_button_cancel(self,
                                   interaction: Interaction,
                                   _: ui.Button) -> None:
        """
        Cancel this timelapse creator.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.defer()
        await self.interaction.delete_original_response()
        self.stop()

    @ui.button(label='Change Name', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_EDIT, row=1)
    async def select_button_name(self,
                                 interaction: Interaction,
                                 _: ui.Button) -> None:
        """
        Open a modal prompting the user to enter a new timelapse name.

        Args:
            interaction: The interaction.
            _: This button.
        """

        # Callback function for an invalid name
        async def on_error(i: Interaction,
                           error: InvalidTimelapseNameError) -> None:
            embed = error.build_embed()
            embed.add_field(
                name='Name Not Changed',
                value=f'The name is still **"{self.name}"**. '
                      'Enter a valid name to change it.'
            )
            await i.followup.send(embed=embed, ephemeral=True)

        await interaction.response.send_modal(NewNameModal(
            self.change_name,
            False,
            on_error
        ))

    @ui.button(label='Change Directory', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_DIRECTORY, row=1)
    async def select_button_directory(self,
                                      interaction: Interaction,
                                      _: ui.Button) -> None:
        """
        Open a modal prompting to the user to change the timelapse directory.

        Args:
            interaction: The interaction.
            _: This button.
        """

        await interaction.response.send_modal(ChangeDirectoryModal(
            self.set_directory,
            self._directory
        ))

    @ui.button(label='Set Camera', style=ButtonStyle.secondary,
               emoji=settings.EMOJI_CAMERA, row=2)
    async def select_button__camera(self,
                                    interaction: Interaction,
                                    button: ui.Button) -> None:
        """
        Replace the view with one prompting the user to select a camera from
        a dropdown.

        Args:
            interaction: The interaction.
            button: This button.
        """

        await interaction.response.defer()

        # Define the callback that actually changes updates the camera
        async def callback(camera: GCamera):
            self._camera = camera
            button.label = 'Change Camera'
            await self.refresh_display()

        # Send a new camera selector view
        try:
            await CameraSelector.create_selector(
                callback=callback,
                on_cancel=self.refresh_display,
                message=f"Choose a{'' if self._camera is None else ' new'} "
                        f"timelapse camera from the list below:",
                interaction=interaction,
                edit=True,
                default_camera=self._camera,
                cancel_danger=False
            )
        except NoCameraFound:
            _log.warning(f"Failed to get a camera for timelapse '{self._name}'")
            embed = utils.contrived_error_embed(
                'No cameras detected. Please connected a camera to the '
                'system, and try again.',
                'Missing Camera'
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def select_button_interval(self,
                                     interaction: Interaction) -> None:
        """
        Open a modal prompting to the user to change the interval between
        frames in the timelapses.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Send the modal
        await interaction.response.send_modal(ChangeIntervalModal(
            self.set_interval, self._interval
        ))

    async def select_button_runtime(self,
                                    interaction: Interaction) -> None:
        """
        Open a modal prompting to the user to set/change the runtime
        configuration.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Send the modal
        await interaction.response.send_modal(ChangeRuntimeModal(
            self._start_time,
            self._end_time,
            self._total_frames,
            self.set_runtime
        ))

    async def select_button_schedule(self) -> None:
        """
        Add a timelapse schedule for more complex and precise control of when
        it takes photos.
        """

        # Create a schedule builder
        await ScheduleBuilder(
            self.interaction,
            self._start_time,
            self._end_time,
            self._total_frames,
            self._schedule,
            self.set_schedule,  # primary callback
            self.refresh_display  # on cancel, just refresh the display
        ).refresh_display()

    @property
    def name(self) -> str:
        """
        Get the timelapse name.

        Returns:
            The name.
        """

        return self._name

    async def change_name(self, name: str) -> None:
        """
        Change the timelapse name. If the given name is actually new, the
        display is automatically refreshed.

        If the previous directory was derived from the previous name, this has
        the side effect of changing the directory too (if possible).

        Args:
            name: The new name.
        """

        # Do nothing if the name didn't change
        if self._name == name:
            return

        _log.debug(f"Changing timelapse name from '{self._name}' to '{name}'")

        # If the previous directory, is unset or uses the previous name, try to
        # change it based on the new name
        if self._directory is None or \
                self._name.lower() in self._directory.name.lower():
            new_dir = determine_default_directory(name)
            if new_dir is not None:
                _log.debug(f"Updated directory from '{self._directory}' "
                           f"to '{new_dir}'")
                self._directory = new_dir

        # Change the name
        self._name = name

        # Refresh the display
        await self.refresh_display()

    @property
    def schedule(self) -> Optional[Schedule]:
        """
        Get the timelapse schedule, if set.

        Returns:
            The schedule.
        """

        return self._schedule

    async def set_schedule(self,
                           start_time: Optional[datetime],
                           end_time: Optional[datetime],
                           total_frames: Optional[int],
                           new_schedule: Optional[Schedule]) -> None:
        """
        Set the runtime and timelapse schedule. It is assumed that at least
        something is actually changed by calling this (as opposed to, say
        change_name(), which could receive the existing name).

        Note that it is possible for the schedule to be None, meaning that it's
        either removed or the other parameters have been changed instead.

        After updating the schedule, this refreshes the display.

        Args:
            start_time: The (possibly new) runtime start.
            end_time: The (possibly new) runtime end.
            total_frames: The (possibly new) total frame threshold.
            new_schedule: The (possibly new) timelapse schedule.
        """

        await self.set_runtime(start_time, end_time, total_frames)
        self._schedule = new_schedule

        # Update the button text
        if new_schedule is None:
            self.button_schedule.label = 'Create a Schedule'
        else:
            self.button_schedule.label = 'Edit the Schedule'

        await self.refresh_display()
