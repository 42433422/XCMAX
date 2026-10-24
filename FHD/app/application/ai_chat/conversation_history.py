"""Conversation history and recallable memory persistence, independent of chat dispatch."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Protocol


class ConversationStore(Protocol):
    def save_message(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        intent: str,
        metadata: str,
        idempotency_key: str,
    ) -> Any: ...


def persist_chat_turn(
    user_id: str,
    message: str,
    context: dict[str, Any],
    response_data: dict[str, Any],
    *,
    store: ConversationStore | None = None,
) -> None:
    """
    在请求携带 session_id / conversation_id 时，将会话与工具结果摘要写入 ai_conversations，
    便于审计与和出货/产品等业务联动检索。
    """
    session_id = str(context.get("session_id") or context.get("conversation_id") or "").strip()
    if not session_id:
        return
    from app.application.task_conversation_store import durable_user_id

    # The web_normal_* id scopes model memory, not the authenticated history owner.
    owner_id = durable_user_id(context.get("local_user_id")) or durable_user_id(
        context.get("actor_id")
    )
    history_user_id = str(owner_id) if owner_id is not None else user_id

    inner = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}
    if not isinstance(inner, dict):
        inner = {}
    inner_payload = inner.get("data") if isinstance(inner.get("data"), dict) else {}
    tool_call = (
        response_data.get("toolCall") if isinstance(response_data.get("toolCall"), dict) else {}
    )
    if not isinstance(inner_payload, dict):
        inner_payload = {}
    if not isinstance(tool_call, dict):
        tool_call = {}
    reply = str(
        response_data.get("response")
        or inner.get("text")
        or (response_data.get("message") if not response_data.get("success") else "")
        or ""
    )[:8000]
    intent = str(
        inner_payload.get("intent")
        or inner_payload.get("tool_key")
        or tool_call.get("tool_id")
        or inner.get("action")
        or ""
    ).strip()
    summary = {
        "success": bool(response_data.get("success")),
        "action": inner.get("action"),
        "intent": intent,
        "toolCall": tool_call or None,
        "plan_id": inner_payload.get("plan_id"),
        "document": (inner_payload.get("document") or {}).get("doc_name")
        if isinstance(inner_payload.get("document"), dict)
        else None,
        "excel_import": inner_payload.get("result")
        if inner_payload.get("intent") == "excel_import_to_db"
        else None,
        "task_id": context.get("task_id"),
        "turn_id": context.get("turn_id"),
        "run_id": response_data.get("run_id")
        or response_data.get("agent_run_id")
        or inner.get("run_id")
        or inner.get("agent_run_id"),
    }
    ui_payload = {
        "thinkingSteps": inner_payload.get("thinking_steps")
        or inner.get("thinking_steps")
        or response_data.get("thinking_steps"),
        "todoSteps": inner_payload.get("todo"),
        "workflowAction": inner.get("action"),
        "nodeResults": inner_payload.get("node_results"),
        "approvalCard": inner_payload.get("approval_card"),
        "attachments": inner_payload.get("attachments"),
    }
    ui_payload = {key: value for key, value in ui_payload.items() if value not in (None, "", [])}
    harness_metadata = {
        "protocol": context.get("business_harness_protocol") or "xcagi.business-harness.v1",
        "task_id": context.get("task_id"),
        "turn_id": context.get("turn_id"),
        "conversation_id": session_id,
        "run_id": summary.get("run_id"),
    }
    turn_id = str(context.get("turn_id") or "").strip()
    user_fingerprint = uuid.uuid5(
        uuid.NAMESPACE_URL,
        str(message)[:8000],
    ).hex
    assistant_fingerprint = uuid.uuid5(
        uuid.NAMESPACE_URL,
        reply,
    ).hex
    user_idempotency_key = (
        f"xcagi.business-harness.v1:{turn_id}:user:{user_fingerprint}" if turn_id else ""
    )
    assistant_idempotency_key = (
        f"xcagi.business-harness.v1:{turn_id}:assistant:{assistant_fingerprint}" if turn_id else ""
    )
    meta_user = json.dumps(
        {
            "role_hint": "user",
            "summary": summary,
            "business_harness": harness_metadata,
        },
        ensure_ascii=False,
        default=str,
    )[:12000]
    meta_assistant = json.dumps(
        {
            "role_hint": "assistant",
            "summary": summary,
            "business_harness": harness_metadata,
            "ui": ui_payload,
        },
        ensure_ascii=False,
        default=str,
    )[:12000]
    if store is None:
        from app.services import get_conversation_service

        store = get_conversation_service()
    conv = store
    conv.save_message(
        session_id=session_id,
        user_id=history_user_id,
        role="user",
        content=str(message)[:8000],
        intent=intent or "chat",
        metadata=meta_user,
        idempotency_key=user_idempotency_key,
    )
    if not isinstance(response_data, dict):
        response_data = {}
    conv.save_message(
        session_id=session_id,
        user_id=history_user_id,
        role="assistant",
        content=reply,
        intent=intent or "assistant_reply",
        metadata=meta_assistant,
        idempotency_key=assistant_idempotency_key,
    )


def persist_recallable_chat_turn(
    *,
    user_id: str,
    message: str,
    source: str | None,
    context: dict[str, Any],
    response_data: dict[str, Any],
) -> None:
    if context.get("memory_capture_enabled") is False or not response_data.get("success"):
        return
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return
    from app.utils.deployment import is_desktop_mode

    trusted_principal = context.get("_dataset_access_context_trusted") is True
    if not trusted_principal and (not is_desktop_mode()):
        return
    raw_inner = response_data.get("data")
    inner: dict[str, Any] = raw_inner if isinstance(raw_inner, dict) else {}
    action = str(response_data.get("action") or inner.get("action") or "").strip().lower()
    if action in {
        "error",
        "error_fallback",
        "fallback",
        "goodbye",
        "greeting",
        "help",
        "requires_token",
    }:
        return
    sensitive = re.compile(
        "(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
        re.I,
    )
    assistant_text = str(response_data.get("response") or "").strip()
    if not assistant_text:
        if not isinstance(inner, dict):
            inner = {}
        assistant_text = str(inner.get("text") or inner.get("message") or "").strip()
    if not assistant_text or sensitive.search(f"{message}\n{assistant_text}"):
        return
    from app.application.user_memory_vector_app_service import (
        get_user_memory_vector_ingest_app_service,
    )

    service = get_user_memory_vector_ingest_app_service()
    chunk = service.build_chat_turn_chunk(
        user_id=normalized_user_id,
        user_message=message,
        assistant_message=assistant_text,
        session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
        source=str(source or "chat"),
    )
    service.ingest_chunks(normalized_user_id, [chunk])
    access_context = context.get("_dataset_access_context")
    if trusted_principal and isinstance(access_context, dict):
        from app.application.persy_memory_app_service import get_persy_memory_app_service

        get_persy_memory_app_service().capture_conversation_turn(
            access_context=access_context,
            user_message=message,
            assistant_message=assistant_text,
            session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
            source=str(source or "chat"),
            scope="tenant"
            if str(context.get("persy_memory_scope") or "").strip().lower() == "tenant"
            else "user",
        )
