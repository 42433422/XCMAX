# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.planner_compat_execute")._facade()


async def compat_chat_stream_async(
    request: _facade().Request, body: _facade().XcagiCompatChatBody, *, ai_tier: str | None = None
):
    from app.application.normal_chat_dispatch import try_normal_slot_read_payload
    from app.fastapi_routes.xcagi_compat_chat_helpers import _sse_event_line

    slot_payload = try_normal_slot_read_payload(body.message, request=request)
    if isinstance(slot_payload, dict) and slot_payload.get("response"):
        runtime_context, _ = _facade()._merge_runtime_context_with_message_paths(
            body.context, body.message
        )
        runtime_context = _facade()._runtime_context_with_authenticated_actor(
            request, runtime_context
        )
        runtime_context = _facade()._runtime_context_with_trusted_dataset_access(
            request, runtime_context
        )
        channel = (
            "compat_chat_stream_agent_tool"
            if slot_payload.get("agent_tool_dispatch")
            else "compat_chat_stream_slot"
        )
        traced = _facade().attach_chat_trace_run(
            slot_payload,
            message=body.message,
            runtime_context=runtime_context,
            user_id=getattr(body, "user_id", None),
            source=getattr(body, "source", None),
            channel=channel,
            intent=str((slot_payload.get("data") or {}).get("intent") or "agent_tool"),
        )
        from app.application.conversation_memory import persist_recallable_chat_turn

        persist_recallable_chat_turn(
            user_id=_facade()._resolve_chat_user_id(request, body),
            message=body.message,
            source=body.source,
            context=runtime_context,
            response_data=traced,
        )
        response_text = str(slot_payload.get("response") or "")
        yield _sse_event_line({"type": "token", "text": response_text})
        yield _sse_event_line({"type": "done", "result": traced})
        return
    if not body.system_prompt and body.message:
        try:
            from app.services.conversation.manager import get_ai_conversation_service

            svc = get_ai_conversation_service()
            persona_svc = getattr(svc, "persona_service", None)
            _facade().logger.info(
                "persona_inject check: has_persona=%s msg=%s",
                persona_svc is not None,
                body.message[:50],
            )
            if persona_svc is not None:
                user_id = _facade()._resolve_chat_user_id(request, body)
                ctx = body.context or {}
                industry = ctx.get("industry") if isinstance(ctx, dict) else None
                if not industry:
                    industry = _facade()._derive_industry_from_session(request)
                history = _facade()._recent_history(svc, user_id)
                _facade().logger.info(
                    "persona_inject ctx=%s industry=%s history_len=%d",
                    _facade()._summarize_context_for_log(ctx),
                    industry,
                    len(history),
                )
                prompt, _params = await persona_svc.build_prompt_from_message(
                    user_id=user_id,
                    message=body.message,
                    history=history,
                    industry=industry,
                    context_prompt="",
                )
                body.system_prompt = prompt
                _facade().logger.info("persona_inject OK: prompt_len=%d", len(prompt))
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("persona_inject FAIL: %s", e, exc_info=True)
    tier = ai_tier or _facade().resolve_ai_tier(request)
    async for chunk in _facade()._xcagi_planner_stream_bytes_async(request, body, ai_tier=tier):
        yield chunk
