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
        from app.application.ai_chat.dialogue_memory import (
            dialogue_reply,
            prepare_chat_turn,
            settle_chat_turn,
        )

        prepared = prepare_chat_turn(body.message, context)
        if prepared is not None:
            traced = self.trace(
                prepared,
                message=body.message,
                runtime_context=context,
                user_id=body.user_id,
                source=body.source,
                channel="compat_chat_stream_dialogue_memory",
                intent="dialogue_memory",
            )
            yield self.encode_event({"type": "done", "result": traced})
            return
        dialogue = await dialogue_reply(body.message, context)
        if dialogue is not None:
            reply = str(dialogue.get("response") or "")
            sent: list[str] = []
            try:
                for start in range(0, max(len(reply), 1), 80):
                    if await request.is_disconnected():
                        partial = "".join(sent)
                        settle_chat_turn(
                            body.message,
                            context,
                            {
                                "success": False,
                                "response": partial,
                                "message": "中断",
                                "data": {
                                    "status": "interrupted",
                                    "text": partial,
                                    "action": "dialogue_memory",
                                },
                            },
                            "interrupted",
                        )
                        yield self.encode_event(
                            {
                                "type": "error",
                                "message": "生成已中断，未完成的内容不能当成已完成的分析。",
                                "status": "interrupted",
                            }
                        )
                        return
                    piece = reply[start : start + 80]
                    sent.append(piece)
                    if piece:
                        yield self.encode_event({"type": "token", "text": piece})
                    await asyncio.sleep(0.05)
                    if await request.is_disconnected():
                        partial = "".join(sent)
                        settle_chat_turn(
                            body.message,
                            context,
                            {
                                "success": False,
                                "response": partial,
                                "message": "中断",
                                "data": {
                                    "status": "interrupted",
                                    "text": partial,
                                    "action": "dialogue_memory",
                                },
                            },
                            "interrupted",
                        )
                        yield self.encode_event(
                            {
                                "type": "error",
                                "message": "生成已中断，未完成的内容不能当成已完成的分析。",
                                "status": "interrupted",
                            }
                        )
                        return
            except (GeneratorExit, asyncio.CancelledError):
                settle_chat_turn(
                    body.message,
                    context,
                    {
                        "success": False,
                        "response": "".join(sent),
                        "data": {"status": "interrupted"},
                    },
                    "interrupted",
                )
                raise
            except Exception:
                settle_chat_turn(
                    body.message, context, {"success": False, "response": ""}, "failed"
                )
                raise
            traced = self.trace(
                dialogue,
                message=body.message,
                runtime_context=context,
                user_id=body.user_id,
                source=body.source,
                channel="compat_chat_stream_dialogue_memory",
                intent="dialogue_memory",
            )
            yield self.encode_event({"type": "done", "result": traced})
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
