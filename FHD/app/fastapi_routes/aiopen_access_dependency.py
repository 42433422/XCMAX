"""Bind screen authority from verified credentials, never headers claiming a user ID."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from app.application.aiopen.service import (
    resolve_api_key_execution_context,
    resolve_api_key_principal,
)
from app.domain.aiopen.principal import ScreenPrincipal
from app.infrastructure.aiopen.principal_context import (
    execution_context_scope,
    screen_principal_scope,
)
from app.infrastructure.auth.dependencies import resolve_session_user
from app.utils.operational_errors import RECOVERABLE_ERRORS


async def bind_aiopen_principal(connection: HTTPConnection) -> AsyncIterator[None]:
    key = connection.headers.get("X-AIOPEN-Key")
    principal = None
    context = None
    if key is not None:
        # Do not let an unrelated browser session upgrade an unbound/invalid key.
        principal = resolve_api_key_principal(key)
        context = resolve_api_key_execution_context(key)
    else:
        try:
            principal = ScreenPrincipal.from_user(resolve_session_user(connection))
            if principal is not None:
                from app.fastapi_routes.domains.agent.route_support import request_runtime_context

                context = request_runtime_context(connection)
        except HTTPException:
            principal = None
        except RECOVERABLE_ERRORS:
            principal = None
    if context is not None:
        request_key = str(connection.headers.get("Idempotency-Key") or "").strip()
        if request_key:
            context["idempotency_key"] = request_key
    with screen_principal_scope(principal), execution_context_scope(context):
        yield
