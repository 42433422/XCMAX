"""Ordered single and batch request flows with shared turn execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request

from app.application.planner_compat_execute import ChatTurnExecutor
from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)

from .admission import ChatAdmission
from .ports import ChatBody, ChatTurn, Context, Payload


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
    def __call__(self, message: str, *, request: Request, user_id: str) -> Payload | None: ...


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
        slot = self.fast_paths.slot(
            body.message, request=request, user_id=str(body.user_id or "default")
        )
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
        return await self.execution.execute(request, turn, timeout=self.timeout_seconds())

    async def batch(self, request: Request, body: XcagiCompatChatBatchBody) -> Payload:
        messages = [str(item).strip() for item in body.messages or [] if str(item).strip()]
        if not messages:
            raise HTTPException(status_code=400, detail="messages 须为非空字符串数组")
        self.assert_access(request)
        tier = self.resolve_tier(request)
        self._mode(body)
        timeout = self.timeout_seconds()
        rolling_context = body.context
        client = self.execution.backends.client(request)
        results: list[Payload] = []
        for message in messages:
            context = self.admission.context(request, rolling_context, message)
            context = self.admission.with_tier(context, tier)
            business = self.fast_paths.business(
                message, runtime_context=context, user_id=body.user_id, request=request
            )
            if business is not None:
                results.append(business)
                continue
            turn = ChatTurn(body, message, context, "compat_chat_batch")
            admitted = self.admission.check(request, turn)
            if admitted.payload is not None:
                if admitted.context_update is not None:
                    rolling_context = admitted.context_update
                    turn = ChatTurn(body, message, rolling_context, turn.channel)
                results.append(self._attach(admitted.payload, turn))
                continue
            results.append(
                await self.execution.execute(request, turn, timeout=timeout, batch_client=client)
            )
        return {
            "success": all(result.get("success") for result in results),
            "batch": True,
            "results": results,
            "count": len(results),
        }
