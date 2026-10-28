"""Request-scoped screen authority; reset on errors, cancellation and normal exit."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.domain.aiopen.principal import ScreenPrincipal

_principal: ContextVar[ScreenPrincipal | None] = ContextVar("aiopen_screen_principal", default=None)


def current_screen_principal() -> ScreenPrincipal | None:
    return _principal.get()


@contextmanager
def screen_principal_scope(principal: ScreenPrincipal | None) -> Iterator[None]:
    token = _principal.set(principal)
    try:
        yield
    finally:
        _principal.reset(token)
