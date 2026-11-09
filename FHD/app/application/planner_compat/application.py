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


class SlotRead(Protocol):
    async def __call__(self, message: str, *, request: Request, user_id: str) -> Payload | None: ...


@dataclass(frozen=True)
class FastPaths:
    issue: Callable[[Request, Context, str], Awaitable[tuple[str, Payload] | None]]
    business: BusinessAction
    slot: SlotRead
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
        self._mode(body)
        context = self.admission.context(request, body.context, body.message)
        self.assert_access(request)
        context = self.admission.with_tier(context, self.resolve_tier(request))
        from app.application.ai_chat.chat_evidence import (
            _CUSTOMER_LOOKUP,
            customer_name_question,
            prepare_chat_evidence,
        )

        if _CUSTOMER_LOOKUP.search(body.message):
            enriched = await asyncio.to_thread(
                prepare_chat_evidence, request, context, body.message
            )
            question = customer_name_question(body.message, enriched)
            if question:
                return self._attach(
                    self.admission.reply(question),
                    ChatTurn(body, body.message, context, "compat_chat_customer_disambiguation"),
                )
        issue = await self.fast_paths.issue(request, context, body.message)
        if issue is not None:
            return self._attach(
                issue[1], ChatTurn(body, body.message, context, "compat_chat_issue")
            )
        business = self.fast_paths.business(
            body.message, runtime_context=context, user_id=body.user_id, request=request
        )
        if business is not None:
            return business
        context, kitten_extra = await self.fast_paths.kitten(context, body.message)
        slot = await self.fast_paths.slot(
            body.message, request=request, user_id=str(body.user_id or "default")
        )
        from app.application.ai_chat.chat_evidence import (
            prepare_chat_evidence,
            use_contextual_reply,
        )

        context = await asyncio.to_thread(prepare_chat_evidence, request, context, body.message)
        if isinstance(slot, dict) and use_contextual_reply(slot, context, body.message):
            slot = None
        if isinstance(slot, dict) and slot.get("response"):
            channel = (
                "compat_chat_agent_tool" if slot.get("agent_tool_dispatch") else "compat_chat_slot"
            )
            return self._attach(slot, ChatTurn(body, body.message, context, channel))
        turn = ChatTurn(body, body.message, context, "compat_chat", kitten_extra or None)
        admitted = self.admission.check(request, turn)
        if admitted.payload is not None:
            return self._attach(
                admitted.payload,
                ChatTurn(
                    body,
                    body.message,
                    admitted.context_update if admitted.context_update is not None else context,
                    turn.channel,
                ),
            )
        from app.application.ai_chat.dialogue_memory import prepare_chat_turn

        prepared = prepare_chat_turn(body.message, context)
        if prepared is not None:
            return self._attach(prepared, turn)
        return await self.execution.execute(request, turn, timeout=self.timeout_seconds())

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
