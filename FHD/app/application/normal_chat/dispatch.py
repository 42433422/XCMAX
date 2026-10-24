"""Dispatch ownership and balanced request/tenant context lifetime."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .query_execution import JsonObject

SlotHandler = Callable[[JsonObject], JsonObject | None]


def request_tenant_id(request: Any | None) -> int | None:
    """Prefer middleware identity, falling back to the authenticated session."""
    if request is None:
        return None
    try:
        value = getattr(getattr(request, "state", None), "tenant_id", None)
        if value is not None:
            return int(value)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        from app.infrastructure.auth.tenant_context import resolve_tenant_id

        return resolve_tenant_id(request)
    except RECOVERABLE_ERRORS:
        return None


@contextmanager
def request_scope(
    request: Any | None, resolve_tenant: Callable[[Any | None], int | None]
) -> Iterator[None]:
    token = None
    if request is not None:
        try:
            from app.infrastructure.request_context import set_current_request

            token = set_current_request(request)
        except RECOVERABLE_ERRORS:
            pass
    try:
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(resolve_tenant(request)):
            yield
    finally:
        if token is not None:
            try:
                from app.infrastructure.request_context import reset_current_request

                reset_current_request(token)
            except RECOVERABLE_ERRORS:
                pass


def dispatch_read(
    message: str,
    *,
    request: Any | None,
    user_id: str | None,
    route_message: Callable[[str], JsonObject],
    has_pending_workflow: Callable[[str], bool],
    explicit_workflow_intent: Callable[[str], bool],
    scope: Callable[[Any | None], AbstractContextManager[None]],
    handlers: Mapping[str, SlotHandler],
    logger: logging.Logger,
) -> JsonObject | None:
    text = str(message or "").strip()
    if not text or (user_id is not None and has_pending_workflow(user_id)):
        return None
    if explicit_workflow_intent(text):
        logger.info(
            "chat dispatch decision: dispatch_path=normal_slot intent=workflow_tool_intent matched=False"
        )
        return None
    with scope(request):
        route = route_message(text)
        intent = str(route.get("intent") or "").strip()
        handler = handlers.get(intent)
        if handler is None:
            logger.info(
                "chat dispatch decision: dispatch_path=normal_slot intent=%s matched=False",
                intent or "unmatched",
            )
            return None
        payload = handler(route)
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False and not payload.get("response"):
        return None
    logger.info(
        "chat dispatch decision: dispatch_path=normal_slot intent=%s matched=True channel=%s",
        intent,
        "agent_tool" if payload.get("agent_tool_dispatch") else "slot",
    )
    return payload
