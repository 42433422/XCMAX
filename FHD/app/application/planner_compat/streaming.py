"""Issue and slot admission before persona-enriched compatibility streaming."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass
from logging import Logger
from typing import Protocol

from fastapi import Request

from app.fastapi_routes.xcagi_compat_chat_models import XcagiCompatChatBody

from .admission import ChatAdmission
from .application import FastPaths
from .persona import PersonaEnricher
from .protocols import Context, Payload


class StreamBackend(Protocol):
    def __call__(
        self, request: Request, body: XcagiCompatChatBody, *, ai_tier: str
    ) -> AsyncGenerator[bytes, None]: ...


class StreamTrace(Protocol):
    def __call__(
        self,
        payload: Payload,
        *,
        message: str,
        runtime_context: Context,
        user_id: str | None,
        source: str | None,
        channel: str,
        intent: str = "legacy_chat_adapter",
    ) -> Payload: ...


@dataclass(frozen=True)
class CompatStream:
    admission: ChatAdmission
    fast_paths: FastPaths
    persona: PersonaEnricher
    trace: StreamTrace
    encode_event: Callable[[Payload], bytes]
    resolve_tier: Callable[[Request], str]
    backend: StreamBackend
    logger: Logger

    async def run(
        self, request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
    ) -> AsyncGenerator[bytes, None]:
        context = self.admission.context(request, body.context, body.message)
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
                payload = {"success": True, "response": question, "data": {"intent": "clarify"}}
                yield self.encode_event({"type": "token", "text": question})
                yield self.encode_event(
                    {
                        "type": "done",
                        "result": self.trace(
                            payload,
                            message=body.message,
                            runtime_context=context,
                            user_id=body.user_id,
                            source=body.source,
                            channel="compat_chat_customer_disambiguation",
                        ),
                    }
                )
                return
        issue = await self.fast_paths.issue(request, context, body.message)
        if issue is not None:
            text, payload = issue
            yield self.encode_event({"type": "token", "text": text})
            yield self.encode_event(
                {
                    "type": "done",
                    "result": self.trace(
                        payload,
                        message=body.message,
                        runtime_context=context,
                        user_id=body.user_id,
                        source=body.source,
                        channel="compat_chat_stream_issue_intake",
                    ),
                }
            )
            return
        slot = await self.fast_paths.slot(
            body.message, request=request, user_id=str(body.user_id or "default")
        )
        slot_data = slot.get("data") if isinstance(slot, dict) else None
        if isinstance(slot, dict) and isinstance(slot_data, dict):
            from app.application.ai_chat.chat_evidence import (
                prepare_chat_evidence,
                use_contextual_reply,
            )

            enriched = await asyncio.to_thread(
                prepare_chat_evidence, request, context, body.message
            )
            if use_contextual_reply(slot, enriched, body.message):
                slot = None
        if isinstance(slot, dict) and slot.get("response"):
            context = self.admission.context(request, body.context, body.message)
            channel = (
                "compat_chat_stream_agent_tool"
                if slot.get("agent_tool_dispatch")
                else "compat_chat_stream_slot"
            )
            intent = str((slot.get("data") or {}).get("intent") or "agent_tool")
            traced = self.trace(
                slot,
                message=body.message,
                runtime_context=context,
                user_id=body.user_id,
                source=body.source,
                channel=channel,
                intent=intent,
            )
            self.logger.info(
                "chat dispatch decision: dispatch_path=compat_slot channel=%s intent=%s run_id=%s",
                channel,
                intent,
                str(traced.get("run_id") or ""),
            )
            yield self.encode_event({"type": "token", "text": str(slot.get("response") or "")})
            yield self.encode_event({"type": "done", "result": traced})
            return
        await self.persona.enrich(request, body)
        tier = ai_tier or self.resolve_tier(request)
        self.logger.info(
            "chat dispatch decision: dispatch_path=llm_planner channel=compat_chat_stream_llm tier=%s",
            tier,
        )
        async with aclosing(self.backend(request, body, ai_tier=tier)) as stream:
            async for chunk in stream:
                yield chunk
