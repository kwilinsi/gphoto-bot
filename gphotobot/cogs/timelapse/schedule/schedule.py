from __future__ import annotations

from collections.abc import Collection, Iterator
from datetime import date, datetime
import logging

from gphotobot.utils import const, utils
from gphotobot.utils.validation_error import ValidationError
from .change_tracker import ChangeTracker, TracksChanges
from .dates import Dates
from .schedule_entry import ScheduleEntry

_log = logging.getLogger(__name__)


class Schedule(TracksChanges, Collection):
    def __init__(self):
        """
        Create a new Schedule. This is a collection of ScheduleEntries that
        coordinate a timelapse.
        """

        self._entries: ChangeTracker[list[ScheduleEntry]] = ChangeTracker([])

    @property
    def entries(self) -> list[ScheduleEntry]:
        return self._entries.current

    @entries.setter
    def entries(self, value: list[ScheduleEntry]) -> None:
        self._entries.update(value)

    def __len__(self) -> int:
        """
        Get the length of this schedule (i.e. the number of entries it
        contains).

        Returns:
            The number of entries.
        """

        return len(self.entries)

    def __iter__(self) -> Iterator[ScheduleEntry]:
        """
        Iterate over the entries in this schedule.

        Returns:
            The entries in this schedule.
        """

        return iter(self.entries)

    def __contains__(self, x, /):
        return x in self.entries

    def add_entry(self, entry: ScheduleEntry) -> None:
        """
        Validate a new entry. If it passes validation, add it to the schedule.
        This tests the following rules:

        1. The Days rule actually applies at some point in time.
        2. It doesn't explicitly refer to dates in the past.
        3. If it explicitly refers exclusively to today, the start time must
           be in the future.
        4. If the Days *exactly* match an existing entry, its time range must
           not overlap at all.

        Args:
            entry: The entry to add.

        Raises:
            ValidationError: If the validation fails in any way.
        """

        # ========== Check that it will run at least once ==========

        if not entry.days.does_ever_run():
            raise ValidationError(
                msg="This entry is invalid: it never runs. Make sure you "
                    "specify at least one day that it should run."
            )

        # ========== Check for specific dates/times in the past ==========

        days = entry.days
        if isinstance(days, Dates):
            today = date.today()
            now = datetime.now().time()
            for d in days:
                if d < today:
                    delta = (today - d).days
                    raise ValidationError(
                        msg="Specific dates can't be in the past, but "
                            f"**{d.strftime('%Y-%m-%d')}** was **{delta}** "
                            f"day{'' if delta == 1 else 's'} ago."
                    )
                elif d == today and days.runs_exactly_once() and \
                        entry.start_time <= now:
                    start = datetime.combine(today, entry.start_time)
                    delta = utils.format_duration(datetime.now() - start)
                    raise ValidationError(
                        msg="Schedule entries for just one specific date can't "
                            "start in the past, but the rule on today, "
                            f"**{d.strftime('%Y-%m-%d')}**, starts "
                            f"at **{start.strftime('%I:%M:%S %p')}**. That "
                            f"was **{delta}** ago."
                    )

        # ========== Check for overlapping time on identical Days ==========

        matching_entries = [e for e in self.entries if e.days == entry.days]
        for e in matching_entries:
            if e.end_time > entry.start_time and e.start_time < entry.end_time:
                e_s, e_e = (utils.format_time(e.start_time),
                            utils.format_time(e.end_time))
                en_s, en_e = (utils.format_time(entry.start_time),
                              utils.format_time(entry.end_time))
                if e.start_time < entry.start_time:
                    s1, e1, s2, e2 = e_s, e_e, en_s, en_e
                else:
                    s1, e1, s2, e2 = en_s, en_e, e_s, e_e

                raise ValidationError(
                    msg="Two entries on the same exact day(s) can't have "
                        f"overlapping times. But **'{s1}'** to **'{e1}'** "
                        f"overlaps with **'{s2}'** to **'{e2}'**."
                )

        # ========== Validation passed ==========

        self.entries.append(entry)

    def remove_entry(self, index: int) -> None:
        """
        Remove an entry specified by its index.

        Args:
            index: The index of the schedule entry to remove.
        """

        del self.entries[index]

    def move_entry(self, index: int, move_up: bool) -> None:
        """
        Move an entry specified by its index either up or down.

        This raises an error if the index is invalid or if you try to move
        the first entry up or the last entry down.

        Args:
            index: The index of the entry to move.
            move_up: Whether to move it up in the list (i.e. lower index).

        Raises:
            IndexError: If the index is invalid, or you try to move the first
            entry up or the last entry down.
        """

        # Check for an invalid index
        if index < 0 or index > len(self):
            raise IndexError(f"Attempted to move invalid index {index} "
                             f"for a schedule with {len(self)} "
                             f"entr{'y' if len(self) == 1 else 'ies'}")
        elif index == 0 and move_up:
            raise IndexError("Attempted to move up the entry at index 0")
        elif index == len(self) - 1 and not move_up:
            raise IndexError("Attempted to move down the last entry at "
                             f"index {index}")

        # Move the entry
        destination = index + (-1 if move_up else 1)
        swap = self.entries[destination]
        self.entries[destination] = self.entries[index]
        self.entries[index] = swap

    def get_summary_str(self,
                        max_len: int = const.EMBED_FIELD_VALUE_LENGTH) -> str:
        """
        Get a string that very succinctly summarizes this schedule. It is
        designed to fit in the body of an embed field.

        Args:
            max_len: The maximum length of the returned string, within reason.

        Returns:
            A concise summary string.
        """

        l = len(self)
        if l == 0:
            return '*No entries. Edit the schedule to add some.*'

        if l == 1:
            header, body = self.entries[0].get_embed_field_strings()
            return f"**{header}**\n{body}"

        text = ''
        for i, entry in enumerate(self):
            line, _ = entry.days.str_header()
            if len(text) + len(line) + 2 <= max_len:
                text += '\n- ' + line
            else:
                omitted = len(self) - i - 1
                footer = f"*(plus {omitted} more)*"
                while len(text) + len(footer) > max_len:
                    omitted += 1
                    text = text[:text.rfind('\n')]
                    footer = f"*(plus {omitted} more)*"
                text += '\n' + footer
                break

        return text[1:]

    def has_changed(self) -> bool:
        return self._entries.has_changed() or \
            any(e.has_changed() for e in self.entries)
