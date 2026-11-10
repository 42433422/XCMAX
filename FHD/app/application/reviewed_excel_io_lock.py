"""Serialize workbook operations that capture process-global Python warnings."""

from functools import wraps
from threading import RLock

_LOCK = RLock()


def serialize_workbook_io(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with _LOCK:
            return function(*args, **kwargs)

    return locked
