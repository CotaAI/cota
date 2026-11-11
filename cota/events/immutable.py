"""Reducer-owned JSON values. Copies exposed to callers remain ordinary JSON."""
from copy import deepcopy


def _immutable(*args, **kwargs):
    raise TypeError('Reducer-owned facts and context are immutable; apply a new event')


class _Object(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        result = {}
        memo[id(self)] = result
        result.update((key, deepcopy(value, memo)) for key, value in self.items())
        return result


class _Array(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        result = []
        memo[id(self)] = result
        result.extend(deepcopy(value, memo) for value in self)
        return result


def freeze_json(value):
    """Share already immutable history; traverse only newly projected values."""
    if isinstance(value, (_Object, _Array)):
        return value
    if isinstance(value, dict):
        return _Object((key, freeze_json(item)) for key, item in value.items())
    if isinstance(value, list):
        return _Array(freeze_json(item) for item in value)
    return value
