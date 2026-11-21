"""Conversation history and recallable memory persistence, independent of chat dispatch."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Protocol

from app.infrastructure.modstore_transport import safe_route_metadata
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SECRET_TEXT = re.compile(
    r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|密码|口令)\b\s*[:=]\s*)([^\s,;]+)|"
    r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+"
)
_SECRET_FIELD = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|credential|cookie|authorization|密码|口令)"
)


def _storage_safe(value: Any, *, depth: int = 0) -> Any:
    """Bound persisted transcript metadata and redact credential-like content."""
    if depth >= 8:
        return "[已截断]"
    if isinstance(value, dict):
        return {
            str(key)[:120]: "[已隐藏]"
            if _SECRET_FIELD.search(str(key))
            else _storage_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [_storage_safe(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        bounded = value[:8000]
        return _SECRET_TEXT.sub(
            lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", bounded
        )
    return value


class ConversationStore(Protocol):
    def save_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        messages: list[dict[str, Any]],
        expected_revision: int | None = None,
    ) -> list[int]: ...


def apply_history_fault(payload: dict[str, Any]) -> dict[str, Any]:
    """开发机故障注入。未设置 XCAGI_HISTORY_FAULT_FILE 时原样返回。"""
    import math
    import time
    from pathlib import Path

    from fastapi import HTTPException

    spec_path = os.environ.get("XCAGI_HISTORY_FAULT_FILE", "").strip()
    if not spec_path:
        return payload
    try:
        spec = Path(spec_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return payload
    if spec.startswith("delay:"):
        try:
            delay = float(spec.split(":", 1)[1] or 0)
        except ValueError:
            return payload
        if math.isfinite(delay) and delay > 0:
            # All callers are sync FastAPI handlers, executed in its worker thread pool.
            time.sleep(min(delay, 30))
        return payload
    if spec in {"500", "502", "504"}:
        raise HTTPException(status_code=int(spec), detail=f"history fault {spec}")
    if spec == "empty":
        cloned = dict(payload)
        cloned["messages"] = []
        cloned["sessions"] = []
        return cloned
    if spec == "partial":
        cloned = dict(payload)
        messages = list(cloned.get("messages") or [])
        sessions = list(cloned.get("sessions") or [])
        cloned["messages"] = messages[:1]
        cloned["sessions"] = sessions[:1]
        return cloned
    return payload


def persist_chat_turn(
    user_id: str,
    message: str,
    context: dict[str, Any],
    response_data: dict[str, Any],
    *,
    store: ConversationStore | None = None,
) -> dict[str, Any]:
    """
    在请求携带 session_id / conversation_id 时，将会话与工具结果摘要写入 ai_conversations，
    便于审计与和出货/产品等业务联动检索。
    """
    # Transcript bodies are authoritative; metadata projections may be bounded,
    # but must never silently truncate the original user or assistant message.
    redact = lambda value: _SECRET_TEXT.sub(
        lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", str(value or "")
    )
    message = redact(message)
    raw_inner = response_data.get("data")
    raw_inner = raw_inner if isinstance(raw_inner, dict) else {}
    reply = redact(
        response_data.get("response")
        or raw_inner.get("text")
        or (response_data.get("message") if not response_data.get("success") else "")
    )
    response_data = _storage_safe(response_data)
    session_id = str(context.get("conversation_id") or context.get("session_id") or "").strip()
    if (
        context.get("session_id")
        and context.get("conversation_id")
        and str(context["session_id"]).strip() != str(context["conversation_id"]).strip()
    ):
        raise ValueError("conflicting conversation identifiers")
    if not session_id:
        return {"status": "not_requested"}
    from app.application.task_conversation_store import durable_user_id

    # The web_normal_* id scopes model memory, not the authenticated history owner.
    owners = [
        durable_user_id(context[key]) for key in ("local_user_id", "actor_id") if key in context
    ]
    # Conversation identifiers and body user_id never authorize durable ownership.
    if not owners or None in owners or len(set(owners)) != 1:
        return {"status": "not_authorized"}
    history_user_id = str(owners[0])

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
    intent = str(
        inner_payload.get("intent")
        or inner_payload.get("tool_key")
        or tool_call.get("tool_id")
        or inner.get("action")
        or ""
    ).strip()
    from app.application.agent_orchestrator.trace_payloads import _payload_status
    from app.domain.task_lifecycle.results import (
        execution_result_requires_reconciliation,
        execution_result_wait_reason,
    )

    status: str = _payload_status(response_data)
    if status == "waiting_user" and execution_result_wait_reason(response_data) in {
        "authorization",
        "approval",
    }:
        status = "waiting_approval"
    elif status == "blocked" and execution_result_requires_reconciliation(response_data):
        status = "unknown"
    summary = {
        "success": bool(response_data.get("success")),
        "action": inner.get("action"),
        "status": status,
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
    from app.application.agent_orchestrator.business_harness import (
        extract_payload_business_result,
    )

    ui_payload = {
        "thinkingSteps": inner_payload.get("thinking_steps")
        or inner.get("thinking_steps")
        or response_data.get("thinking_steps"),
        "todoSteps": inner_payload.get("todo"),
        "workflowAction": status if status != "completed" else inner.get("action") or status,
        "nodeResults": inner_payload.get("node_results"),
        "approvalCard": inner_payload.get("approval_card"),
        "attachments": inner_payload.get("attachments"),
        "businessResult": extract_payload_business_result(response_data),
    }
    continuation = response_data.get("runtime_context_update")
    if response_data.get("runtime") == "codex" and isinstance(continuation, dict):
        ui_payload["runtimeContinuation"] = {
            "runId": continuation.get("agent_runtime_run_id"),
            "status": str(
                continuation.get("status") or response_data.get("execution_state") or status
            ),
            "sessionId": session_id,
        }
    ui_payload = {key: value for key, value in ui_payload.items() if value not in (None, "", [])}
    harness_metadata = {
        "protocol": context.get("business_harness_protocol") or "xcagi.business-harness.v1",
        "task_id": context.get("task_id"),
        "turn_id": context.get("turn_id"),
        "conversation_id": session_id,
        "run_id": summary.get("run_id"),
        "recall_bound": True,
    }
    turn_id = str(context.get("turn_id") or "").strip()
    user_fingerprint = uuid.uuid5(
        uuid.NAMESPACE_URL,
        str(message),
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
            "input_fingerprint": context.get("_conversation_input_fingerprint"),
            "summary": summary,
            "business_harness": harness_metadata,
        },
        ensure_ascii=False,
        default=str,
    )
    clarification_candidates = inner_payload.get("candidates")
    meta_assistant = json.dumps(
        {
            "role_hint": "assistant",
            **(
                {"route_metadata": safe_route_metadata(response_data)}
                if safe_route_metadata(response_data)
                else {}
            ),
            "summary": summary,
            "business_harness": harness_metadata,
            "ui": ui_payload,
            **(
                {"clarification_candidates": clarification_candidates[:20]}
                if isinstance(clarification_candidates, list) and clarification_candidates
                else {}
            ),
        },
        ensure_ascii=False,
        default=str,
    )
    if store is None:
        from app.services import get_conversation_service

        store = get_conversation_service()
    message_ids = store.save_turn(
        session_id=session_id,
        user_id=history_user_id,
        expected_revision=context.get("_conversation_revision"),
        messages=[
            {
                "role": "user",
                "content": message,
                "intent": intent or "chat",
                "metadata": meta_user,
                "idempotency_key": user_idempotency_key,
            },
            {
                "role": "assistant",
                "content": reply,
                "intent": intent or "assistant_reply",
                "metadata": meta_assistant,
                "idempotency_key": assistant_idempotency_key,
            },
        ],
    )
    from app.application.ai_chat.active_conversation import remember_active_conversation

    try:
        remember_active_conversation(context, conversation_id=session_id)
    except RECOVERABLE_ERRORS:
        logging.getLogger(__name__).warning(
            "active conversation pointer update failed", exc_info=True
        )
    return {
        "status": "saved",
        "conversation_id": session_id,
        "message_ids": message_ids,
        "revision": context.get("_conversation_revision", 0),
        "turn_id": turn_id,
    }


def retry_stored_chat_turn(
    context: dict[str, Any], turn_id: str, expected_revision: int
) -> dict[str, Any]:
    """Repair only the original authenticated receipt; never re-enter the planner."""
    from app.application.ai_chat.dialogue_memory import mark_history_persisted, stored_turn_receipt
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    receipt = stored_turn_receipt(context, turn_id)
    if receipt is None:
        raise LookupError("本轮原始回执不可用，请核对历史；不会重新执行任务。")
    if receipt["revision"] != expected_revision:
        raise ConversationRevisionError("会话已经修改，请重新读取历史。")
    context = {
        **context,
        "turn_id": turn_id,
        "_conversation_revision": expected_revision,
        "_conversation_input_fingerprint": receipt.get("input_fingerprint"),
    }
    ack = persist_chat_turn(
        str(context["local_user_id"]), receipt["message"], context, receipt["payload"]
    )
    mark_history_persisted(context, turn_id, ack)
    return {
        "success": True,
        "saved": ack["status"] == "saved",
        "durable": ack["status"] == "saved",
        **ack,
    }


def authorized_memory_context(
    user_id: str, context: dict[str, Any], *, write: bool = False
) -> tuple[str, dict[str, Any] | None] | None:
    """Validate a live actor and return its stable cross-session memory namespace.

    Dataset/Persy capture additionally needs server-derived dataset permissions;
    ordinary personal memory requires actor ownership, not a dataset grant.
    """
    from app.application.agent_task_context import (
        scoped_conversation_user_id,
        scoped_personal_memory_id,
    )
    from app.application.task_conversation_store import durable_user_id
    from app.infrastructure.auth.agent_mod_scope import (
        AgentModAuthorizationError,
        agent_dataset_access_context,
        validate_actor_context,
    )
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    if validate_actor_context(context) is not None:
        return None
    owner = durable_user_id(context.get("user_id"))
    if (
        owner is None
        or not (context.get("local_user_id") or context.get("actor_id"))
        or any(
            durable_user_id(context[key]) != owner
            for key in ("local_user_id", "actor_id")
            if key in context
        )
    ):
        return None
    if not context.get("session_id") and not context.get("conversation_id"):
        return None
    normalized = str(user_id or "").strip()
    if normalized != scoped_conversation_user_id(normalized, context):
        return None
    access = None
    if context.get("_dataset_access_context_trusted") or context.get("_dataset_access_context"):
        access_errors: tuple[type[Exception], ...] = (
            AgentModAuthorizationError,
        ) + RECOVERABLE_ERRORS
        try:
            principal = agent_dataset_access_context(context)
        except access_errors:
            return None
        required = "dataset.write" if write else "dataset.read"
        if principal.is_admin or required in principal.permissions:
            access = principal.to_dict()
    memory_namespace = scoped_personal_memory_id(context)
    if not memory_namespace:
        return None
    return memory_namespace, access


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
    authorized = authorized_memory_context(user_id, context, write=True)
    if authorized is None:
        return
    _memory_namespace, access_context = authorized
    if access_context is None and context.get("persy_memory_scope") == "tenant":
        return  # A private-memory capability never authorizes a tenant-wide write.
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
    # Raw dialogue remains in the conversation store. Only active, scoped
    # MemoryV2 records supply long-term evidence.
    from app.application.persy_memory_app_service import get_persy_memory_app_service

    service = get_persy_memory_app_service()
    if access_context is not None:
        captured = service.capture_conversation_turn(
            access_context=access_context,
            user_message=message,
            assistant_message=assistant_text,
            session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
            source=str(source or "chat"),
            scope=str(context.get("persy_memory_scope") or "user"),
        )
    else:
        captured = service.capture_personal_turn(
            user_id=user_id,
            context=context,
            user_message=message,
            assistant_message=assistant_text,
            source=str(source or "chat"),
        )
    if isinstance(captured, dict) and not captured.get("success"):
        logger.warning(
            "memory candidate capture incomplete: %s",
            captured.get("errors") or captured.get("error_code"),
        )
