import asyncio
from datetime import datetime
from functools import partial
import logging

from discord.ext import commands

from gphotobot.bot import GphotoBot
from gphotobot.conf import settings
from gphotobot.sql import (async_session_maker, get_active_timelapses,
                           State, Timelapse)
from gphotobot.utils import utils
from gphotobot.utils.base.task_loop import TaskLoop
from gphotobot.utils.base.cog_metaclass import CogABCMeta
from .event_queue import ExecutorEventQueue
from .executor import TimelapseExecutor
from .executor_event import ExecutorEvent

_log = logging.getLogger(__name__)


class Coordinator(TaskLoop, commands.Cog, metaclass=CogABCMeta):
    """
    This class coordinates the execution of all the active timelapses. It spawns
    executor task loops for each timelapse.
    """

    def __init__(self, bot: GphotoBot) -> None:
        self.bot: GphotoBot = bot

        # Maps timelapse database ids to executors that handle picture taking
        self.executors: dict[int, TimelapseExecutor] = {}

        self.queue: ExecutorEventQueue = ExecutorEventQueue(
            self.process_executor_event
        )
        self.queue_lock: asyncio.Lock = asyncio.Lock()

        # Initialize this task using the timelapse interval and name
        super().__init__(
            name='coordinator',
            minutes=settings.TIMELAPSE_COORDINATOR_REFRESH_DELAY
        )

    async def run(self) -> None:
        _log.info('Timelapse coordinator: syncing with database')

        # Load timelapses from database
        async with async_session_maker(expire_on_commit=False) as session:
            timelapses: list[Timelapse] = await get_active_timelapses(session)

        # Sync with the ones we've got
        updated = added = removed = 0
        for db_t in timelapses:
            if db_t.id in self.executors:
                # Found a match: check for updates
                if not self.executors[db_t.id].equals_db_record(db_t):
                    # Update by deleting the executor and recreating it
                    await self.remove_executor(self.executors[db_t.id])
                    did_add = await self.add_timelapse(db_t)
                    removed += not did_add
                    updated += did_add
            else:
                # No matches: add a new executor
                added += await self.add_timelapse(db_t)

        # Look for any executors running timelapses that are no longer in the
        # database, and remove them
        db_ids = tuple(t.id for t in timelapses)
        for executor_id in self.executors:
            if executor_id not in db_ids:
                await self.remove_executor(self.executors[executor_id])
                removed += 1

        # Print a log message nicely summarizing what happened
        n = added + updated + removed
        changes = utils.list_to_str(
            ((f"added {added}" if added > 0 else None),
             (f"updated {updated}" if updated > 0 else None),
             (f"removed {removed}" if removed > 0 else None)),
            omit_empty=True
        ) + f" timelapse executor{'' if n == 1 else 's'}"
        _log.info('Synced timelapse executors with db: ' +
                  (changes if n else 'no changes made'))

    async def add_timelapse(self, tl: Timelapse) -> bool:
        """
        Create a timelapse executor for a new timelapse. Send the initial event
        to the event queue.

        Args:
            tl: The timelapse to register with an executor.

        Returns:
            A boolean indicating whether the timelapse was actually added.
        """

        # Create an executor, and get an event to set its current state
        executor = TimelapseExecutor(
            tl,
            partial(self.remove_executor, cancel=False)
        )
        event = executor.determine_current_event(datetime.now())

        # If the event state is PAUSED, READY, or FINISHED, don't even bother
        # adding this executor. It needs user input to do anything, and it'll
        # just be removed again as soon as the event is processed
        if event.state in (State.READY, State.PAUSED, State.FINISHED):
            # But if the state is currently something else, fix it in the db
            if executor.timelapse.state != event.state:
                _log.info('Correcting malformed db entry state from '
                          f'{executor.timelapse.state.name} to '
                          f'{event.state.name} for executor {executor}')
                executor.timelapse.state = event.state
                await executor.update_db()

            return False

        # Add this executor, and push its initial event to the queue
        self.executors[executor.id] = executor
        async with self.queue_lock:
            assert not await self.queue.has_any(tl.id)  # Just double-checking
            await self.queue.push(event)

        return True

    async def process_executor_event(self, event: ExecutorEvent) -> None:
        """
        Process some executor event, applying its affect to the relevant
        timelapse.

        Args:
            event: The event to process.
        """

        try:
            # Get the executor associated with this event
            executor: TimelapseExecutor = self.executors[event.timelapse_id]
        except KeyError:
            _log.error(
                f"Tried to process an event on timelapse {event.timelapse_id}, "
                "but the associated executor couldn't be found."
            )
            return

        # Apply the event
        await executor.apply_event(event)

        # Get the next event to apply
        next_event = await executor.determine_next_event(event.timestamp)
        if next_event == 'cancel':
            # Cancel again in case it was somehow missed by apply_event()
            if not executor.cancelling:
                _log.info(f"Executor {executor} wasn't being cancelled despite "
                          f"returned 'cancel' from determine_next_event()")
                executor.cancel()
        elif next_event == 'indefinite':
            # Nothing to do here. The executor keeps running, but no more
            # events to apply
            _log.debug(
                f'No more executor events for timelapse {event.timelapse_id}; '
                f'running until end condition met or user stops it'
            )
        else:
            # Already handled the literal cases. This prevents a type warning
            assert isinstance(next_event, ExecutorEvent)

            # Add this event to the queue
            async with self.queue_lock:
                await self.queue.push(next_event)

    async def remove_executor(self,
                              executor: TimelapseExecutor,
                              cancel: bool = True) -> None:
        """
        Remove a timelapse executor and all upcoming events associated with that
        timelapse.

        This first removes the events and then the executor, in that order.

        Args:
            executor: The executor to remove.
            cancel: Whether to cancel the executor. (Only set this to False when
            the executor is in the process of stopping). Defaults to True.
        """

        async with self.queue_lock:
            await self.queue.remove_timelapse(executor.id)
            if cancel:
                _log.info('Calling cancel in remove_executor()')
                executor.cancel()
            self.executors.pop(executor.id, None)  # Silently remove

    def cancel(self) -> None:
        super().cancel()

    def stop(self) -> None:
        super().stop()

    async def clean_up(self) -> None:
        """
        Cancel all active executors and the event queue. Call this before
        deleting/cancelling this coordinator.
        """

        _log.info('Cleaning up timelapse coordinator: cancelling executors '
                  'and event queue')

        for executor in self.executors.values():
            executor.cancel()

        async with self.queue_lock:
            await self.queue.cancel()
