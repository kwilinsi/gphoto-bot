from abc import ABC, abstractmethod


class TracksChanges(ABC):
    @abstractmethod
    def has_changed(self) -> bool:
        """
        Determine whether any of this object's values have changed.

        Returns:
            True if and only if something has changed.
        """


class ChangeTracker[T](TracksChanges):
    def __init__(self, value: T) -> None:
        self._original_value = value
        self._current_value = value

    @property
    def current(self) -> T:
        """
        Get the current value with possible changes.

        Returns:
            The current value.
        """

        return self._current_value

    def update(self, value: T) -> bool:
        """
        Replace the current value with a new one, and return whether it changed.

        Args:
            value: The new value.

        Returns:
            Whether the new value is different from the previous one (NOT
            whether it's different from the original).
        """

        if self._current_value == value:
            return False
        else:
            self._current_value = value
            return True

    @property
    def original(self) -> T:
        """
        Get the original value before any changes.

        Returns:
            The original value.
        """

        return self._original_value

    def has_changed(self) -> bool:
        """
        Determine whether the value has changed by comparing the current and
        original values.

        If the given object implements TracksChanges (as this does), it also
        calls has_changed() on that object.

        This also recognizes built-in iterable types, checking whether any
        contained elements implement ChangeTracker and have changed.

        Returns:
            True if and only if the value has changed.
        """

        current = self._current_value
        if current != self.original:
            return True

        if isinstance(current, TracksChanges):
            return self._current_value.has_changed()

        # Check dictionaries separately to check both keys and values
        if isinstance(current, dict):
            for k, v in current.items():
                if (isinstance(k, TracksChanges) and k.has_changed()) or \
                        (isinstance(v, TracksChanges) and v.has_changed()):
                    return True
            return False

        # Check other iterable types. This is done with iter() and not
        # isinstance(current, collections.abc.Iterable) due to this:
        # https://docs.python.org/3.12/library/collections.abc.html#collections.abc.Iterable
        try:
            for item in iter(current):
                if isinstance(item, TracksChanges) and item.has_changed():
                    return True
        except TypeError:
            # It's not iterable
            pass

        return False
