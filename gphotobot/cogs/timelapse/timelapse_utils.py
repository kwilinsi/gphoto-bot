from datetime import datetime
from typing import Optional

from discord import utils as discord_utils


def generate_embed_runtime_text(start: Optional[datetime],
                                end: Optional[datetime],
                                frames: Optional[int]) -> str:
    """
    Generate the text that goes in an embed to display the overall runtime
    information (the start time, end time, and/or total frames).

    Args:
        start: The start time.
        end: The end time.
        frames:  The total frames to capture.

    Returns:
        A formatted string for an embed value field.
    """

    start = 'Manual' if start is None else discord_utils.format_dt(start)
    end = None if end is None else discord_utils.format_dt(end)

    if frames is None:
        frames = None
    else:
        frames = (f"After capturing **{frames:,} "
                  f"frame{'' if frames == 1 else 's'}**")

    if end is None and frames is None:
        end_str = 'Manual'
    elif end is None:
        end_str = frames
    elif frames is None:
        end_str = end
    else:
        end_str = f"{end} or {frames.lower()} (whichever comes first)"

    return (f"**Start:** {start}\n"
            f"**End:** {end_str}")
