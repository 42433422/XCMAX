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
from .offline import is_offline, offline_turn
from .persona import PersonaEnricher
from .protocols import ChatTurn, Context, Payload


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
        intent: str = "langgraph_chat",
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
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        if is_offline(body.mode):
            turn = ChatTurn(body, body.message, context, "compat_chat_offline")
            from app.application.ai_chat.dialogue_memory import prepare_chat_turn

            prepared = prepare_chat_turn(body.message, context)
            if prepared is not None:
                yield self.encode_event({"type": "done", "result": prepared})
                return
            payload = offline_turn(request, turn, self.admission, self.fast_paths.business)
            reply = str(payload.get("response") or payload.get("message") or "")
            if reply:
                yield self.encode_event({"type": "token", "text": reply})
            yield self.encode_event(
                {
                    "type": "done",
                    "result": self.trace(
                        payload,
                        message=body.message,
                        runtime_context=context,
                        user_id=body.user_id,
                        source=body.source,
                        channel=turn.channel,
                    ),
                }
            )
            return
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
                context, _ = await self.fast_paths.kitten(context, body.message)
            body.context = context
        await self.persona.enrich(request, body)
        tier = ai_tier or self.resolve_tier(request)
        self.logger.info(
            "chat dispatch decision: dispatch_path=llm_planner channel=compat_chat_stream_llm tier=%s",
            tier,
        )
        async with aclosing(self.backend(request, body, ai_tier=tier)) as stream:
            async for chunk in stream:
                yield chunk
