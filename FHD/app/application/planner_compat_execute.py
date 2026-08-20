# mypy: disable-error-code=no-any-return
# ruff: noqa: F401
"""JSON and batch execution paths for planner compatibility chat."""

from __future__ import annotations

import importlib
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
_FACADE_GLOBALS: ContextVar[dict[str, Any] | None] = ContextVar(
    "planner_compat_facade_globals", default=None
)


from app.application.planner_compat_execute_part01 import (
    _GlobalsFacade as _GlobalsFacade,
)
from app.application.planner_compat_execute_part01 import (
    reset_facade_globals as reset_facade_globals,
)
from app.application.planner_compat_execute_part01 import (
    set_facade_globals as set_facade_globals,
)


def _facade():
    values = _FACADE_GLOBALS.get()
    if values is not None:
        return _GlobalsFacade(values)
    return importlib.import_module("app.application.planner_compat_service")


from app.application.planner_compat_execute_part02 import (
    execute_compat_chat as execute_compat_chat,
)
from app.application.planner_compat_execute_part03 import (
    execute_compat_chat_batch as execute_compat_chat_batch,
)
