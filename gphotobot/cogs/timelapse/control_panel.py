import asyncio
from copy import deepcopy
from datetime import datetime
import logging
from typing import Optional

from discord import ButtonStyle, Interaction, Embed, utils as discord_utils
from gphoto2 import GPhoto2Error
from sqlalchemy.exc import SQLAlchemyError

from gphotobot import settings, utils
from gphotobot.libgphoto import GCamera, gutils
from gphotobot.sql import async_session_maker, State, Timelapse
from . import timelapse_utils
from .execute import Coordinator, TimelapseExecutor
from .schedule.schedule import Schedule
from .timelapse_creator import TimelapseCreator

_log = logging.getLogger(__name__)


class TimelapseControlPanel(utils.BaseView):
    def __init__(self,
                 interaction: Interaction,
                 timelapse: Timelapse,
                 camera: GCamera):
        """
        Initialize a TimelapseInfoPanel, which allows the user to fully control
        a timelapse.

        Args:
            interaction: The interaction that triggered this panel.
            timelapse: The timelapse to control.
            camera: The GCamera object that matches the camera associated with
            this timelapse in the database.
        """

        super().__init__(
            interaction,
            permission_error_msg='If you want to control an existing '
                                 'timelapse, type `/timelapse show`. Or type '
                                 '`/timelapse create` to make a new one.'
        )

        # Save the passed parameters
        self.timelapse: Timelapse = timelapse
        self.camera: GCamera = camera

        # Get the coordinator and timelapse executor running this timelapse
        from .execute import TIMELAPSE_COORDINATOR
        self.coordinator: Coordinator = TIMELAPSE_COORDINATOR
        self.executor: Optional[TimelapseExecutor] = \
            TIMELAPSE_COORDINATOR.get_executor(timelapse.id)

        # Register a listener that runs when the executor changes state/interval
        if self.executor is not None:
            self._t = asyncio.create_task(
                self.executor.register_listener(self.on_executor_state_change)
            )

        # Get the timelapse owner and the schedule from the db record
        self.owner_id: int = timelapse.user_id
        self.schedule: Schedule = Schedule.from_db(timelapse.schedule_entries)

        #################### ADD COMPONENTS ####################

        # Row 1: START/STOP, PAUSE/RESUME, INFO

        label, emoji, style, enabled = self.get_start_stop_button_settings()
        self.button_start_stop = self.create_button(
            label=label,
            style=style,
            emoji=emoji,
            disabled=not enabled,
            callback=self.clicked_start_stop,
            interaction_check=self.require_owner,
            row=0
        )

        label, emoji, style, enabled = self.get_pause_resume_button_settings()
        self.button_pause_resume = self.create_button(
            label=label,
            style=style,
            emoji=emoji,
            disabled=not enabled,
            callback=self.clicked_pause_resume,
            interaction_check=self.require_owner,
            row=0
        )

        self.button_info = self.create_button(
            label='Info',
            style=ButtonStyle.primary,
            emoji=settings.EMOJI_INFO,
            callback=self.clicked_info,
            row=0
        )

        # Row 2: EDIT, DELETE, CLOSE

        self.button_edit = self.create_button(
            label='Edit',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_EDIT,
            callback=self.clicked_edit,
            interaction_check=self.require_owner,
            row=1
        )

        self.button_delete = self.create_button(
            label='Delete',
            style=ButtonStyle.danger,
            emoji=settings.EMOJI_DELETE,
            callback=self.clicked_delete,
            interaction_check=self.require_owner,
            row=1
        )

        self.button_close = self.create_button(
            label='Close',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CLOSE,
            callback=self.clicked_close,
            row=1
        )

        # Row 3: PREVIEW, GALLERY

        self.button_preview = self.create_button(
            label='Preview',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_PREVIEW_IMAGE,
            callback=self.clicked_preview,
            auto_defer=False,
            row=2
        )

        self.button_take_picture = self.create_button(
            label='Take Picture',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_CAMERA,
            callback=self.clicked_take_picture,
            interaction_check=self.require_owner,
            auto_defer=False,
            row=2
        )

        self.button_gallery = self.create_button(
            label='Gallery',
            style=ButtonStyle.secondary,
            emoji=settings.EMOJI_GALLERY,
            callback=self.clicked_gallery,
            row=2
        )

        # Final debug message for successful creation
        _log.debug(f'Created a timelapse control panel for {timelapse.name}')

    @property
    def timelapse_id(self) -> int:
        return self.timelapse.id

    @property
    def name(self) -> str:
        return self.timelapse.name

    @property
    def directory(self) -> str:
        return self.timelapse.directory

    @property
    def start_time(self) -> datetime:
        return self.timelapse.start_time

    @property
    def end_time(self) -> datetime:
        return self.timelapse.end_time

    @property
    def capture_interval(self) -> float:
        return self.timelapse.capture_interval

    @property
    def frames(self) -> int:
        return self.timelapse.frames if self.executor is None \
            else self.executor.frame_count

    @property
    def total_frames(self) -> int:
        return self.timelapse.total_frames

    @property
    def state(self) -> State:
        return self.timelapse.state

    @state.setter
    def state(self, state: State) -> None:
        self.timelapse.state = state

    async def build_embed(self, *args, **kwargs) -> Embed:
        """
        Build an embed with information about the timelapse.

        Returns:
            An embed.
        """

        # Construct the base embed
        embed: Embed = utils.default_embed(
            title='Timelapse Control Panel',
            description=f'**Name:** {discord_utils.escape_markdown(self.name)}'
                        f'\n**Directory:** `{self.timelapse.directory}`'
        )

        # Add a camera field
        addr = utils.trunc(self.camera.addr, 20, escape_markdown=True)
        embed.add_field(
            name='Camera',
            value=f'{self.camera.name}\n`{addr}`\n'
                  f'(DB ID: `{await self.camera.get_db_id()}`)'
        )

        # Add owner field
        embed.add_field(name='Owner', value=f'<@!{self.owner_id}>')

        # Add current state and frame count
        embed.add_field(
            name='Status',
            value=f"{self.state.name}\n"
                  f"{self.frames} frame{'' if self.frames == 1 else 's'}"
        )

        # Determine the current capture interval and the timelapse default
        def_interval: float = self.timelapse.capture_interval
        cur_interval = def_interval if self.executor is None else \
            self.executor.seconds

        # Get a string with the capture interval
        if def_interval == cur_interval:
            interval = 'One frame every ' + utils.format_duration(def_interval)
        else:
            interval = (f'Currently {utils.format_duration(cur_interval)} '
                        f'(default is {utils.format_duration(def_interval)})')

        # Add field with capture interval
        embed.add_field(name='Interval', value=interval)

        # Add start time and end condition
        runtime_text = timelapse_utils.generate_embed_runtime_text(
            self.start_time,
            self.end_time,
            self.total_frames
        )
        embed.add_field(name='Runtime', value=runtime_text)

        return embed

    def get_start_stop_button_settings(self) -> \
            tuple[str, Optional[str], ButtonStyle, bool]:
        """
        Generate information for the start/stop button based on the current
        timelapse state and runtime:
        - The label.
        - An emoji.
        - The button style.
        - Whether to enable (True) or disable (False) the button.

        Returns:
            The label, emoji, style, and whether to enable it.
        """

        if self.state == State.READY:
            # Just waiting for the user to click start
            return "Start", settings.EMOJI_START, ButtonStyle.success, True

        elif self.state == State.WAITING and self.start_time is not None and \
                self.start_time > datetime.now():
            # Hasn't started yet but has start time
            return "Start Early", settings.EMOJI_START, \
                ButtonStyle.success, True

        elif self.state == State.FINISHED:
            # This sets it into FORCE_RUNNING mode
            return "Continue", settings.EMOJI_CONTINUE, \
                ButtonStyle.primary, True

        elif self.state == State.FORCE_RUNNING or \
                (self.state == State.RUNNING and self.end_time is None):
            # Either force_running, or it just runs until the user stops it
            return "Stop", settings.EMOJI_STOP, ButtonStyle.danger, True

        elif self.state in (State.WAITING, State.RUNNING, State.PAUSED):
            # It's already started. Disabled button; colored green normally
            # but gray if PAUSED so that the emphasis is on the green resume
            # button
            return (
                "Start", settings.EMOJI_START,
                ButtonStyle.secondary if self.state == State.PAUSED
                else ButtonStyle.success,
                False
            )

        else:
            raise ValueError(f"Unreachable: invalid state {self.state.name}")

    def get_pause_resume_button_settings(self) -> \
            tuple[str, Optional[str], ButtonStyle, bool]:
        """
        Generate information for the pause/resume button based on the current
        timelapse state and runtime:
        - The label.
        - An emoji.
        - The button style.
        - Whether to enable (True) or disable (False) the button.

        Returns:
            The label, emoji, and whether to enable it.
        """

        if self.state == State.READY or self.state == State.FINISHED:
            # Can't pause if not running
            return "Pause", settings.EMOJI_PAUSE, ButtonStyle.secondary, False

        elif self.state == State.FORCE_RUNNING and \
                self.end_time is not None and self.end_time <= datetime.now():
            # In FORCE_RUNNING after it should have ended, you can only stop it
            return "Pause", settings.EMOJI_PAUSE, ButtonStyle.secondary, False

        elif self.state in (State.WAITING, State.RUNNING, State.FORCE_RUNNING):
            # Can pause while running, waiting, or running early
            return "Pause", settings.EMOJI_PAUSE, ButtonStyle.secondary, True

        elif self.state == State.PAUSED:
            # Can only resume once paused
            return "Resume", settings.EMOJI_RESUME, ButtonStyle.success, True

        else:
            raise ValueError(f"Unreachable: invalid state {self.state.name}")

    def update_start_pause_buttons(self) -> None:
        """
        Update the start/stop and pause/resume buttons to reflect the current
        timelapse state.
        """

        # Update the start/stop button
        label, emoji, style, enable = self.get_start_stop_button_settings()
        self.button_start_stop.label = label
        self.button_start_stop.emoji = emoji
        self.button_start_stop.style = style
        self.button_start_stop.enable = enable

        # Update the pause/remove button
        label, emoji, style, enable = self.get_pause_resume_button_settings()
        self.button_pause_resume.label = label
        self.button_pause_resume.emoji = emoji
        self.button_pause_resume.style = style
        self.button_pause_resume.enable = enable

    async def require_owner(self, interaction: Interaction) -> bool:
        """
        This is an interaction check added to buttons that can only be used by
        the owner of the timelapse.

        If the user is not the owner, this sends an ephemeral error message
        and returns False.

        Args:
            interaction: The interaction that triggered this check.

        Returns:
            True if and only if the user is the owner of the timelapse.
        """

        # If the user is the owner, allow the interaction to go through
        if interaction.user.id == self.owner_id:
            return True

        # Send an error message to the user
        embed = utils.contrived_error_embed(
            title='Permission Denied',
            text="Sorry, only the owner of the timelapse can do that. You "
                 "can create your own timelapse with `/timelapse create`."
        )
        # Send message with create_task(). Can't 'await' or it'll deadlock
        print('sending error')
        asyncio.create_task(
            interaction.response.send_message(embed=embed, ephemeral=True)
        )

        # Log a debug message
        _log.debug(f'Blocked user {interaction.user.display_name} '
                   f'(id {interaction.user.id}) from using a component '
                   f'reserved for owner on timelapse {self.name}')

        # Return False to block this interaction
        return False

    async def clicked_start_stop(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the start/stop button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Save the initial state to check for changes
        initial_state: State = self.state

        if self.state == State.WAITING:
            # If clicking start while waiting, either the user is trying to
            # FORCE_RUNNING early, or there's a bug
            if self.start_time is None:
                _log.warning("Unreachable: user clicked start while state "
                             f"was {State.WAITING.name} and start time wasn't "
                             f"set; should have been {State.READY.name}")
                # Pretend it *was* State.READY
                self.state = State.READY
            elif self.start_time > datetime.now():
                # Start time is in the future. Force run now
                self.state = State.FORCE_RUNNING
            else:
                # If we passed the start time, then either (a) the start button
                # was left enabled by a bug, or (b) there was some race
                # condition where the embed was rendered *before* the start time
                # but then the user sat around waiting before clicking "Start",
                # and by that time the timelapse had started. (Notably the user
                # would have to be quick, as the state listener registered on
                # the executor should trigger an embed update as soon as the
                # executor starts running). Anyway, this is probably nothing
                # to worry about. Just log a message and re-render the embed
                _log.warning("User clicked start wile state was "
                             f"{State.WAITING.name} and start time already "
                             f"passed. This is probably a race condition "
                             f"issue and nothing to worry about")

        # This is intentionally if and not elif, just for this one case, to
        # allow resolution of WAITING to READY in the previous case
        if self.state == State.READY:
            # Timelapse is ready, and the user started it

            if self.end_time is not None and self.end_time < datetime.now():
                embed = utils.contrived_error_embed(
                    title='Timelapse Already Ended',
                    text='The timelapse already passed its end time and should '
                         f'have been marked {State.FINISHED.name}'
                )
                interaction.followup.send(embed=embed, ephemeral=True)
                self.state = State.FINISHED
            else:
                self.state = State.RUNNING

        elif self.state == State.RUNNING:
            # User clicked "Stop" while running, because there's no end time

            if self.end_time is not None:
                _log.warning('User clicked stop button during RUNNING state '
                             'with an end time set. It should have been '
                             'disabled')  # woops ¯\_(ツ)_/¯
            else:
                self.state = State.FINISHED

        elif self.state == State.PAUSED:
            # This shouldn't be possible

            embed = utils.contrived_error_embed(
                title='Unexpected Error',
                text=f"Can't \"{self.button_start_stop.label}\" the timelapse "
                     f"when it's paused. Click \"Resume\" to start it."
            )
            interaction.followup.send(embed=embed, ephemeral=True)

        elif self.state == State.FORCE_RUNNING:
            # The user wants to stop the manual force run override

            if self.end_time is not None and self.end_time <= datetime.now():
                # If we're past the end time, it's now finished
                self.state = State.FINISHED
            elif self.start_time is not None and \
                    self.start_time > datetime.now():
                # It hasn't reached the start time yet. Wait for it to start
                # like normal without the manual override
                self.state = State.WAITING
            else:
                # The timelapse should be running anyway, but it's in
                # FORCE_RUNNING mode. This is similar to the WAITING issue
                # above. It could happen if the button was accidentally left
                # enabled or there was a race condition where the user clicked
                # the button *just* after reaching the start time
                _log.warning("User clicked stop wile state was "
                             f"{State.FORCE_RUNNING.name} and start time "
                             f"already passed. This is probably a race "
                             f"condition issue and nothing to worry about")

        elif self.state == State.FINISHED:
            # The timelapse already finished, but the user choose to start
            # again. If there's no end time, this goes back to RUNNING. If
            # there's an end time, it's FORCE_RUNNING
            if self.end_time is None:
                self.state = State.RUNNING
            else:
                self.state = State.FORCE_RUNNING

        # If the state changed, notify the timelapse coordinator, and update
        # the database record
        if self.state != initial_state:
            await self.on_update()

        # Update the start/end and pause/resume buttons
        self.update_start_pause_buttons()

        # Then re-render the display
        await self.refresh_display()

    async def clicked_pause_resume(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the pause/resume
        button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Save the initial state to check for changes
        initial_state: State = self.state

        # In the READY state, this button should have been disabled
        if self.state == State.READY:
            embed = utils.contrived_error_embed(
                title="Timelapse Hasn't Started",
                text="The timelapse hasn't started yet, so you can't "
                     f"{self.button_pause_resume.label.lower()} it. It's "
                     f"currently {State.READY.name} to begin. Click start to "
                     f"run it."
            )
            interaction.followup.send(embed=embed, ephemeral=True)

        # In FINISHED state, this button should have been disabled
        elif self.state == State.FINISHED:
            embed = utils.contrived_error_embed(
                title="Timelapse Finished",
                text=f"The timelapse is already {State.FINISHED.name}, so you "
                     f"can't {self.button_pause_resume.label.lower()} it."
            )
            interaction.followup.send(embed=embed, ephemeral=True)

        # If FORCE_RUNNING after it *ended*, you can only stop it, not pause
        elif self.state == State.FORCE_RUNNING and \
                self.end_time is not None and self.end_time <= datetime.now():
            embed = utils.contrived_error_embed(
                title=f"Can't {self.button_pause_resume.label.capitalize()} "
                      "Timelapse",
                text="The timelapse was set to continue running after "
                     "finishing. You can stop it, but you can't "
                     f"{self.button_pause_resume.label.lower()} it."
            )
            interaction.followup.send(embed=embed, ephemeral=True)

        # When PAUSED, it can only be resumed
        elif self.state == State.PAUSED:

            # If it already should have ended, set to FINISHED. This shouldn't
            # be possible, but it could happen in a race condition where the
            # end time was reached just before the user clicked "resume"
            if self.end_time is not None and self.end_time <= datetime.now():
                self.state = State.FINISHED

            # Otherwise, just set it to WAITING. If it should be RUNNING, the
            # executor will figure that out and adjust accordingly.
            else:
                self.state = State.WAITING

        # In all of these states, it can be paused
        elif self.state in (State.WAITING, State.RUNNING, State.FORCE_RUNNING):
            self.state = State.PAUSED

        # Every state should have been accounted for already
        else:
            raise ValueError(f"Unreachable: invalid state {self.state.name}")

        # If the state changed, notify the timelapse coordinator, and update
        # the database record
        if self.state != initial_state:
            await self.on_update()

        # Update the start/end and pause/resume buttons
        self.update_start_pause_buttons()

        # Then re-render the display
        await self.refresh_display()

    async def on_update(self) -> None:
        """
        This is called by clicked_start_stop() and clicked_pause_resume() when
        the user edits the timelapse.

        This updates the associated executor if one exists and attempts to
        create a new executor if it doesn't exist. This also updates the
        timelapse record in the database.
        """

        # Update the database first to fast-fail on a SQLAlchemyError
        await self.save_timelapse_to_db()

        if self.executor is None:
            # If there's no executor, try to create one
            # (PyCharm linter just REFUSES to understand Coordinator type)
            result = await self.coordinator.create_executor(  # noqa
                deepcopy(self.timelapse)
            )
            _log.info(("Created" if result else "Didn't create") +
                      f" executor for timelapse '{self.name}'")
        else:
            # Update the existing executor
            result = await self.coordinator.update_executor(  # noqa
                self.executor, deepcopy(self.timelapse)
            )
            if result == True:  # noqa
                _log.info(f"Updated executor for timelapse '{self.name}'")
            elif result == False:  # noqa
                _log.info(f"Removed executor for timelapse '{self.name}'")
            else:
                _log.info(f"Executor for timelapse '{self.name}' not changed")

        # Get the new executor in case it was created, removed, or replaced
        self.executor = self.coordinator.get_executor(  # noqa
            self.timelapse_id
        )

    async def clicked_info(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the info button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        ...

    async def clicked_edit(self, _: Interaction) -> None:
        """
        This callback function runs when the user clicks the edit button.

        Args:
            _: The interaction that triggered this UI event.
        """

        await TimelapseCreator.edit_existing(
            parent=self,
            timelapse=deepcopy(self.timelapse),
            callback=self.on_timelapse_edited,
            callback_cancel=self.refresh_display
        )

    async def clicked_delete(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the delete button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        ...

    async def clicked_close(self, _: Interaction) -> None:
        """
        This callback function runs when the user clicks the close button.

        Args:
            _: The interaction that triggered this UI event.
        """

        await self.delete_original_message()
        self.stop()

    async def clicked_preview(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the preview button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        # Defer a response
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            async with gutils.preview_image_embed(self.camera) as (embed, file):
                await interaction.followup.send(
                    file=file, embed=embed, ephemeral=True
                )
        except GPhoto2Error as error:
            await gutils.handle_gphoto_error(
                interaction, error,
                f'Failed to capture preview with {self.camera}'
            )

    async def clicked_take_picture(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the take picture
        button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        ...

    async def clicked_gallery(self, interaction: Interaction) -> None:
        """
        This callback function runs when the user clicks the gallery button.

        Args:
            interaction: The interaction that triggered this UI event.
        """

        ...

    async def save_timelapse_to_db(self, update_frames: bool = True) -> None:
        """
        Save the current timelapse record to the database, overwriting whatever
        else is there.

        Args:
            update_frames: Whether to first update the total frame count from
            the executor before saving to the database.
        """

        async with (async_session_maker(expire_on_commit=False) as session,
                    session.begin()):
            # Update frame count
            if update_frames:
                self.timelapse.frames = self.frames

            # Add to session; it'll commit while exiting the context manager
            await session.merge(self.timelapse)

    async def on_executor_state_change(self, state: State) -> None:
        """
        This listener is attached to the executor and is triggered whenever it
        updates the timelapse state.

        Args:
            state: The new state.
        """

        self.state = state
        self.update_start_pause_buttons()
        await self.refresh_display()

    async def on_timelapse_edited(self, timelapse: Timelapse) -> None:
        """
        This callback function runs when the user finishes editing the
        timelapse. It may or may not have changed in the process.

        Args:
            timelapse: The edited timelapse.
        """

        initial_timelapse = self.timelapse
        self.timelapse = timelapse

        # Try to update the timelapse record and executor
        try:
            await self.on_update()
        except (SQLAlchemyError, AssertionError) as e:
            # Catch SQLAlchemyErrors and AssertionErrors, which are sometimes
            # raised by SQLAlchemy here. If they fail, revert to the original
            # timelapse
            _log.error("Fatal exception updating the "
                       f"'{initial_timelapse.name}' timelapse from the "
                       f"control panel: {e}")
            self.timelapse = initial_timelapse

        # Refresh the display
        await self.refresh_display()
