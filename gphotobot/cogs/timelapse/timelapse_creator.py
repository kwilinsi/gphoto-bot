from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Optional

from discord import (ButtonStyle, Embed, Interaction, Message,
                     ui, utils as discord_utils)
from sqlalchemy.exc import SQLAlchemyError

from gphotobot import GphotoBot, settings, utils
from gphotobot.libgphoto import GCamera, gmanager, NoCameraFound
from gphotobot.sql import async_session_maker, State, Timelapse
from ..helper.camera_selector import CameraSelector, generate_camera_dict
from ..timelapse import timelapse_utils
from .change_directory_modal import ChangeDirectoryModal
from .interval_modal import ChangeIntervalModal
from .new_name_modal import NewNameModal
from .runtime_modal import ChangeRuntimeModal
from .schedule.schedule import Schedule
from .schedule.schedule_builder import ScheduleBuilder
from .validation import (InvalidTimelapseNameError, validate_name,
                         determine_default_directory)

_log = logging.getLogger(__name__)


class TimelapseCreator(utils.BaseView):
    def __init__(self,
                 parent: Interaction[GphotoBot] | utils.BaseView | Message,
                 name: str,
                 camera: GCamera | None,
                 directory: Path | None,
                 callback: Optional[Callable[[Timelapse],
                 Awaitable[None]]] = None,
                 callback_cancel: Optional[Callable[...,
                 Awaitable[None]]] = None,
                 timelapse: Timelapse | None = None) -> None:
        """
        Create a new view for helping the user make a timelapse.

        Args:
            parent: The interaction, view, or message to use when refreshing
            the display.
            name: The already-validated name of the timelapse.
            camera: The camera to use for the timelapse.
            directory: The directory for storing timelapse photos.
            callback: An async function to call when the timelapse is created.
            Defaults to None.
            callback_cancel: An async function to call when this is cancelled.
            Defaults to None.
            timelapse: An existing database timelapse record to edit. Defaults
            to None.
        """

        super().__init__(
            parent=parent,
            permission_error_msg='Type `/timelapse create` '
                                 'to make your own timelapse.',
            callback=callback,
            callback_cancel=callback_cancel
        )

        self._name = name
        self._camera: GCamera | None = camera
        self._directory: Path | None = directory

        # Default interval
        self._interval: timedelta | None = None

        # Start runtime conditions
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None
        self._total_frames: int | None = None

        # A timelapse schedule
        self._schedule: Schedule | None = None

        # Store the existing timelapse record, if one was given
        self._timelapse: Timelapse | None = timelapse
        if timelapse is not None:
            self._interval = timedelta(seconds=timelapse.capture_interval)
            self._start_time = timelapse.start_time
            self._end_time = timelapse.end_time
            self._total_frames = timelapse.total_frames
            s = Schedule.from_db(timelapse.schedule_entries)
            if len(s) > 0:
                self._schedule = s

        # Create the Save/Create button
        self.button_save_create = self.create_button(
            label='Create' if timelapse is None else 'Save',
            style=ButtonStyle.success,
            emoji=settings.EMOJI_DONE_CHECK if timelapse is None
            else settings.EMOJI_SAVE,
            callback=self.select_button_save_create,
            row=0
        )

        # Create the Info button
        self.button_info = self.create_button(
            label='Info',
            style=ButtonStyle.primary,
            emoji=settings.EMOJI_INFO,
            callback=self.select_button_info,
            row=0,
            auto_defer=False
        )

        # Create the Create/Save button
        self.button_cancel = self.create_button(
            label='Cancel',
            style=ButtonStyle.danger,
            emoji=settings.EMOJI_CANCEL,
            callback=self.select_button_cancel,
            row=0
        )

        # Create the button for changing the directory
        self.button_directory = self.create_button(
            label='Set Directory' if directory is None else 'Change Directory',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_DIRECTORY,
            callback=self.select_button_directory,
            row=1,
            auto_defer=False
        )

        # Create the button for changing the camera
        self.button_camera = self.create_button(
            label='Set Camera' if camera is None else 'Change Camera',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CAMERA,
            callback=self.select_button_camera,
            row=2
        )

        # Create the interval button
        self.button_interval = self.create_button(
            label=('Set' if self.interval is None else 'Change') + ' Interval',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_TIME_INTERVAL,
            callback=self.select_button_interval,
            auto_defer=False,
            row=2
        )

        # Get runtime button
        self.button_runtime = self.create_button(
            label='Set Runtime' if self.start_time is None and
                                   self.end_time is None
            else 'Change the Runtime',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_SET_RUNTIME,
            callback=self.select_button_runtime,
            auto_defer=False,
            row=3,
        )

        # Create the schedule button
        self.button_schedule = self.create_button(
            label='Create a Schedule' if self.schedule is None
            else 'Edit the Schedule',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CREATE_SCHEDULE,
            callback=lambda _: self.select_button_schedule(),
            row=3
        )

        _log.info(f"Opening a new "
                  f"{'creator' if self._timelapse is None else 'editor'} "
                  f"for the timelapse '{name}'")

    @classmethod
    async def create_new(
            cls,
            parent: Interaction[GphotoBot] | utils.BaseView | Message,
            name: str,
            do_validate: bool = True) -> None:
        """
        Create a new timelapse creator view. This gets some default values and
        builds the initial timelapse creation panel.

        Args:
            parent: The interaction, view, or message to use when refreshing
            the display.
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
        await cls(parent, name, camera, directory).refresh_display()

    @classmethod
    async def edit_existing(
            cls,
            parent: Interaction[GphotoBot] | utils.BaseView | Message,
            timelapse: Timelapse,
            callback: Callable[[Timelapse], Awaitable[None]],
            callback_cancel: Callable[[...], Awaitable[None]],
    ) -> None:
        """
        Create a view for editing an existing timelapse.

        Args:
            parent: The interaction, view, or message to use when refreshing
            the display.
            timelapse: The timelapse to edit.
            callback: The async function to run when the user clicks "Save".
            callback_cancel: The async function to run if the user clicks
            "Cancel".
        """

        await cls(
            parent=parent,
            name=timelapse.name,
            camera=await gmanager.get_camera(timelapse.camera),
            directory=Path(timelapse.directory),
            callback=callback,
            callback_cancel=callback_cancel,
            timelapse=timelapse
        ).refresh_display()

    @property
    def name(self) -> str:
        """
        Get the timelapse name.

        Returns:
            The name.
        """

        return self._name

    def safe_name(self) -> str:
        """
        Get the timelapse name with markdown characters escaped.

        Returns:
            The timelapse name, safe for use in Discord.
        """

        return discord_utils.escape_markdown(self.name)

    async def set_name(self, name: str) -> None:
        """
        Set the timelapse name. If the given name is actually new, the display
        is automatically refreshed.

        If the previous directory was derived from the previous name, this has
        the side effect of changing the directory too (if possible).

        Args:
            name: The new name.
        """

        # Do nothing if the name didn't change
        if self.name == name:
            return

        _log.debug(f"Changing timelapse name from '{self.name}' to '{name}'")

        # If the previous directory, is unset or uses the previous name, try to
        # change it based on the new name
        if self.directory is None or \
                self.name.lower() in self.directory.name.lower():
            await self.set_directory(determine_default_directory(name),
                                     refresh=False)

        # Change the name
        self._name = name

        # Change in the timelapse record too, if there is one
        if self._timelapse is not None:
            self._timelapse.name = name

        # Refresh the display
        await self.refresh_display()

    @property
    def directory(self) -> Path | None:
        return self._directory

    async def set_directory(self,
                            directory: Path | None,
                            refresh: bool = True) -> None:
        """
        Change the directory. If the directory is currently unset, this has the
        side effect of renaming the "Set Directory" button back to "Change
        Directory".

        Args:
            directory: The new directory. If this is None, nothing happens. The
            directory is not cleared.
            refresh: Whether to refresh the display if the name changes. This
            should always be done unless you're about to refresh it anyway.
            Defaults to True.
        """

        # Do nothing if the input is None
        if directory is None:
            return

        # Change in the timelapse record, if there is one
        if self._timelapse is not None:
            self._timelapse.directory = str(directory)

        # Update the directory
        if self.directory is None:
            self.button_directory.label = 'Change Directory'
            self._directory = directory
            _log.debug(f"Updated directory from None to '{directory}'")
        elif self.directory != directory:
            _log.debug(f"Updated directory from '{self.directory}' "
                       f"to '{directory}'")
            self._directory = directory
            if refresh:
                await self.refresh_display()

    @property
    def interval(self) -> Optional[timedelta]:
        return self._interval

    async def set_interval(self, interval: timedelta) -> None:
        """
        Change the interval. If the interval is currently unset, this has the
        side effect of renaming the "Set Interval" to "Change Interval".

        If the interval changes, this also refreshes the display.

        Args:
            interval: The new interval.
        """

        assert interval is not None  # Just making sure

        if self.interval is None:
            utils.get_button(self, 'Set Interval').label = \
                'Change Interval'
        elif self.interval == interval:
            return

        # Change the interval
        self._interval = interval

        # Change in the timelapse record too, if there is one
        if self._timelapse is not None:
            self._timelapse.capture_interval = interval.total_seconds()

        await self.refresh_display()

    @property
    def start_time(self) -> datetime | None:
        return self._start_time

    @property
    def end_time(self) -> datetime | None:
        return self._end_time

    @property
    def total_frames(self) -> int | None:
        return self._total_frames

    async def set_runtime(self,
                          start_time: datetime | None,
                          end_time: datetime | None,
                          total_frames: int | None) -> None:
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

        # If nothing changed, exit
        if total_frames == self.total_frames and \
                start_time == self.start_time and \
                end_time == self.end_time:
            return

        # Update the values
        self._start_time = start_time
        self._end_time = end_time
        self._total_frames = total_frames

        # Change in the timelapse record too, if there is one
        if self._timelapse is not None:
            self._timelapse.start_time = start_time
            self._timelapse.end_time = end_time
            self._timelapse.total_frames = total_frames

        # Refresh the display
        await self.refresh_display()

    @property
    def camera(self) -> Optional[GCamera]:
        return self._camera

    async def set_camera(self, camera: GCamera) -> None:
        """
        Set the camera, and refresh the display.

        Args:
            camera: The new camera.
        """

        assert camera is not None  # Just in case

        # Change the button, in case the camera was previously None
        self.button_camera = 'Change Camera'

        # Update the value
        self._camera = camera

        # Change in the timelapse record too, if there is one
        if self._timelapse is not None:
            async with (async_session_maker(expire_on_commit=False) as session,
                        session.begin()):
                self._timelapse.camera = \
                    await camera.sync_with_database(session)

        # Update the display
        await self.refresh_display()

    @property
    def schedule(self) -> Optional[Schedule]:
        """
        Get the timelapse schedule, if set.

        Returns:
            The schedule.
        """

        return self._schedule

    @property
    def owner_mention(self) -> str:
        return (self.user.mention if self._timelapse is None
                else f'<@!{self._timelapse.user_id}>')

    async def set_schedule(self,
                           start_time: datetime | None,
                           end_time: datetime | None,
                           total_frames: int | None,
                           new_schedule: Schedule | None) -> None:
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

        # Change in the timelapse record too, if there is one
        if self._timelapse is not None:
            entries = (
                [] if new_schedule is None
                else new_schedule.to_db(self._timelapse.id, force_copy=True)
            )
            self._timelapse.schedule_entries = entries
            self._timelapse.has_schedule = len(entries) > 0

        # Update the button text
        if new_schedule is None:
            self.button_schedule.label = 'Create a Schedule'
        else:
            self.button_schedule.label = 'Edit the Schedule'

        # Update the display
        await self.refresh_display()

    async def build_embed(self, *args, **kwargs) -> Embed:
        """
        Construct an embed with the info about this timelapse. This embed is
        associated with the buttons in this view.

        Returns:
            The embed.
        """

        # Get the camera name
        if self.camera is None:
            camera = '*undefined*'
        else:
            camera = utils.trunc(self.camera.name, 75, escape_markdown=True)

        # Create the base embed
        embed = utils.default_embed(
            title='Create a Timelapse' if self._timelapse is None
            else 'Edit the Timelapse',
            description=f"**Name:** {self.safe_name()}\n"
                        f"**Owner:** {self.owner_mention}\n"
                        f"**Camera:** {camera}"
        )

        # Add directory info
        if self.directory is None:
            # The directory can never be removed. If missing, it was never
            # chosen due to being too long
            directory = '*[Undefined: default path was too long]*'
        else:
            directory = f'`{self.directory}`'

        embed.add_field(name='Directory', value=directory, inline=False)

        # Add interval
        if self.interval is None:
            interval = '*Undefined*'
        else:
            interval = utils.format_duration(self.interval,
                                             always_decimal=True)

        embed.add_field(name='Capture Interval', value=interval, inline=False)

        # Add runtime info
        runtime_text = timelapse_utils.generate_embed_runtime_text(
            self.start_time,
            self.end_time,
            self.total_frames
        )
        embed.add_field(name='Runtime', value=runtime_text, inline=False)

        # Add schedule
        if self.schedule is not None:
            embed.add_field(
                name='Schedule',
                value=self.schedule.get_summary_str(),
                inline=False
            )

        # Return finished embed
        return embed

    async def select_button_save_create(self, interaction: Interaction) -> None:
        """
        Create this timelapse, and add it to the database. Switch to a new
        display for controlling the created timelapse.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Validate the timelapse values to catch any problems
        try:
            self.validate()
        except utils.ValidationError as e:
            await interaction.followup.send(embed=utils.contrived_error_embed(
                title=f"Error: Invalid {e.attr}",
                text=e.msg
            ), ephemeral=True)
            return

        # If there's a timelapse record, we're in edit mode. Send that to the
        # callback function
        if self._timelapse is not None:
            await self.callback(self._timelapse)
            _log.debug(f"Saved changes to timelapse: '{self.name}'")
            return

        # Otherwise, create a new timelapse record in the database

        try:
            async with (async_session_maker(expire_on_commit=False) as session,
                        session.begin()):
                tl = await self.to_db()
                session.add(tl)
        except SQLAlchemyError as e:
            await interaction.followup.send(embed=utils.error_embed(
                e,
                text='Failed to save this timelapse to the database. Please '
                     'try again later or report a bug.'
            ))
            return

        _log.info(f"Created a new timelapse: '{self.name}'")

        # Create an executor in case it should start automatically. The result
        # value is irrelevant, though, as no matter what happens with an
        # executor, the timelapse was created
        from .execute import TIMELAPSE_COORDINATOR
        await TIMELAPSE_COORDINATOR.create_executor(tl)

        # Send a confirmation dialog, so the user knows it worked
        await utils.ConfirmationDialog(
            parent=self,
            title='Success!',
            description=f"Created the new timelapse **{self.safe_name()}** "
                        f"and saved it to the database."
        ).refresh_display()
        self.stop()

    async def to_db(self) -> Timelapse:
        """
        Construct a database record for this timelapse.

        This does not attempt to validate any parameters.

        Returns:
            The new timelapse record to send to the database.
        """

        schedule = self.schedule

        return Timelapse(
            camera_id=await self.camera.get_db_id(),
            name=self.name,
            user_id=self.user.id,
            directory=str(self.directory),
            start_time=self.start_time,
            end_time=self.end_time,
            capture_interval=self.interval.total_seconds(),
            total_frames=self.total_frames,
            state=State.READY if self.start_time is None else State.WAITING,
            has_schedule=schedule is not None and len(schedule) > 0,
            schedule_entries=[] if schedule is None else schedule.to_db()
        )

    def validate(self) -> None:
        """
        Validate the input to this timelapse. Run this right before saving to
        the database to catch any last errors.

        Raises:
            ValidationError: If there is any problem with the timelapse. This
            includes a user-friendly error message.
        """

        if self.directory is None:
            raise utils.ValidationError(
                attr='Directory',
                msg='You must specify a directory for saving timelapse photos.'
            )

        if self.camera is None:
            raise utils.ValidationError(
                attr='Camera',
                msg='You must specify a camera to take the timelapse photos.'
            )

        if self.interval is None:
            raise utils.ValidationError(
                attr='Interval',
                msg='You must specify an overall interval between capturing '
                    'photos.'
            )

    @staticmethod
    async def select_button_info(interaction: Interaction) -> None:
        """
        Show the user information about timelapses, as if they had run the
        `/timelapse info` command.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        await interaction.response.send_message(
            content='This is some info on timelapses!',
            ephemeral=True
        )

    async def select_button_cancel(self, _: Interaction) -> None:
        """
        Cancel this timelapse creator.

        Args:
            _: The interaction that triggered this UI event.
        """

        if self.callback_cancel is not None:
            # If there's a cancel callback, run that.
            await self.callback_cancel()
        else:
            # Otherwise, delete the message
            await self.delete_original_message()

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
            self.set_name,
            False,
            on_error
        ))

    async def select_button_directory(self, interaction: Interaction) -> None:
        """
        Open a modal prompting to the user to change the timelapse directory.

        Args:
            interaction: The interaction.
        """

        await interaction.response.send_modal(ChangeDirectoryModal(
            self.set_directory,
            self.directory
        ))

    async def select_button_camera(self, interaction: Interaction) -> None:
        """
        Replace the view with one prompting the user to select a camera from
        a dropdown.

        Args:
            interaction: The interaction.
        """

        # Send a new camera selector view
        try:
            await CameraSelector(
                parent=interaction,
                callback=self.set_camera,
                on_cancel=self.refresh_display,
                cameras=await generate_camera_dict(),
                message=f"Choose a{'' if self._camera is None else ' new'} "
                        f"timelapse camera from the list below:",
                default_camera=self._camera,
                cancel_danger=False
            ).refresh_display()
        except NoCameraFound:
            _log.warning(f"Failed to get a camera for timelapse '{self.name}'")
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
            self,
            self._start_time,
            self._end_time,
            self._total_frames,
            self._schedule,
            self.set_schedule,  # primary callback
            self.refresh_display  # on cancel, just refresh the display
        ).refresh_display()
