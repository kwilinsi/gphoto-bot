from __future__ import annotations

from datetime import datetime
from typing import Optional

from gphotobot.sql import State, Timelapse
from ..schedule.schedule_entry import ScheduleEntry


class ExecutorEvent:
    def __init__(self,
                 dt: datetime,
                 timelapse_id: int,
                 name: str,
                 state: State,
                 interval: float):
        """
        Create a new executor event, which contains information on a change to
        make to a TimelapseExecutor at a particular time.

        The tuple (datetime, timelapse_id) should form a primary key that is
        unique among all executor events, in order to make it function properly
        within an executor event queue.

        Args:
            dt: The datetime that this event comes into effect.
            timelapse_id: The database id of the affected timelapse.
            name: The timelapse name (for debugging purposes).
            state: The new timelapse state.
            interval: The new capture interval.
        """

        self.timestamp: datetime = dt
        self.timelapse_id: int = timelapse_id
        self.name: str = name
        self.state: State = state
        self.interval: float = interval

    @classmethod
    def from_schedule_event(
            cls,
            tl: Timelapse,
            event: tuple[Optional[datetime], Optional[ScheduleEntry], bool]) \
            -> Optional[ExecutorEvent]:
        """
        Construct an executor event from a timelapse and some upcoming event
        from its schedule.

        Args:
            tl: The timelapse.
            event: The event: the time it occurs, the affected schedule entry,
            and whether said entry is starting or stopping. If the datetime part
            of this tuple is None, then this will return None.

        Returns:
            A new executor event allowing a TimelapseExecutor to update its
            settings accordingly. Or, if the event time is None, then the
            returned event is also None.
        """

        event_time, entry, state = event

        if event_time is None:
            return None

        if not state:
            # Turn off the timelapse, and wait for next schedule event or for
            # it to end
            return cls(
                event_time,
                tl.id,
                name=tl.name,
                state=State.WAITING,
                interval=tl.capture_interval
            )
        else:
            # Apply the given schedule entry
            return cls.from_schedule_entry(event_time, tl, entry)

    @classmethod
    def from_schedule_entry(cls,
                            dt: datetime,
                            tl: Timelapse,
                            entry: ScheduleEntry) -> ExecutorEvent:
        """
        Generate an executor event that applies a particular schedule entry at
        a particular time. This does not perform any validation. In particular,
        the entry is not validated to confirm that it applies at the given time.

        Args:
            dt: The time the event applies.
            tl: The affected timelapse.
            entry: An entry from the timelapse schedule to apply.

        Returns:
            An event that will apply the given entry to a timelapse executor.
        """

        # Use the schedule entry's capture interval override, if given
        inter = entry.get_config_interval()
        return cls(
            dt=dt,
            timelapse_id=tl.id,
            name=tl.name,
            state=State.RUNNING,
            interval=tl.capture_interval if inter is None else inter.total_seconds()
        )

    @classmethod
    def with_state(cls,
                   dt: datetime,
                   tl: Timelapse,
                   state: State = None) -> ExecutorEvent:
        """
        Return an executor event that updates the given timelapse to the given
        state, with all the other settings determined by the default timelapse
        config.

        Args:
            dt: The datetime that this event comes into effect.
            tl: The timelapse DB record.
            state: The new timelapse state. If None, the state is unchanged from
            its current value. Defaults to None.

        Returns:
            A new ExecutorEvent that set the timelapse to the given state.
        """

        return cls(
            dt=dt,
            timelapse_id=tl.id,
            name=tl.name,
            state=tl.state if state is None else state,
            interval=tl.capture_interval
        )

    def time_until(self) -> float:
        """
        Calculate the time (in seconds) until this event should be processed.

        Note that if the event should have already started, this will be
        negative.

        Returns:
            The time in seconds.
        """

        return (self.timestamp - datetime.now()).total_seconds()

    def __str__(self) -> str:
        """
        Return a string form of this event with some helpful information. This
        is intended for debugging purposes. It includes:
        - The timelapse name and id
        - The timestamp this event takes effect
        - The new timelapse state

        Returns:
            A formatted string with basic info.
        """

        return (f'{self.name}({self.timelapse_id})_' +
                self.timestamp.strftime('%Y-%m-%d@%H:%M:%S') +
                f'_{self.state.name}')

    def __lt__(self, other):
        if type(self) == type(other):
            return self.timestamp < other.timestamp
        else:
            return NotImplemented

    def __le__(self, other):
        if type(self) == type(other):
            return self.timestamp <= other.timestamp
        else:
            return NotImplemented

    def __gt__(self, other):
        if type(self) == type(other):
            return self.timestamp > other.timestamp
        else:
            return NotImplemented

    def __ge__(self, other):
        if type(self) == type(other):
            return self.timestamp >= other.timestamp
        else:
            return NotImplemented

    def __eq__(self, other):
        if type(self) == type(other):
            return self.timelapse_id == other.timelapse_id and \
                self.timestamp == other.timestamp
        else:
            return NotImplemented
