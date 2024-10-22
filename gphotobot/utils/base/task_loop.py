from abc import ABC, abstractmethod
from collections.abc import Sequence
import datetime
from typing import Optional, Union

from discord.ext import tasks
from discord.utils import MISSING


class TaskLoop(tasks.Loop, ABC):
    def __init__(self,
                 name: Optional[str],
                 seconds: float = MISSING,
                 minutes: float = MISSING,
                 hours: float = MISSING,
                 time: Union[datetime.time, Sequence[datetime.time]] = MISSING,
                 count: Optional[int] = None,
                 reconnect: bool = True,
                 start: bool = True):
        """
        Initialize a TaskLoop, an extension of the base discord.py Loop. This
        autofill the keyword args with the default values used in the
        tasks.loop() decorator.

        Args:
            name: The internal task name.
            seconds: The seconds between iterations. Defaults to MISSING.
            minutes: The minutes between iterations. Defaults to MISSING.
            hours: The hours between iterations. Defaults to MISSING.
            time: The seconds between iterations. Defaults to MISSING.
            count: The number of loops to run. Defaults to None.
            reconnect: Whether to auto handle errors. Defaults to True.
            start: Whether to immediately start this loop. Defaults to True.
        """

        super().__init__(
            coro=self.run,
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            time=time,
            count=count,
            reconnect=reconnect,
            name=name
        )

        # Auto-start, if enabled
        if start:
            self.start()

    @abstractmethod
    async def run(self) -> None:
        """
        Run the task associated with this task loop.
        """

        pass
