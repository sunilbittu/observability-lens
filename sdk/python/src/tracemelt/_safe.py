"""Input cleaning shared by every public call. Nothing here raises."""

from __future__ import annotations

import math
import re

MAX_ATTRIBUTES = 32
MAX_STRING = 1024
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-/]{0,199}$")

# Attribute keys that hold identifiers or codes even when the value is a number.
# A numeric attribute whose key matches is recorded on the event but never summed.
ID_LIKE = re.compile(
    r"(^|[._-])(id|ids|uuid|guid|key|code|number|num|no|zip|postcode|phone|port|pid|version|year|status|index|seq|timestamp|time|ts)$",
    re.IGNORECASE)


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(_NAME.match(name))


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def attributes(data) -> dict:
    out: dict = {}
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        if len(out) >= MAX_ATTRIBUTES:
            break
        if not isinstance(key, str):
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, str):
            out[key] = value[:MAX_STRING]
        elif is_number(value):
            out[key] = value
        # everything else (objects, lists, None, NaN) is dropped
    return out


def summable(attrs: dict) -> list[tuple[str, float]]:
    """Which attributes of an event are measurements that can be added up."""
    return [(key, value) for key, value in attrs.items()
            if is_number(value) and value >= 0 and not ID_LIKE.search(key)]
