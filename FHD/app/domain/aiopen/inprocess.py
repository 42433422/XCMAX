"""In-process AIOPEN follow-up calls.

The marker lives on the ASGI scope. External clients cannot set it with
headers, and the LAN guards must not treat ``X-Forwarded-For`` or
``X-AIOPEN-Internal`` as this marker.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

MARKER = "aiopen_inprocess_dispatch"

_ticket: ContextVar[dict[str, Any] | None] = ContextVar("aiopen_dispatch_ticket", default=None)


def current_dispatch_ticket() -> dict[str, Any] | None:
    ticket = _ticket.get()
    return dict(ticket) if isinstance(ticket, dict) else None


@contextmanager
def dispatch_ticket_scope(ticket: dict[str, Any] | None) -> Iterator[None]:
    token = _ticket.set(dict(ticket) if isinstance(ticket, dict) else None)
    try:
        yield
    finally:
        _ticket.reset(token)


def read_inprocess_ticket(scope: Scope) -> dict[str, Any] | None:
    state = scope.get("state") if isinstance(scope, dict) else None
    ticket = state.get(MARKER) if isinstance(state, dict) else None
    if (
        not isinstance(ticket, dict)
        or ticket.get("v") != 1
        or ticket.get("authenticated") is not True
    ):
        return None
    return ticket


def inprocess_admitted(scope: Scope) -> bool:
    return read_inprocess_ticket(scope) is not None


class InProcessDispatch:
    """Stamp a verified ticket onto HTTP scopes before the edge guards run."""

    def __init__(self, app: ASGIApp, ticket: dict[str, Any] | None) -> None:
        self.app = app
        self.ticket = dict(ticket) if isinstance(ticket, dict) else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http" and self.ticket is not None:
            scope = dict(scope)
            state = dict(scope.get("state") or {})
            state[MARKER] = dict(self.ticket)
            scope["state"] = state
        await self.app(scope, receive, send)
