"""Serialize workbook operations that capture process-global Python warnings."""

from collections.abc import Callable
from functools import wraps
from threading import RLock
from typing import ParamSpec, TypeVar

_LOCK = RLock()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def serialize_workbook_io(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def locked(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _LOCK:
            return function(*args, **kwargs)

    return locked
