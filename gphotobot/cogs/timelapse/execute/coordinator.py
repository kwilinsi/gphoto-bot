import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
import logging

from discord.ext import commands

from gphotobot import GphotoBot, settings, utils
from gphotobot.sql import async_session_maker, get_active_timelapses, Timelapse
from .event_queue import ExecutorEventQueue
from .executor import TimelapseExecutor
from .executor_event import ExecutorEvent

_log = logging.getLogger(__name__)


class Coordinator(utils.TaskLoop,
                  commands.Cog,
                  metaclass=utils.CogABCMeta):
    """
    This class coordinates the execution of all the active timelapses. It spawns
    executor task loops for each timelapse.
    """

    def __init__(self, bot: GphotoBot) -> None:
        self.bot: GphotoBot = bot

        # Maps timelapse database ids to executors that handle picture taking
        self.executors: dict[int, TimelapseExecutor] = {}

        # The event queue and a lock to prevent concurrent read/write
        self.queue: ExecutorEventQueue = ExecutorEventQueue(
            self.process_executor_event
        )
        self.queue_lock: asyncio.Lock = asyncio.Lock()

        # Attached listeners for when an executor is created or removed, and
        # a lock to prevent concurrent read/write
        self.listeners: dict[int, list[Callable[[TimelapseExecutor | int],
        Awaitable[None]]]] = defaultdict(list)
        self.listener_lock: asyncio.Lock = asyncio.Lock()

        # Initialize this task using the timelapse interval and name
        super().__init__(
            name='coordinator',
            minutes=settings.TIMELAPSE_COORDINATOR_REFRESH_DELAY
        )

    async def run(self) -> str:
        """
        Reload timelapse data from the database. Add, update, or remove
        timelapse executors as needed.

        Returns:
            A user-friendly string indicating the number of executors that were
            added, updated, and/or removed.
        """

        _log.info('Timelapse coordinator: syncing with database')

        # Load timelapses from database
        async with async_session_maker(expire_on_commit=False) as session:
            timelapses: list[Timelapse] = await get_active_timelapses(session)

        # Sync with the ones we've got
        updated = added = removed = 0
        for db_t in timelapses:
            if db_t.id in self.executors:
                # Found a match: try to apply updates
                updated += await self.update_executor(
                    self.executors[db_t.id],
                    db_t
                )
            else:
                # No matches: add a new executor
                added += (await self.create_executor(db_t))[1]

        # Look for any executors running timelapses that are no longer in the
        # database, and remove them
        db_ids = tuple(t.id for t in timelapses)
        for executor_id in self.executors:
            if executor_id not in db_ids:
                await self.remove_executor(self.executors[executor_id])
                removed += 1

        # Build a message nicely summarizing what happened
        n = added + updated + removed
        changes = utils.list_to_str(
            ((f"added {added}" if added > 0 else None),
             (f"updated {updated}" if updated > 0 else None),
             (f"removed {removed}" if removed > 0 else None)),
            omit_empty=True
        ) + f" timelapse executor{'' if n == 1 else 's'}"
        message = ('Synced timelapse scheduler with database: ' +
                   (changes if n else 'no changes made'))

        # Log and return the message
        _log.info(message)
        return message

    async def update_executor(self,
                              executor: TimelapseExecutor,
                              timelapse: Timelapse) -> bool:
        """
        Update some timelapse executor with a new timelapse record from the
        database. If the executor already matched the db record, nothing
        happens, and this returns False.

        Args:
            executor: The executor to update.
            timelapse: The incoming timelapse record (either from the database
            or a timelapse control panel).

        Returns:
            True if and only if the executor was updated in some way; otherwise
            False, indicating the timelapse record already matched the executor.
        """

        # If there's no change to the timelapse, do nothing
        if executor.equals_db_record(timelapse):
            return False

        # First, remove all upcoming events for this executor
        await self.remove_events_from_queue(executor.id)

        # Next, update the timelapse record for this executor
        executor.timelapse = timelapse

        # Add an event to run right now that'll update the executor settings
        await self.push_initial_event(executor)

        # Successfully updated the executor
        return True

    async def create_executor(
            self,
            timelapse: Timelapse) -> tuple[TimelapseExecutor, bool]:
        """
        Create a timelapse executor for a new timelapse. Send the initial event
        to the event queue.

        If there is already an executor on the same timelapse id, this updates
        that existing executor with the given timelapse before returning it.

        Args:
            timelapse: The timelapse to register with an executor.

        Returns:
            The executor, and a boolean indicating whether it is new (True) or
            an existing one that may have been updated (False).
        """

        # If there's already an executor with the same timelapse id, just use
        # that. Update it in case there are any changes
        if timelapse.id in self.executors:
            executor = self.executors[timelapse.id]
            await self.update_executor(executor, timelapse)
            return executor, False

        # Otherwise, create and add a new executor
        executor = TimelapseExecutor(timelapse, self.remove_executor)
        self.executors[executor.id] = executor

        # Call any listeners waiting for an executor on this id
        async with self.listener_lock:
            for listener in self.listeners[executor.id]:
                await listener(executor)

        # Push the initial event for this executor
        await self.push_initial_event(executor)

        # Return the new executor
        return executor, True

    async def push_initial_event(self, executor: TimelapseExecutor) -> None:
        """
        Given some timelapse executor, construct an ExecutorEvent for the
        CURRENT settings/state it should have, and then add that event to the
        queue.

        Args:
            executor: The executor for which to add an event.

        Raises:
            AssertionError: If for some reason the queue already has one or
            more events for this timelapse.
        """

        # Get an event with the settings it should currently have
        event = executor.determine_current_event(datetime.now())

        # Push the initial event to the queue
        async with self.queue_lock:
            assert not await self.queue.has_any(executor.id)  # Double-check
            await self.queue.push(event)

    def get_executor(self, timelapse_id: int) -> TimelapseExecutor | None:
        """
        Get the timelapse executor for the timelapse with the specified id.

        Args:
            timelapse_id: The id of the desired timelapse.

        Returns:
            The associated timelapse executor, or None if no executor matches
            that id.
        """

        return self.executors.get(timelapse_id, None)

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
                f"Tried to process event {event} on the executor for timelapse "
                f"{event.timelapse_id}, but the executor couldn't be found."
            )
            return

        # Apply the event
        await executor.apply_event(event)

        # Get the next event to apply
        next_event = await executor.determine_next_event(event.timestamp)

        # Process the event
        if next_event is None:
            # No event to add. It'll just stay cancelled or running until the
            # user intervenes
            _log.debug(f'No more events to process for executor {executor}')
        else:
            # Add this event to the queue
            async with self.queue_lock:
                await self.queue.push(next_event)

    async def remove_events_from_queue(self, timelapse_id: int) -> None:
        """
        Remove all events from the queue for a particular timelapse.

        Args:
            timelapse_id: The id of the timelapse whose events should be
            removed.
        """

        async with self.queue_lock:
            await self.queue.remove_timelapse(timelapse_id)

    async def remove_executor(self, executor: TimelapseExecutor) -> None:
        """
        First, cancel the executor. Then, remove all events pertaining to it
        from the event queue. Finally, remove the reference to the executor
        object from the `self.executors` dict.

        Args:
            executor: The executor to remove.
        """

        _log.info(f'Removing executor {executor} from coordinator')

        async with self.queue_lock:
            executor.cancel()
            await self.queue.remove_timelapse(executor.id)

            # Silently remove the executor
            self.executors.pop(executor.id, None)

            # Call any listeners that want to know if this is removed
            async with self.listener_lock:
                for listener in self.listeners[executor.id]:
                    await listener(executor.id)

    async def register_listener(
            self,
            listener: Callable[[TimelapseExecutor | int], Awaitable[None]],
            timelapse_id: int) -> None:
        """
        Add a listener that's called whenever an executor is added or removed
        for the timelapse with the specified id.

        Args:
            listener: The async listener to call. This receives a
            TimelapseExecutor when a new executor is added, and it receives
            an int (a timelapse id) when an executor is removed.
            timelapse_id: Only call the listener for creating/removing executors
            with this timelapse id.
        """

        async with self.listener_lock:
            self.listeners[timelapse_id].append(listener)

    async def remove_listener(
            self,
            listener: Callable[[TimelapseExecutor | int], Awaitable[None]],
            timelapse_id: int) -> bool:
        """
        Remove a listener that was added to listen for creating/removing an
        executor on a particular timelapse id. If there are multiple matches
        for this listener on the given timelapse id, they are all removed.

        Args:
            listener: The listener to remove.
            timelapse_id: Only remove the matching listeners associated with
            this timelapse id.

        Returns:
            True if and only if at least one listener was removed.
        """

        async with self.listener_lock:
            listeners = self.listeners[timelapse_id]
            removed = False

            # Check each listener on this timelapse id
            for i in range(len(listeners) - 1, -1, -1):
                if listeners[i] == listener:
                    # Delete any matches
                    del listeners[i]
                    removed = True

            # Failed to find a matching listener
            return removed

    def cancel(self) -> None:
        _log.info('Cancelling schedule event coordinator task loop')
        super().cancel()

    def stop(self) -> None:
        _log.info('Stopping schedule event coordinator task loop')
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
