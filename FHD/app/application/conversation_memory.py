"""Shared cross-session memory hooks for every chat transport.

The desktop has JSON and streaming chat entry points.  Keeping capture and
recall here prevents a transport from returning a successful answer while
silently skipping the user's long-term memory stores.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SENSITIVE_MEMORY_RE = re.compile(
    r"(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
    re.I,
)
_NON_MEMORY_ACTIONS = frozenset(
    {
        "error",
        "error_fallback",
        "fallback",
        "goodbye",
        "greeting",
        "help",
        "requires_token",
    }
)


def resolve_memory_owner_id(user_id: str, context: dict[str, Any] | None) -> str:
    """Return the stable Persy owner instead of a conversation id."""

    runtime_context = context if isinstance(context, dict) else {}
    access = runtime_context.get("_dataset_access_context")
    if runtime_context.get("_dataset_access_context_trusted") is True and isinstance(access, dict):
        actor_id = str(access.get("actor_id") or "").strip()
        if actor_id:
            return actor_id
    return str(user_id or "").strip()


def resolve_vector_memory_owner_id(user_id: str, context: dict[str, Any] | None) -> str:
    """Return a tenant-qualified vector index owner when the principal is trusted."""

    runtime_context = context if isinstance(context, dict) else {}
    access = runtime_context.get("_dataset_access_context")
    if runtime_context.get("_dataset_access_context_trusted") is True and isinstance(access, dict):
        actor_id = str(access.get("actor_id") or "").strip()
        tenant_id = str(access.get("tenant_id") or "").strip()
        if actor_id:
            return f"{tenant_id}:{actor_id}" if tenant_id else actor_id
    return str(user_id or "").strip()


def _assistant_text(response_data: dict[str, Any]) -> str:
    text = str(response_data.get("response") or "").strip()
    if text:
        return text
    inner = response_data.get("data")
    if not isinstance(inner, dict):
        return ""
    return str(inner.get("text") or inner.get("message") or "").strip()


def persist_recallable_chat_turn(
    *,
    user_id: str,
    message: str,
    source: str | None,
    context: dict[str, Any] | None,
    response_data: dict[str, Any],
) -> None:
    """Persist a successful chat turn to vector memory and trusted Persy memory.

    The two stores are intentionally isolated: a vector failure must not block
    structured candidate extraction, and vice versa.
    """

    runtime_context = context if isinstance(context, dict) else {}
    if runtime_context.get("memory_capture_enabled") is False or not response_data.get("success"):
        return
    from app.utils.deployment import is_desktop_mode

    trusted_principal = runtime_context.get("_dataset_access_context_trusted") is True
    if not trusted_principal and not is_desktop_mode():
        return
    vector_owner_id = resolve_vector_memory_owner_id(user_id, runtime_context)
    if not vector_owner_id:
        return
    inner = response_data.get("data")
    inner = inner if isinstance(inner, dict) else {}
    action = str(response_data.get("action") or inner.get("action") or "").strip().lower()
    if action in _NON_MEMORY_ACTIONS:
        return
    assistant_text = _assistant_text(response_data)
    if not assistant_text or _SENSITIVE_MEMORY_RE.search(f"{message}\n{assistant_text}"):
        return
    session_id = str(
        runtime_context.get("session_id") or runtime_context.get("conversation_id") or ""
    )
    try:
        from app.application.user_memory_vector_app_service import (
            get_user_memory_vector_ingest_app_service,
        )

        service = get_user_memory_vector_ingest_app_service()
        chunk = service.build_chat_turn_chunk(
            user_id=vector_owner_id,
            user_message=message,
            assistant_message=assistant_text,
            session_id=session_id,
            source=str(source or "chat"),
        )
        service.ingest_chunks(vector_owner_id, [chunk])
    except RECOVERABLE_ERRORS as vector_error:
        logger.warning("对话向量记忆写入失败，继续提炼结构化记忆: %s", vector_error)
    access_context = runtime_context.get("_dataset_access_context")
    if trusted_principal and isinstance(access_context, dict):
        try:
            from app.application.persy_memory_app_service import get_persy_memory_app_service

            get_persy_memory_app_service().capture_conversation_turn(
                access_context=access_context,
                user_message=message,
                assistant_message=assistant_text,
                session_id=session_id,
                source=str(source or "chat"),
                scope="tenant"
                if str(runtime_context.get("persy_memory_scope") or "").strip().lower() == "tenant"
                else "user",
            )
        except RECOVERABLE_ERRORS as structured_error:
            logger.warning("结构化对话记忆提炼失败，不影响向量记忆: %s", structured_error)


def recallable_memory_prompt(
    *,
    user_id: str,
    message: str,
    context: dict[str, Any] | None,
) -> str:
    """Build best-effort active memory context for a streaming chat request."""

    runtime_context = context if isinstance(context, dict) else {}
    vector_owner_id = resolve_vector_memory_owner_id(user_id, runtime_context)
    if not vector_owner_id or not str(message or "").strip():
        return ""
    sections: list[str] = []
    try:
        from app.application.user_memory_vector_app_service import (
            get_user_memory_rag_app_service,
        )

        rag = get_user_memory_rag_app_service()
        result = rag.query(user_id=vector_owner_id, query_text=message, top_k=3)
        hits = result.get("hits") if isinstance(result, dict) else None
        if isinstance(hits, list) and hits:
            sections.append(
                rag.format_for_prompt(
                    user_id=vector_owner_id,
                    query_text=message,
                    hits=hits,
                    max_hits=3,
                )
            )
    except RECOVERABLE_ERRORS as vector_error:
        logger.warning("流式对话向量记忆召回失败（不阻断回复）: %s", vector_error)
    access_context = runtime_context.get("_dataset_access_context")
    if runtime_context.get("_dataset_access_context_trusted") is True and isinstance(
        access_context, dict
    ):
        try:
            from app.application.persy_memory_app_service import get_persy_memory_app_service

            result = get_persy_memory_app_service().query(
                access_context=access_context,
                query=message,
                top_k=4,
                reinforce=True,
            )
            memories = result.get("memories") if isinstance(result, dict) else None
            if isinstance(memories, list) and memories:
                lines = ["【Persy 已确认记忆】"]
                for row in memories[:4]:
                    if isinstance(row, dict):
                        statement = str(row.get("statement") or row.get("value") or "").strip()
                        if statement:
                            lines.append(f"- {statement}")
                if len(lines) > 1:
                    sections.append("\n".join(lines))
        except RECOVERABLE_ERRORS as structured_error:
            logger.warning("流式对话结构化记忆召回失败（不阻断回复）: %s", structured_error)
    return "\n\n".join(section for section in sections if section.strip())


__all__ = [
    "persist_recallable_chat_turn",
    "recallable_memory_prompt",
    "resolve_memory_owner_id",
    "resolve_vector_memory_owner_id",
]
