from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
import logging
from typing import Optional

from gphotobot import const, utils
from gphotobot.sql import ScheduleEntry as SQLScheduleEntry
from .change_tracker import TracksChanges
from .dates import Dates
from .schedule_entry import ScheduleEntry

_log = logging.getLogger(__name__)


class Schedule(list[ScheduleEntry], TracksChanges):
    def __init__(self, entries: Optional[Iterable[ScheduleEntry]] = None):
        """
        Create a new Schedule. This is a list of ScheduleEntries that coordinate
        a timelapse.

        Args:
            entries: A set of existing entries to add to this schedule, or None
            to start with an empty schedule. Defaults to None.

        Raises:
            ValidationError: If any of the entries fail validation checks while
            adding them with append().
        """

        super().__init__()
        if entries is not None:
            for entry in entries:
                self.append(entry)

    @classmethod
    def from_db(cls, records: list[SQLScheduleEntry]) -> Schedule:
        """
        Construct a Schedule from a list of schedule entry records.

        Returns:
            A new schedule.
        """

        return cls(ScheduleEntry.from_db(r) for r in records)

    def __str__(self) -> str:
        """
        Get a string with basic info about each entry in this schedule.

        Returns:
            A string with basic schedule info.
        """

        if len(self) == 0:
            return 'Schedule(0 entries)'
        else:
            return f"Schedule[{', '.join(str(e) for e in self)}]"

    def append(self, entry: ScheduleEntry) -> None:
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
            raise utils.ValidationError(
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
                    raise utils.ValidationError(
                        msg="Specific dates can't be in the past, but "
                            f"**{d.strftime('%Y-%m-%d')}** was **{delta}** "
                            f"day{'' if delta == 1 else 's'} ago."
                    )
                elif d == today and days.runs_exactly_once() and \
                        entry.start_time <= now:
                    start = datetime.combine(today, entry.start_time)
                    delta = utils.format_duration(datetime.now() - start)
                    raise utils.ValidationError(
                        msg="Schedule entries for just one specific date can't "
                            "start in the past, but the rule on today, "
                            f"**{d.strftime('%Y-%m-%d')}**, starts "
                            f"at **{start.strftime('%I:%M:%S %p')}**. That "
                            f"was **{delta}** ago."
                    )

        # ========== Check for overlapping time on identical Days ==========

        matching_entries = [e for e in self if e.days == entry.days]
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

                raise utils.ValidationError(
                    msg="Two entries on the same exact day(s) can't have "
                        f"overlapping times. But **'{s1}'** to **'{e1}'** "
                        f"overlaps with **'{s2}'** to **'{e2}'**."
                )

        # ========== Validation passed ==========

        super().append(entry)

    def __delitem__(self, index):
        super().__delitem__(index)

        # Adjust the index of all items after the one that was deleted
        for i in range(index, len(self)):
            self[i].index = i

    def remove(self, __value):
        super().remove(__value)

        # Make sure indices are consecutive
        for i in range(len(self)):
            self[i].index = i

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
        swap = self[destination]
        self[destination] = self[index]
        self[index] = swap

        # Update indices of the entries themselves
        self[destination].index = destination
        self[index].index = index

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

        n = len(self)
        if n == 0:
            return '*No entries. Edit the schedule to add some.*'

        if n == 1:
            header, body = self[0].get_embed_field_strings()
            return f"**{header}**\n{body}"

        text = ''
        for entry in self:
            # Get the short summary text for the next entry
            line = entry.short_summary()

            # Keep adding entries until reaching the max length
            if len(text) + len(line) + 2 <= max_len:
                text += '\n- ' + line
            else:
                omitted = len(self) - entry.index - 1
                footer = f"*(plus {omitted} more)*"
                while len(text) + len(footer) > max_len:
                    omitted += 1
                    text = text[:text.rfind('\n')]
                    footer = f"*(plus {omitted} more)*"
                text += '\n' + footer
                break

        return text[1:]

    def has_changed(self) -> bool:
        return any(e.has_changed() for e in self)

    def to_db(self,
              timelapse_id: int | None = None,
              force_copy: bool = False) -> list[SQLScheduleEntry]:
        """
        Convert all the schedule entries into database records.

        Args:
            timelapse_id: The id of the timelapse to which this schedule is
            attached. This is optional. Defaults to None.
            force_copy: Whether to create a new database record even if there's
            an existing one. Defaults to False.

        Returns:
            A list of SQL schedule entry records.
        """

        return [e.to_db(timelapse_id=timelapse_id, force_copy=force_copy)
                for e in self]

    def active_entry_at(self, dt: datetime) -> Optional[ScheduleEntry]:
        """
        Determine which schedule entry is active a particular time. If no entry
        is active at that time, this returns None.

        This is checked in the natural order of the entries. The first entry
        receives precedence, and the second entry is checked only if the first
        one doesn't match, etc.

        Args:
            dt: The timestamp to check.

        Returns:
            The active entry, or None if there is no active entry.
        """

        for entry in self:
            if entry.is_active_at(dt):
                return entry

        return None

    def next_event_after(self, dt: datetime) -> \
            tuple[Optional[datetime], Optional[ScheduleEntry], bool]:
        """
        Determine the next time that the active schedule entry will change for
        this timelapse.

        This returns a tuple with three elements:
        - A datetime: this is the time that the next event occurs that will
          change the timelapse in some way. It will always be AFTER the given
          datetime, never equal to or before it.
        - A ScheduleEntry: this is the schedule entry that will change its state
          at the returned time.
        - A boolean: this indicates whether the schedule entry will become
          active or inactive at the given time. Usually, this is True,
          indicating that the entry becomes active. If False, it means that the
          timelapse will turn off until the next schedule entry becomes active.

        If no entries are currently active or none of them will ever become
        active, this returns (None, None, True).

        If one entry becomes inactive at the same time another becomes active
        (either because their start/end times or day rules touch, or they
        overlap), then this event refers to the latter one becoming active.
        Remember that only one schedule entry can be active at a given time.

        Args:
            dt: The timestamp to start checking from. The returned event will
            always be AFTER this time, not equal to or before it.

        Returns:
            The next event, composed of the time it occurs, the effected entry,
            and whether the entry becomes active or inactive.
        """

        if len(self) == 0:
            return None, None, True

            # (Note: in these comments, by "now"/"today" I mean the value of `dt`).

        # Check whether there's currently an active schedule entry
        active: Optional[ScheduleEntry] = self.active_entry_at(dt)

        # If it is active, start from the time it deactivates
        if active is not None:
            deactivate_time, state = active.next_event_after(dt)
            assert state == False

            # Check if any other entries are active at this time
            new_active = self.active_entry_at(deactivate_time)
            if new_active is not None:
                return deactivate_time, new_active, True

            # No other entries will start immediately when this one stops
            return deactivate_time, active, False

        # Find the earliest time that each entry becomes active
        # (associated with that entry's index)
        next_events = [entry.next_event_after(dt) for entry in self]

        # Making sure that all these events are for entries *starting*, because
        # none are active right now, and thus none of them should be stopping
        assert all(state == True for _, state in next_events)

        # Find the earliest event time (note that there could easily be more
        # than one schedule entry starting at this time)
        first_time = None
        for event_time, _ in next_events:
            if event_time is not None and \
                    (first_time is None or event_time < first_time):
                first_time = event_time

        # No entries have any upcoming events
        if first_time is None:
            return None, None, True

        # Return the first schedule entry starting at that time
        for (event_time, _), entry in zip(next_events, self):
            if event_time == first_time:
                return event_time, entry, True
