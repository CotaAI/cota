"""Read-only history access without copying the entire stream for each lookup."""
from collections.abc import Sequence
from copy import deepcopy


class EventHistory(Sequence):
    """A live collection view; each returned event is detached from DST facts."""

    def __init__(self, events):
        self.__events = events

    def __len__(self):
        return len(self.__events)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(deepcopy(event) for event in self.__events[index])
        return deepcopy(self.__events[index])

    def __iter__(self):
        # Appends during iteration cannot change which facts this iteration sees.
        return (deepcopy(event) for event in tuple(self.__events))
