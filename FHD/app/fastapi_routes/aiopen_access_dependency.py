"""Bind screen authority from verified credentials, never headers claiming a user ID."""

from __future__ import annotations

from collections.abc import AsyncIterator

from starlette.requests import HTTPConnection

from app.application.aiopen.service import resolve_api_key_principal, resolve_dispatch_ticket
from app.domain.aiopen.inprocess import dispatch_ticket_scope
from app.domain.aiopen.principal import ScreenPrincipal
from app.infrastructure.aiopen.principal_context import screen_principal_scope
from app.infrastructure.auth.dependencies import resolve_session_user
from app.utils.operational_errors import RECOVERABLE_ERRORS


async def bind_aiopen_principal(connection: HTTPConnection) -> AsyncIterator[None]:
    key = connection.headers.get("X-AIOPEN-Key")
    principal = None
    ticket = None
    if key is not None:
        # Do not let an unrelated browser session upgrade an unbound/invalid key.
        principal = resolve_api_key_principal(key)
        ticket = resolve_dispatch_ticket(key)
    else:
        try:
            principal = ScreenPrincipal.from_user(resolve_session_user(connection))
        except RECOVERABLE_ERRORS:
            principal = None
    with screen_principal_scope(principal), dispatch_ticket_scope(ticket):
        yield
