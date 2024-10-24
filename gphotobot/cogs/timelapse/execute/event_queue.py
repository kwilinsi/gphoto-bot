import asyncio
from collections.abc import Awaitable, Callable
import heapq
import logging

from gphotobot import utils
from .executor_event import ExecutorEvent

_log = logging.getLogger(__name__)


class ExecutorEventQueue:
    def __init__(self, callback: Callable[[ExecutorEvent], Awaitable[None]]):
        """
        Initialize an event queue, which keeps tracks of all the events for
        updating active timelapses when their settings change, or they
        start/stop capturing photos.

        Args:
            callback: The function to call whenever the next executor event is
            ready to be processed.
        """

        self._queue: list[ExecutorEvent] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._callback: Callable[[ExecutorEvent], Awaitable[None]] = callback

    def create_task(self) -> None:
        """
        This method is somewhat recursive. It creates the self._task, which is
        the asyncio task that processes the next event in the queue. The task
        calls the _run() method, and when it finishes, it calls this method
        again to recreate itself.
        """

        # Cancel previous task, if there is one
        if self._task is not None and not self._task.done():
            self._task.cancel()

        # Start the new task
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        """
        Run the first event in the queue (the heap invariant). First, wait with
        asyncio.sleep() until it's time to process that event. Then, send it
        to the callback function.

        When actually processing the event, this acquires the lock in order to
        remove the event from the queue.

        This method waits until the task is processed. Start it with
        asyncio.create_task() to prevent blocking. If the heap invariant
        changes, acquire the lock, and cancel the task. Then create a new task
        on the new invariant.

        Note: this method handles popping the first element from the queue:
        hence why this class has no pop() method.
        """

        # Acquire the lock to get the heap invariant
        async with self._lock:
            # If the queue is empty, exit, thereby ending the task; it'll be
            # recreated when a new event is added to the queue
            if len(self._queue) == 0:
                return

            # Get the heap invariant: the first event to process
            event = self._queue[0]

        try:
            # Wait until it's time for this task
            seconds = event.time_until()
            _log.debug(f"Waiting {utils.format_duration(seconds)} to run "
                       f"the event {event}")
            await asyncio.sleep(seconds)

            # Get the lock to avoid processing an event while in the middle of
            # a delete or push operation. Also so we can pop.
            async with self._lock:
                # Make sure the queue isn't empty
                if len(self._queue) == 0:
                    _log.warning('Unexpected: queue empty when about to '
                                 f'process event {event}')
                    return

                # Get and remove (i.e. pop) the first element from the queue
                e = heapq.heappop(self._queue)

                # Make sure this event is still the heap invariant. If not,
                # this probably should have been cancelled
                if e != event:
                    _log.debug(f'While waiting to process {event}, it was '
                               f'displaced by {e}')
                else:
                    # Send the event to the callback function to process it
                    n = len(self._queue)
                    _log.debug(f"Running event {event}: there "
                               f"{'is' if n == 1 else 'are'} now {n} "
                               f"event{'' if n == 1 else 's'} left in the queue")
                    asyncio.create_task(self._callback(event))

        except asyncio.CancelledError:
            _log.debug('Cancelled event queue task')
            raise

        # Restart the task
        self._task = None
        self.create_task()

    async def cancel(self) -> None:
        """
        Cancel the task running the next event. Call this before deleting the
        queue.
        """

        async with self._lock:
            _log.info('Cancelling event queue task and clearing the queue')
            if self._task is not None:
                self._task.cancel()
            self._queue.clear()

    async def push(self, event: ExecutorEvent) -> None:
        """
        Add an executor event to the queue. It's automatically inserted in the
        proper location based on its timestamp. If this becomes the first event
        in the queue (i.e. the heap invariant), the current task awaiting that
        event is replaced with a new task on this event.

        Args:
            event: The event to add.
        """

        async with self._lock:
            heapq.heappush(self._queue, event)

            if self._task is None or event == self._queue[0]:
                # Start a task to run the heap invariant executor event
                self.create_task()

            n = len(self._queue)
            _log.debug(f"Added event {event}: there "
                       f"{'is' if n == 1 else 'are'} now "
                       f"{n} event{'' if n == 1 else 's'} in the queue")

    async def remove_timelapse(self, timelapse_id: int):
        """
        Remove all events for a particular timelapse based on its id.

        Args:
            timelapse_id: The id of the timelapse.
        """

        async with self._lock:
            n1 = len(self._queue)
            self._queue = [event for event in self._queue
                           if event.timelapse_id != timelapse_id]
            heapq.heapify(self._queue)

            # Log a message
            n2 = len(self._queue)
            diff = n1 - n2
            _log.debug(
                f"Removed {diff} event{'' if diff == 1 else 's'} from "
                f"queue for timelapse with id {timelapse_id}: there "
                f"{'is' if n2 == 1 else 'are'} now {n2} "
                f"event{'' if n2 == 1 else 's'} left in the queue"
            )

    async def has_any(self, timelapse_id: int) -> bool:
        """
        Check whether this queue contains any events for a timelapse with
        the given id.

        Args:
            timelapse_id: The id to check.

        Returns:
            True if and only if there is at least one match for the given id.
        """

        async with self._lock:
            return any(e for e in self._queue if e.timelapse_id == timelapse_id)
