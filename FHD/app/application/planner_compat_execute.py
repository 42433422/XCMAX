"""Shared turn execution for JSON and batch planner compatibility chat."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.application.planner_compat.protocols import (
    AwaitTimeout,
    ChatBackends,
    ChatResponses,
    ChatTrace,
    ChatTurn,
    Payload,
)
from app.application.planner_compat.tracing import TurnTrace
from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class ChatTurnExecutor:
    backends: ChatBackends
    responses: ChatResponses
    trace: ChatTrace
    await_timeout: AwaitTimeout

    async def execute(self, turn: ChatTurn, *, timeout: float) -> Payload:
        trace = TurnTrace(turn, turn.planner_context(), self.trace)
        try:
            call = (
                self.backends.mainline(turn.body, trace.context, message=turn.message)
                if turn.is_batch
                else self.backends.mainline(
                    turn.body, trace.context, kitten_extra=turn.kitten_extra
                )
            )
            payload = await self.await_timeout(call, timeout=timeout)
            if payload.get("run_id") or payload.get("agent_run_id"):
                return payload
            return trace.attach(payload, mainline=True)
        except TimeoutError:
            return trace.attach(self.responses.timeout(timeout), mainline=True)
        except RECOVERABLE_ERRORS as exc:
            if turn.is_batch:
                error = self.responses.http_error(exc)
                detail = error.detail if isinstance(error.detail, str) else str(error.detail)
                return trace.attach(
                    {"success": False, "message": detail, "response": detail}, mainline=True
                )
            raise self.responses.http_error(exc) from exc


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> Payload:
    """Retain direct executor imports while the public service owns composition."""
    from app.application.planner_compat_service import execute_compat_chat as execute

    return await execute(request, body)


async def execute_compat_chat_batch(request: Request, body: XcagiCompatChatBatchBody) -> Payload:
    from app.application.planner_compat_service import execute_compat_chat_batch as execute

    return await execute(request, body)
