from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import logging
from typing import Literal, Union, Any

from gphotobot import utils
from gphotobot.sql import async_session_maker, State, Timelapse
from .executor_event import ExecutorEvent
from ..schedule.schedule import Schedule

_log = logging.getLogger(__name__)


class TimelapseExecutor(utils.TaskLoop):
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

        # Tracks whether cancel() was called on this executor
        self.cancelling: bool = False

        self.timelapse: Timelapse = timelapse
        self.schedule: Schedule = Schedule.from_db(timelapse.schedule_entries)

        # These listeners are executed whenever the timelapse state changes
        self._state_listener_lock: asyncio.Lock = asyncio.Lock()
        self.state_listeners: list[Callable[[State], Awaitable[None]]] = []

        _log.info(f"Initialized a new executor instance: {self}")

    @property
    def id(self) -> int:
        return self.timelapse.id

    @property
    def name(self) -> str:
        return self.timelapse.name

    @property
    def frame_count(self) -> int:
        return self.timelapse.frames

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
        _log.info(f"Cancelling executor task loop {self}")

    def stop(self) -> None:
        super().stop()
        _log.info(f"Stopping executor task loop {self}")

    def start(self, *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        _log.debug(f'Starting the task loop for executor {self}')
        self.cancelling = False
        return super().start(*args, **kwargs)

    async def run(self):
        self.timelapse.frames += 1
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
                self.timelapse.capture_interval != tl.capture_interval or \
                self.schedule != Schedule.from_db(tl.schedule_entries):
            return False

        # Check the state
        if self.timelapse.state != tl.state:
            # Ignore differences in WAITING/RUNNING, which are probably a
            # symptom of a recent event that changed things
            ignore = (State.WAITING, State.RUNNING)
            if self.timelapse.state not in ignore or tl.state not in ignore:
                return False

        # No changes found
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

        # If the state is currently PAUSED, keep it that way UNLESS the end
        # time is in the past, in which case set it should have FINISHED
        if state == State.PAUSED:
            return ExecutorEvent.with_state(
                now,
                tl,
                State.FINISHED if end is not None and end <= now else state
            )

        # If the start time is in the future, it should always be WAITING to
        # start soon (unless manually paused, which we already checked, or
        # manually started with FORCE_RUNNING)
        if start is not None and start > now:
            return ExecutorEvent.with_state(
                now,
                tl,
                state if state == State.FORCE_RUNNING else State.WAITING
            )

        # If the state is currently FINISHED, then keep it that way UNLESS the
        # end times is in the future.
        if state == State.FINISHED:
            if end is None or end <= now:
                return ExecutorEvent.with_state(now, tl)  # Yep, still finished

        #################### READY & GLOBAL END TIME ####################

        # If the end time is given and in the past, it should be FINISHED,
        # unless the user overrode that with FORCE_RUNNING.
        if end is not None and end <= now:
            return ExecutorEvent.with_state(
                now,
                tl,
                state if state == State.FORCE_RUNNING else State.FINISHED
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
                    State.READY if state in (State.READY, State.WAITING)
                    else State.RUNNING
                )
            else:
                # If this line is reached, it must be RUNNING. We know from
                # earlier that it already started and that it's not PAUSED or
                # FINISHED.
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

    async def determine_next_event(self,
                                   now: datetime) -> ExecutorEvent | None:
        """
        Determine the next execution event for updating this timelapse executor.
        This is based on the timelapse settings and schedule and is relative
        to the given datetime.

        This method assumes that determine_current_event() has been called and
        used to update the timelapse settings/state.

        This will return None in two different situations:

        - The timelapse is currently READY, PAUSED, or FINISHED. These require
          user input for anything to happen, so the executor is also cancelled
          with self.cancel().

        - There's no schedule (or no more schedule entries) and no end_time.
          The timelapse will just keep RUNNING or FORCE_RUNNING until either
          (a) the user intervenes, or (b) it's reaches the total_frames end
          condition in regular RUNNING mode.

        Args:
            now: The "current" time to use while calculating the next event.

        Returns:
            The next event, or None if there are no more automated events.
        """

        #################### PAUSED, FINISHED, or READY ####################

        cur_state: State = self.determine_current_event(now).state
        tl = self.timelapse
        state, start, end = tl.state, tl.start_time, tl.end_time

        # If paused with an end time in the future, the next event is when it
        # reaches that end time and finishes
        if cur_state == State.PAUSED and end is not None and end >= now:
            # (Used end >= now instead of > just in case there's a bug, and
            # it should be finished right now)
            return ExecutorEvent.with_state(end, tl, State.FINISHED)

        # Next event is unknown; user input needed for anything to happen
        if cur_state in (State.PAUSED, State.FINISHED, State.READY):
            self.cancel()  # Probably already cancelled in apply_event()
            return None

        #################### FORCE RUNNING ####################

        # If it's past the end time, but it's set to force run, we don't know
        # when it'll end. Run indefinitely until the user stops it manually.
        # The other FORCE_RUNNING case (where it hasn't started yet) is covered
        # below under "BEFORE START TIME"
        if cur_state == State.FORCE_RUNNING and end is not None and end <= now:
            return None

        #################### BEFORE START TIME ####################

        # If it hasn't reached the start time yet, then it'll do something at
        # the start time. Either that's when it starts RUNNING, or, if there's
        # a schedule that takes effect later, then it'll start WAITING for the
        # first schedule entry.
        if start is not None and self.timelapse.start_time > now:
            if tl.has_schedule:
                # It has a schedule. Check if there's an active entry at the
                # start time
                entry = self.schedule.active_entry_at(now)
                if entry is None:
                    # No active entry. Wait until the schedule starts running
                    return ExecutorEvent.with_state(start, tl, State.WAITING)
                else:
                    # Activate this entry at the start time
                    return ExecutorEvent.from_schedule_entry(start, tl, entry)

            # There's no schedule. Switch to RUNNING at the start time
            return ExecutorEvent.with_state(start, tl, State.RUNNING)

        #################### CHECK SCHEDULE ####################

        # At this point we know that it started running. If it has a schedule,
        # get an event for the next schedule entry
        if self.timelapse.has_schedule:
            event = ExecutorEvent.from_schedule_event(
                tl,
                self.schedule.next_event_after(now)
            )

            # If this event exists and is before the end time, use it
            if event is not None and \
                    (end is not None and event.timestamp < end):
                return event

        #################### NO SCHEDULE EVENTS ####################

        # Either there's no schedule, or there aren't any upcoming schedule
        # events to wait for before the end time. Just wait until the global
        # end time for the timelapse. Switch to the FINISHED when it ends.
        if self.timelapse.end_time is not None:
            return ExecutorEvent.with_state(
                self.timelapse.end_time,
                self.timelapse,
                State.FINISHED
            )
        else:
            # We don't know when it'll end. Just keep going indefinitely
            return None

    async def apply_event(self, event: ExecutorEvent):
        """
        Apply the given event to this timelapse executor.

        Args:
            event: The event to apply.
        """

        _log.debug(f"Applying executor event {event} to executor {self}")

        if event.state == State.FINISHED:
            # This timelapse finished. Run the callback to cancel it and delete
            # it from the coordinator. Then save any last changes to the db.
            self.timelapse.state = State.FINISHED
            await self.stop_callback(self)
            await self._run_state_listeners(State.FINISHED)
            await self.update_db()
            _log.info(f"Timelapse '{self.name}' (id {self.id}) just finished")
            return

        # If the state changed, update the SQL db
        if self.timelapse.state != event.state:
            self.timelapse.state = event.state
            _log.info(f"Timelapse '{self.name}' (id {self.id}) "
                      f"is now {event.state.name}")
            await self.update_db()
            await self._run_state_listeners(event.state)

        if event.state in (State.READY, State.PAUSED):
            # Cancel to stop taking pictures, but don't delete this executor
            self.cancel()
            return

        # Update the interval, if it was modified
        if self.seconds != event.interval:
            _log.debug(
                f'Changing interval from '
                f'{utils.format_duration(self.seconds, spaces=False)} '
                f'to {utils.format_duration(event.interval, spaces=False)}'
            )
            self.change_interval(seconds=event.interval)

        # Make sure this is running when it should be and not running when it
        # shouldn't be.
        if event.state in (State.RUNNING, State.FORCE_RUNNING):
            # Should be running
            if not self.is_running():
                self.start()
        else:
            # Shouldn't be running
            if self.is_running():
                self.cancel()

    async def update_db(self) -> None:
        """
        Update the timelapse associated with this executor in the database.
        Something about the local timelapse object changed, and its changes must
        be pushed to the db.
        """

        _log.debug(f'Updating {self} timelapse record in db')

        async with (async_session_maker(expire_on_commit=False) as session,
                    session.begin()):  # Read/write session with begin()
            obj = await session.merge(self.timelapse)
            session.add(obj)

    async def register_listener(
            self, listener: Callable[[State], Awaitable[None]]) -> None:
        """
        Register a listener function that will run whenever the executor changes
        the timelapse state.

        Args:
            listener: The async listener function to register.
        """

        async with self._state_listener_lock:
            self.state_listeners.append(listener)
            _log.debug('Registered state change listener '
                       f'#{len(self.state_listeners)} on {self}')

    async def _run_state_listeners(self, state: State) -> None:
        """
        The executor/timelapse state changed. Call this to notify all the
        registered listeners.

        Args:
            state: The new state.
        """

        async with self._state_listener_lock:
            for listener in self.state_listeners:
                await listener(state)

    async def remove_listener(
            self, listener: Callable[[State], Awaitable[None]]) -> None:
        """
        Remove the specified listener function from the list of registered
        listeners that run when the executor state changes.

        Args:
            listener: The async listener to remove.
        """

        async with self._state_listener_lock:
            for i in range(len(self.state_listeners) - 1, -1, -1):
                if self.state_listeners[i] == listener:
                    del self.state_listeners[i]
                    _log.debug(f'Removed state change listener #{i + 1} '
                               f'from {self}')
