"""Revalidate long-lived Agent streams against the original authenticated scope."""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.utils.operational_errors import RECOVERABLE_ERRORS

StreamAuthorizer = Callable[[], Awaitable[bool]]

STREAM_AUTH_ERRORS: tuple[type[Exception], ...] = (HTTPException, *RECOVERABLE_ERRORS)


def require_stream_authorizer(
    request: Request, principal: AgentPrincipal = Depends(require_agent_principal)
) -> StreamAuthorizer:
    async def authorize() -> bool:
        try:
            current = await run_in_threadpool(
                require_agent_principal, request, x_user_id=request.headers.get("X-User-ID")
            )
            return current == principal
        except STREAM_AUTH_ERRORS:
            return False

    return authorize
