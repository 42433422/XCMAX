"""Request-scoped screen authority; reset on errors, cancellation and normal exit."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from app.domain.aiopen.principal import ScreenPrincipal

_principal: ContextVar[ScreenPrincipal | None] = ContextVar("aiopen_screen_principal", default=None)
_execution: ContextVar[dict[str, Any] | None] = ContextVar("aiopen_execution_context", default=None)


def current_execution_context() -> dict[str, Any]:
    """Return only the host-bound execution identity for this transport request."""
    return deepcopy(_execution.get() or {})


@contextmanager
def execution_context_scope(context: dict[str, Any] | None) -> Iterator[None]:
    token = _execution.set(deepcopy(context) if context else None)
    try:
        yield
    finally:
        _execution.reset(token)


def current_screen_principal() -> ScreenPrincipal | None:
    return _principal.get()


@contextmanager
def screen_principal_scope(principal: ScreenPrincipal | None) -> Iterator[None]:
    token = _principal.set(principal)
    try:
        yield
    finally:
        _principal.reset(token)
