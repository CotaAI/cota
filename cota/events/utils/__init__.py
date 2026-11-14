"""Pure utility functions shared across the events module."""
import json
import math


def _json_native(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_native(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_native(item) for key, item in value.items())
    return False


def canonical_json(value):
    """JSON numbers survive JS roundtrips; booleans remain a distinct type."""
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item
    return json.dumps(normalize(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def _same(a, b):
    return canonical_json(a) == canonical_json(b)
