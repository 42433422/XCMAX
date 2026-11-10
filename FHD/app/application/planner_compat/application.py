"""Ordered single and batch request flows with shared turn execution."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request

from app.application.planner_compat_execute import ChatTurnExecutor
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_error,
    execution_result_requires_reconciliation,
    execution_result_states,
    execution_result_wait_reason,
)
from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .admission import ChatAdmission
from .offline import is_offline, offline_turn
from .protocols import ChatBody, ChatTurn, Context, Payload


class BusinessAction(Protocol):
    def __call__(
        self,
        message: str,
        *,
        runtime_context: Context,
        user_id: str | None,
        request: Request,
    ) -> Payload | None: ...


@dataclass(frozen=True)
class FastPaths:
    business: BusinessAction
    kitten: Callable[[Context, str], Awaitable[tuple[Context, Payload]]]


@dataclass(frozen=True)
class CompatChatApplication:
    admission: ChatAdmission
    execution: ChatTurnExecutor
    fast_paths: FastPaths
    set_mode: Callable[[str], None]
    assert_access: Callable[[Request], None]
    resolve_tier: Callable[[Request], str]
    timeout_seconds: Callable[[], float]
    single_turn: Callable[[Request, XcagiCompatChatBody], Awaitable[Payload]]

    def _mode(self, body: ChatBody) -> None:
        mode = (body.mode or "").strip().lower()
        if mode in ("online", "offline"):
            self.set_mode(mode)

    def _attach(self, payload: Payload, turn: ChatTurn) -> Payload:
        return self.execution.trace.attach(
            payload,
            turn.body,
            message=turn.message,
            runtime_context=turn.context,
            channel=turn.channel,
        )

    async def single(self, request: Request, body: XcagiCompatChatBody) -> Payload:
        context = self.admission.context(request, body.context, body.message)
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        self.assert_access(request)
        context = self.admission.with_tier(context, self.resolve_tier(request))
        if is_offline(body.mode):
            turn = ChatTurn(body, body.message, context, "compat_chat_offline")
            from app.application.ai_chat.dialogue_memory import prepare_chat_turn

            prepared = prepare_chat_turn(body.message, context)
            if prepared is not None:
                return self._attach(prepared, turn)
            return self._attach(
                offline_turn(request, turn, self.admission, self.fast_paths.business),
                turn,
            )
        from app.application.ai_chat.chat_evidence import (
            prepare_chat_evidence,
        )

        context = await asyncio.to_thread(prepare_chat_evidence, request, context, body.message)
        context.setdefault(
            "conversation_id",
            context.get("session_id")
            or body.user_id
            or context.get("local_user_id")
            or context.get("actor_id")
            or "default",
        )
        context.pop("_chat_evidence_prepared_marker", None)
        body.context = context
        if context.get("kitten_analyzer"):
            with model_rate_limit_scope(context):
                context, kitten_extra = await self.fast_paths.kitten(context, body.message)
            body.context = context
        else:
            kitten_extra = {}
        turn = ChatTurn(body, body.message, context, "compat_chat", kitten_extra or None)
        admitted = self.admission.check(request, turn)
        if admitted.payload is not None:
            return self._attach(
                admitted.payload,
                ChatTurn(
                    body,
                    body.message,
                    (admitted.context_update if admitted.context_update is not None else context),
                    turn.channel,
                ),
            )
        return await self.execution.execute(turn, timeout=self.timeout_seconds())

    async def batch(self, request: Request, body: XcagiCompatChatBatchBody) -> Payload:
        messages = [str(item).strip() for item in body.messages or [] if str(item).strip()]
        if not messages:
            raise HTTPException(status_code=400, detail="messages 须为非空字符串数组")
        self.assert_access(request)
        values = body.model_dump(exclude={"messages", "context"})
        rolling_context = dict(body.context or {})
        batch_turn = str(rolling_context.get("turn_id") or uuid.uuid4().hex)
        turn_ids = [
            uuid.uuid5(uuid.NAMESPACE_URL, f"{batch_turn}:{index}").hex
            for index in range(len(messages))
        ]
        results: list[Payload] = []
        paused_state = ""
        wait_reason = ""
        processed_count = 0
        for index, message in enumerate(messages):
            if paused_state:
                results.append(
                    {
                        "success": False,
                        "execution_state": "blocked",
                        "message": "前序任务尚未完成，本项未执行。请先核对原任务状态。",
                        "data": {
                            "status": "not_started",
                            "turn_id": turn_ids[index],
                            "blocked_by_turn_id": turn_ids[processed_count - 1],
                        },
                    }
                )
                continue
            context = {
                **rolling_context,
                "turn_id": turn_ids[index],
            }
            single = XcagiCompatChatBody(message=message, context=context, **values)
            try:
                result = await self.single_turn(request, single)
            except (HTTPException,) + RECOVERABLE_ERRORS as exc:
                error = (
                    exc
                    if isinstance(exc, HTTPException)
                    else self.execution.responses.http_error(exc)
                )
                details: Payload = error.detail if isinstance(error.detail, dict) else {}
                message = str(details.get("message") or details.get("response") or error.detail)
                result = {
                    **details,
                    "success": False,
                    "message": message,
                    "response": str(details.get("response") or message),
                }
                if not isinstance(exc, HTTPException) or error.status_code >= 500:
                    result.update(execution_outcome="unknown", requires_reconciliation=True)
            data = result.get("data")
            update = data.get("runtime_context") if isinstance(data, dict) else None
            if isinstance(update, dict):
                rolling_context = update
            results.append(result)
            processed_count += 1
            wait_reason = execution_result_wait_reason(result)
            unknown_effect = any(
                execution_result_states(item)
                & {"unknown", "interrupted", "partial", "partial_success"}
                or item.get("reconciliation_required")
                or item.get("requires_reconciliation")
                for item in execution_result_envelopes(result)
            )
            if unknown_effect:
                paused_state, wait_reason = "blocked", "pending_result"
            elif wait_reason:
                paused_state = {
                    "authorization": "waiting_approval",
                    "approval": "waiting_approval",
                    "input": "waiting_user",
                    "paused": "paused",
                }[wait_reason]
            elif execution_result_requires_reconciliation(result):
                paused_state = "blocked"
                wait_reason = "pending_result"
        completed = all(
            item.get("success") and not execution_result_error(item) for item in results
        )
        return {
            "success": completed,
            "execution_state": paused_state or ("completed" if completed else "failed"),
            "wait_reason": wait_reason,
            "batch": True,
            "batch_turn_id": batch_turn,
            "turn_ids": turn_ids,
            "results": results,
            "count": len(results),
            "processed_count": processed_count,
        }
