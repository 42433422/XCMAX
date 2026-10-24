"""Shared turn execution for JSON and batch planner compatibility chat."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi import Request

from app.application.planner_compat.ports import (
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
    clear_legacy_tool_result: Callable[[Any], None]
    workspace_root: Callable[[], str]
    logger: Logger

    async def execute(
        self, request: Request, turn: ChatTurn, *, timeout: float, batch_client: Any = None
    ) -> Payload:
        trace = TurnTrace(turn, turn.planner_context(), self.trace)
        if self.backends.use_mainline(trace.context):
            try:
                # Preserve the existing call signatures for per-facade patches.
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
                if not self.backends.allow_fallback(trace.context):
                    error = self.responses.http_error(exc)
                    if not turn.is_batch:
                        raise error from exc
                    detail = error.detail if isinstance(error.detail, str) else str(error.detail)
                    return {
                        "success": False,
                        "message": detail,
                        "response": detail,
                        "data": {"error": str(exc)},
                    }
                self.logger.warning(
                    "AIChatApplicationService mainline failed; legacy fallback explicitly allowed: %s",
                    exc,
                    exc_info=True,
                )
        return await self._legacy(request, trace, timeout=timeout, batch_client=batch_client)

    async def _legacy(
        self, request: Request, trace: TurnTrace, *, timeout: float, batch_client: Any
    ) -> Payload:
        turn = trace.turn
        try:
            if turn.is_batch:
                trace.start(self.logger)
                workspace_root = self.workspace_root()
                client = batch_client
            else:
                workspace_root = self.workspace_root()
                client = self.backends.client(request)
                trace.start(self.logger)
            reply = await self.await_timeout(
                asyncio.to_thread(
                    self.backends.legacy,
                    turn.message,
                    runtime_context=trace.context or None,
                    system_prompt=turn.body.system_prompt,
                    workspace_root=workspace_root,
                    db_write_token=turn.body.db_write_token,
                    client=client,
                ),
                timeout=timeout,
            )
            parsed = self._token_request(reply)
            if parsed is not None:
                return trace.finish(self.responses.token_required(parsed))
            self.clear_legacy_tool_result(reply)
            # Single-chat formatting historically occurs outside the execution
            # error boundary; batch failures must remain an individual result.
            if turn.is_batch:
                return trace.finish(self.responses.reply(reply))
        except TimeoutError:
            return trace.finish(self.responses.timeout(timeout))
        except RECOVERABLE_ERRORS as exc:
            if turn.is_batch:
                error = self.responses.http_error(exc)
                return trace.finish(
                    {
                        "success": False,
                        "message": error.detail
                        if isinstance(error.detail, str)
                        else str(error.detail),
                    }
                )
            if trace.run_id is not None:
                trace.finish(
                    {
                        "success": False,
                        "message": str(exc),
                        "response": str(exc),
                        "data": {"error": str(exc)},
                    }
                )
            raise self.responses.http_error(exc) from exc
        return trace.finish(self.responses.reply(reply, kitten_attachments=turn.kitten_extra))

    @staticmethod
    def _token_request(reply: str | Payload) -> Payload | None:
        try:
            parsed = json.loads(reply) if isinstance(reply, str) else reply
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) and parsed.get("requires_token") else None


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> Payload:
    """Retain direct executor imports while the public service owns composition."""
    from app.application.planner_compat_service import execute_compat_chat as execute

    return await execute(request, body)


async def execute_compat_chat_batch(request: Request, body: XcagiCompatChatBatchBody) -> Payload:
    from app.application.planner_compat_service import execute_compat_chat_batch as execute

    return await execute(request, body)
