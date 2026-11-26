"""Transaction fence supplied by the current worker claim, when one exists."""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from contextvars import ContextVar
from typing import Any

write_transaction_guard: ContextVar[Callable[[Any], AbstractContextManager[Any]]] = ContextVar(
    "worker_write_transaction_guard", default=nullcontext
)
