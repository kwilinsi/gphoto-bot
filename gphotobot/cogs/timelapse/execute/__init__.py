from .coordinator import Coordinator
from .executor import TimelapseExecutor

# This is the single, global coordinator that schedules all timelapses
TIMELAPSE_COORDINATOR: Coordinator = None  # noqa
