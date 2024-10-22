from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import logging
from typing import Literal, Union

from gphotobot.sql import async_session_maker, State, Timelapse
from gphotobot.utils import utils
from gphotobot.utils.base.task_loop import TaskLoop
from .executor_event import ExecutorEvent
from ..schedule.schedule import Schedule

_log = logging.getLogger(__name__)


class TimelapseExecutor(TaskLoop):
    def __init__(self,
                 timelapse: Timelapse,
                 stop_callback: Callable[[TimelapseExecutor],
                 Awaitable[None]]) -> None:
        """
        Initialize an executor task that captures photos for a particular
        timelapse.

        Args:
            timelapse: The timelapse run by this executor.
            stop_callback: An async function to call if the timelapse stops
            or is cancelled for any reason.
        """

        # Initialize this task using the timelapse interval and name
        super().__init__(
            name=timelapse.name,
            seconds=timelapse.capture_interval,
            start=False
        )

        self.stop_callback: Callable[[TimelapseExecutor],
        Awaitable[None]] = stop_callback
        self.frame_count: int = 0

        # Tracks whether cancel() was called on this executor
        self.cancelling: bool = False

        self.timelapse: Timelapse = timelapse
        self.schedule: Schedule = Schedule.from_db(timelapse.schedule_entries)

    @property
    def id(self) -> int:
        return self.timelapse.id

    @property
    def name(self) -> str:
        return self.timelapse.name

    def __str__(self) -> str:
        """
        Return a string with information about this executor. This is intended
        for debugging purposes. It includes:
        - The timelapse id and name
        - The current timelapse state
        - The current capture interval

        Returns:
            A formatted string with basic info.
        """

        return (f"{self.name}({self.id})_{self.timelapse.state.name}_"
                f"int={utils.format_duration(self.seconds, spaces=False)}")

    def cancel(self) -> None:
        super().cancel()

        # Only run the stop callback if it's being totally cancelled. If it's
        # just WAITING, stick around for the next event
        if self.timelapse.state != State.WAITING:
            _log.info(f"Cancelling executor running timelapse '{self.name}'")
            self.cancelling = True
            asyncio.create_task(self.stop_callback(self))

    def stop(self) -> None:
        super().stop()

        # Only run the stop callback if it's being totally stopped. If it's
        # just WAITING, stick around for the next event
        if self.timelapse.state != State.WAITING:
            _log.info(f"Stopping executor running timelapse '{self.name}'")
            asyncio.create_task(self.stop_callback(self))

    async def run(self):
        self.frame_count += 1
        print(f'{self.name}: '
              f'l={self.current_loop}, f={self.frame_count} | '
              f'{utils.format_time()}')

    async def load_frame_count(self) -> int:
        """
        Get the number of frames that have been captured for this timelapse.

        This is somewhat costly; it counts the files on the disk. Only call this
        when first initializing this executor.

        Returns:
            The number of already captured frames.
        """

        print('Scanning', self.timelapse.directory)
        return NotImplemented

    def equals_db_record(self, tl: Timelapse) -> bool:
        """
        Check whether the given db timelapse record equals the one associated
        with this executor.

        Args:
            tl: The db record to compare with the existing one.

        Returns:
            True if and only if the timelapses are equal for the purposes of
            this executor.
        """

        # Check basic parameters that affect how/when this executor runs, along
        # with the schedules
        if self.timelapse.camera_id != tl.camera_id or \
                self.timelapse.end_time != tl.end_time or \
                self.timelapse.start_time != tl.start_time or \
                self.timelapse.total_frames != tl.total_frames or \
                self.timelapse.schedule_entries != tl.schedule_entries:
            return False

        # Check the state
        if self.timelapse.state != tl.state:
            # Ignore differences in WAITING/RUNNING, which are probably a
            # symptom of a recent event that changed things
            ignore = (State.WAITING, State.RUNNING)
            if self.timelapse.state not in ignore or tl.state not in ignore:
                return False

        return True

    def determine_current_event(self, now: datetime) -> ExecutorEvent:
        """
        Construct an ExecutorEvent based on the timelapse state at the given
        time (i.e. what its state should be at that time).

        Importantly, this method makes few assumptions about the integrity of
        the database record for the timelapse, as this is the first time the
        settings are configured for this executor. More specifically, this
        doesn't assume that the timelapse's State attribute makes any sense:
        it could be READY when the timelapse theoretically started an hour ago,
        and this will correct the state to RUNNING (or whatever is appropriate
        based on the schedule). This makes it resilient to long bot downtimes
        and some live, external modification of the database.

        This event returned by this method is never None, but it might set the
        state to FINISHED or PAUSED, in which case the timelapse executor
        should be stopped.

        Args:
            now: The "current" time used for calculating the correct timelapse
            execution state.

        Returns:
            An executor event that sets the proper state at the given time.
        """

        tl = self.timelapse
        state, start, end = tl.state, tl.start_time, tl.end_time

        #################### FINISHED / PAUSED STATES ####################

        # If the state is currently FINISHED, keep it that way UNLESS the end
        # time is in the future, in which set it to WAITING (temporarily)
        if state == State.FINISHED:
            if end is not None and end > now:
                state = State.READY  # Idk, not sure yet what this should be
            else:
                # It's still finished, ok?
                return ExecutorEvent.with_state(now, tl)

        # If the state is currently PAUSED, keep it that way UNLESS the end
        # time is in the past, in which case set it should have FINISHED
        if state == State.PAUSED:
            return ExecutorEvent.with_state(
                now,
                tl,
                State.FINISHED if end is not None and end <= now else state
            )

        #################### GLOBAL START/END TIMES ####################

        # If the start time is given and in the future, it should be WAITING;
        # If the end time is given and in the past, it should be FINISHED.
        # But both of these rules can be overridden with FORCE_RUNNING.
        if (start is not None and start > now) or \
                (end is not None and end <= now):
            return ExecutorEvent.with_state(
                now,
                tl,
                state if state == State.FORCE_RUNNING
                else State.WAITING if (start is not None and start > now)
                else State.FINISHED
            )

        # If the start time is not set, and the state is READY, then it's just
        # waiting for the user to manually start the timelapse. Stay that way.
        if start is None and state == State.READY:
            return ExecutorEvent.with_state(now, tl)

        #################### NO SCHEDULE ####################

        if not tl.has_schedule:
            if start is None:
                # Without a schedule, if there's no start time, it's just based
                # on when the user starts the timelapse. So it should either be
                # READY or RUNNING. (Remember, end time must be in the future if
                # this line is reached, so it can't be FINISHED). Auto-fix
                # WAITING to READY and FORCE_RUNNING to regular RUNNING here.
                return ExecutorEvent.with_state(
                    now,
                    tl,
                    State.READY if state == State.READY or
                                   state == State.WAITING
                    else State.RUNNING
                )
            else:
                # If this line is reached, it must be RUNNING. We know from
                # earlier that the start time is in the past and that it's not
                # PAUSED or FINISHED.
                return ExecutorEvent.with_state(now, tl, State.RUNNING)

        #################### CURRENTLY RUNNING ####################

        # At this point, we know we're within the global start/end window with
        # a schedule. Either we passed the start time, or the user manually
        # started the timelapse. So now, let's check the schedule to see which
        # entry is active at this time and then activate it.

        entry = self.schedule.active_entry_at(now)

        if entry is None:
            # If there's no active entry, then we're just waiting for some entry
            # to come into effect or for the timelapse to end. Go with WAITING.
            return ExecutorEvent.with_state(now, tl, State.WAITING)
        else:
            # Otherwise, active this entry
            return ExecutorEvent.from_schedule_entry(now, tl, entry)

    async def determine_next_event(self, now: datetime) -> \
            Union[ExecutorEvent, Literal['cancel', 'indefinite']]:
        """
        Determine the next execution event for updating this timelapse executor.
        This is based on the timelapse settings and schedule and is relative
        to the given datetime.

        This method assumes that determine_current_event() has been called and
        used to update the timelapse settings/state.

        Note that this can return literal strings in two different situations,
        indicating that there are no more automated, upcoming events:

        - It returns "cancel" if the timelapse is currently READY, PAUSED,
          or FINISHED. These require user input for anything to happen, so the
          executor should be cancelled for the time being.
        - It returns "indefinite" if there's no schedule (or no more schedule
          entries) and no end_time. It'll just keep RUNNING or FORCE_RUNNING
          until either (a) the user intervenes, or (b) it's RUNNING and reaches
          the total_frames end condition.

        Args:
            now: The "current" time to use while calculating the next event,
            or the literal strings "cancel" or "indefinite".

        Returns:
            The next event, or None if there are no more automated events.
        """

        # It should stop right now
        if self.determine_current_event(now).state in \
                (State.PAUSED, State.FINISHED, State.READY):
            return 'cancel'

        #################### FORCE RUNNING ####################

        # If it's past the end time, but it's set to force run, we don't know
        # when it'll end. Run indefinitely until the user stops it manually
        if self.timelapse.end_time is not None and \
                now >= self.timelapse.end_time and \
                self.timelapse.state == State.FORCE_RUNNING:
            return 'indefinite'

        #################### CHECK SCHEDULE ####################

        # If it has a schedule, get an event for the next schedule entry
        if self.timelapse.has_schedule:
            event = ExecutorEvent.from_schedule_event(
                self.timelapse,
                self.schedule.next_event_after(now)
            )

            # Use the upcoming schedule event
            if event is not None:
                return event

        #################### NO SCHEDULE EVENTS ####################

        # If there's no schedule, or there is a schedule but without any
        # upcoming entries that'll become active, then just wait until the
        # global end time for the timelapse. Switch to the FINISHED state when
        # it ends.
        if self.timelapse.end_time is not None:
            return ExecutorEvent.with_state(
                self.timelapse.end_time,
                self.timelapse,
                State.FINISHED
            )
        else:
            # We don't know when it'll end. Just wait indefinitely
            return 'indefinite'

    async def apply_event(self, event: ExecutorEvent):
        """
        Apply the given event to this timelapse executor.

        Args:
            event: The event to apply.
        """

        # If the state changed, update the SQL db
        if self.timelapse.state != event.state:
            self.timelapse.state = event.state
            _log.info(f'Timelapse {self.id} is now {event.state.name}')
            await self.update_db()

        if event.state in (State.READY, State.PAUSED, State.FINISHED):
            # The timelapse stopped; no need to update any settings. Cancel
            # this executor, which will delete it from the coordinator and
            # prevent any more events from running
            self.cancel()
            return

        # Update the interval, if it was modified
        if self.seconds != event.interval:
            self.change_interval(seconds=event.interval)

        # If it should be (FORCE_)RUNNING, start this task loop. If it
        # shouldn't be running, cancel it
        do_run = event.state in (State.RUNNING, State.FORCE_RUNNING)
        if self.is_running() and not do_run:
            self.cancel()
        elif not self.is_running() and do_run:
            self.start()

    async def update_db(self) -> None:
        """
        Update the timelapse associated with this executor in the database.
        Something about the local timelapse object changed, and its changes must
        be pushed to the db.
        """

        _log.debug(f'Updating {self} timelapse record in db')

        async with (async_session_maker(expire_on_commit=False) as session,
                    session.begin()):  # Read/write session with begin()
            session.add(self.timelapse)
            await session.commit()
