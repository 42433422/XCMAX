"""
XCAGI 前端兼容 API — 会话管理路由（历史对话列表 / 消息持久化）。
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Query

from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    normalize_active_mod_id,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)

_XCAGI_CONVERSATION_MAX_SESSIONS = 200
_conversation_lock = threading.Lock()
_xcagi_user_sessions: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}


def _xcagi_resolve_session_scope(
    user_id: Any,
    explicit_mod_id: Any = None,
) -> tuple[str, str]:
    uid = str(user_id or "default").strip() or "default"
    mod = normalize_active_mod_id(explicit_mod_id) if explicit_mod_id else ""
    if not mod:
        try:
            mod = get_request_active_mod_id() or ""
        except RECOVERABLE_ERRORS:
            mod = ""
    return (uid, mod)


def _xcagi_strip_html(text: str) -> str:
    s = str(text or "")
    return re.sub(r"<[^>]+>", "", s)


def _xcagi_iso_from_ts(ts: float) -> str:
    return (
        datetime.fromtimestamp(float(ts), tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _xcagi_ts(value: Any) -> float:
    if isinstance(value, datetime):
        current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return current.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _xcagi_normalize_chat_role(role: Any) -> str:
    r = str(role or "user").strip().lower()
    if r in ("assistant", "model"):
        return "ai"
    if r in ("user", "ai", "task"):
        return r
    return "ai"


def _xcagi_title_from_messages(msgs: list[dict]) -> str | None:
    for m in msgs:
        if m.get("role") != "user":
            continue
        t = _xcagi_strip_html(str(m.get("content") or "")).strip()
        if not t:
            continue
        return (t[:48] + "…") if len(t) > 48 else t
    return None


def _xcagi_summary_from_messages(msgs: list[dict]) -> str:
    if not msgs:
        return ""
    c = str(msgs[-1].get("content") or "")
    t = _xcagi_strip_html(c).strip().replace("\n", " ")
    if len(t) > 120:
        return t[:120] + "…"
    return t


def _xcagi_evict_oldest_session_if_needed(
    user_bucket: dict[str, dict[str, Any]], new_sid: str
) -> None:
    if new_sid in user_bucket or len(user_bucket) < _XCAGI_CONVERSATION_MAX_SESSIONS:
        return
    oldest_sid = min(
        user_bucket.keys(), key=lambda k: float(user_bucket[k].get("updated_ts") or 0.0)
    )
    user_bucket.pop(oldest_sid, None)


def _xcagi_memory_records_for_session(
    scope: tuple[str, str], session_id: str
) -> list[dict[str, Any]]:
    bucket = _xcagi_user_sessions.get(scope) or {}
    record = bucket.get(session_id)
    if record is not None or scope[1]:
        return [record] if record is not None else []
    return [
        candidate
        for key, candidate_bucket in _xcagi_user_sessions.items()
        if key[0] == scope[0]
        for candidate in [candidate_bucket.get(session_id)]
        if candidate is not None
    ]


def _xcagi_db_session(session_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Read the durable conversation store when the process-local cache is absent."""

    try:
        from app.application.facades.conversation_facade import get_conversation_service
        from app.fastapi_routes.domains.misc.helpers import _message_to_dict, _session_to_dict

        service = get_conversation_service()
        messages = [_message_to_dict(row) for row in service.get_session_messages(session_id, 500)]
        session = next(
            (
                _session_to_dict(row)
                for row in service.get_sessions(user_id=None, limit=1000)
                if _session_to_dict(row).get("session_id") == session_id
            ),
            None,
        )
        return session, messages
    except RECOVERABLE_ERRORS as exc:
        logger.warning("conversation durable fallback unavailable for %s: %s", session_id, exc)
        return None, []


def _xcagi_db_sessions(user_id: str, limit: int) -> list[dict[str, Any]]:
    try:
        from app.application.facades.conversation_facade import get_conversation_service
        from app.fastapi_routes.domains.misc.helpers import _session_to_dict

        service = get_conversation_service()
        return [
            _session_to_dict(row)
            for row in service.get_sessions(user_id=user_id, limit=max(limit, 200))
        ]
    except RECOVERABLE_ERRORS as exc:
        logger.warning("conversation durable list unavailable for %s: %s", user_id, exc)
        return []


@router.post("/conversations/message")
def conversations_save_message(body: dict = Body(default_factory=dict)) -> dict:
    from app.neuro_bus.route_event_publisher import (
        publish_simple_event,
    )

    session_id = str(body.get("session_id") or "").strip()
    role = _xcagi_normalize_chat_role(body.get("role"))
    content = str(body.get("content") or "")
    if not session_id or not content.strip():
        return {"success": True, "saved": False, "message": "empty session_id or content"}

    scope = _xcagi_resolve_session_scope(body.get("user_id"), body.get("mod_id"))
    user_id, mod_id = scope

    now = time.time()
    msg = {"role": role, "content": content, "timestamp": _xcagi_iso_from_ts(now)}

    with _conversation_lock:
        user_bucket = _xcagi_user_sessions.setdefault(scope, {})
        is_new = session_id not in user_bucket
        if is_new:
            _xcagi_evict_oldest_session_if_needed(user_bucket, session_id)
        rec = user_bucket.get(session_id)
        if rec is None:
            rec = {"messages": [], "created_ts": now, "updated_ts": now}
            user_bucket[session_id] = rec
        rec["messages"].append(msg)
        rec["updated_ts"] = now

    publish_simple_event(
        "conversation.message.saved",
        {
            "session_id": session_id,
            "user_id": user_id,
            "mod_id": mod_id,
            "role": role,
            "message_length": len(content),
            "is_new_session": is_new,
        },
        domain="conversation",
    )

    return {"success": True, "saved": True, "mod_id": mod_id}


@router.get("/conversations/sessions")
def conversations_sessions_list(
    limit: int = Query(default=50, ge=1, le=500),
    user_id: str = Query(default="default"),
    mod_id: str = Query(default=""),
) -> dict:
    scope = _xcagi_resolve_session_scope(user_id, mod_id)
    with _conversation_lock:
        user_bucket = dict(_xcagi_user_sessions.get(scope) or {})
    by_session_id: dict[str, tuple[float, dict[str, Any]]] = {}
    for durable in _xcagi_db_sessions(scope[0], int(limit)):
        sid = str(durable.get("session_id") or "").strip()
        if not sid:
            continue
        sort_ts = _xcagi_ts(durable.get("last_message_at") or durable.get("created_at"))
        by_session_id[sid] = (
            sort_ts,
            {
                **durable,
                "session_id": sid,
                "mod_id": scope[1],
            },
        )
    for sid, rec in user_bucket.items():
        msgs = list(rec.get("messages") or [])
        title = str(rec.get("title") or "").strip() or _xcagi_title_from_messages(msgs)
        uts = float(rec.get("updated_ts") or 0.0)
        by_session_id[sid] = (
            uts,
            {
                "session_id": sid,
                "title": title,
                "summary": _xcagi_summary_from_messages(msgs),
                "message_count": len(msgs),
                "mod_id": scope[1],
                "created_at": _xcagi_iso_from_ts(float(rec.get("created_ts") or 0.0)),
                "last_message_at": _xcagi_iso_from_ts(uts),
            },
        )
    rows = list(by_session_id.values())
    rows.sort(key=lambda x: x[0], reverse=True)
    return {
        "success": True,
        "mod_id": scope[1],
        "sessions": [r[1] for r in rows[: int(limit)]],
    }


@router.post("/conversations/sessions/clear")
def conversations_sessions_clear(body: dict = Body(default_factory=dict)) -> dict:
    payload = body or {}
    scope = _xcagi_resolve_session_scope(payload.get("user_id"), payload.get("mod_id"))
    clear_all_mods = bool(payload.get("all_mods") or payload.get("all"))
    with _conversation_lock:
        if clear_all_mods:
            target_scopes = [key for key in list(_xcagi_user_sessions.keys()) if key[0] == scope[0]]
            deleted = 0
            for key in target_scopes:
                removed = _xcagi_user_sessions.pop(key, None)
                if isinstance(removed, dict):
                    deleted += len(removed)
        else:
            removed = _xcagi_user_sessions.pop(scope, None)
            deleted = len(removed) if isinstance(removed, dict) else 0
    durable_deleted = 0
    try:
        from app.application.facades.conversation_facade import get_conversation_service

        durable_deleted = int(get_conversation_service().delete_sessions(scope[0]) or 0)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("conversation durable clear unavailable for %s: %s", scope[0], exc)
    return {
        "success": True,
        "deleted": max(deleted, durable_deleted),
        "mod_id": scope[1],
        "all_mods": clear_all_mods,
        "message": "ok",
    }


@router.post("/ai/conversation/new")
def ai_conversation_new(body: dict = Body(default_factory=dict)) -> dict:
    sid = str(body.get("session_id") or "").strip() or uuid.uuid4().hex
    return {"success": True, "data": {"session_id": sid}}


@router.get("/conversations/{conversation_id}")
def conversations_get(
    conversation_id: str,
    user_id: str = Query(default="default"),
    mod_id: str = Query(default=""),
) -> dict:
    cid = (conversation_id or "").strip()
    scope = _xcagi_resolve_session_scope(user_id, mod_id)
    with _conversation_lock:
        rec = (_xcagi_user_sessions.get(scope) or {}).get(cid)
        if rec is None and not scope[1]:
            for key, bucket in _xcagi_user_sessions.items():
                if key[0] != scope[0]:
                    continue
                if cid in bucket:
                    rec = bucket[cid]
                    break
        msgs = [dict(m) for m in list((rec or {}).get("messages") or [])]
        title = str((rec or {}).get("title") or "").strip() or (
            _xcagi_title_from_messages(msgs) if rec else None
        )
    if rec is None:
        durable_session, durable_messages = _xcagi_db_session(cid)
        if durable_session is not None or durable_messages:
            msgs = durable_messages
            durable_title = str((durable_session or {}).get("title") or "").strip()
            title = (
                durable_title
                if durable_title and durable_title != "新会话"
                else _xcagi_title_from_messages(msgs)
            )
    return {
        "success": True,
        "id": cid,
        "title": title,
        "mod_id": scope[1],
        "messages": msgs,
        "metadata": {},
    }


@router.put("/conversations/{conversation_id}/title")
def conversations_title_put(
    conversation_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Query(default="default"),
    mod_id: str = Query(default=""),
) -> dict:
    cid = str(conversation_id or "").strip()
    title = str((body or {}).get("title") or "").strip()
    scope = _xcagi_resolve_session_scope(user_id, mod_id)
    memory_updated = False
    with _conversation_lock:
        for record in _xcagi_memory_records_for_session(scope, cid):
            record["title"] = title
            record["updated_ts"] = time.time()
            memory_updated = True

    durable_updated = False
    try:
        from app.application.facades.conversation_facade import get_conversation_service

        durable_updated = bool(get_conversation_service().update_session_title(cid, title))
    except RECOVERABLE_ERRORS as exc:
        logger.warning("conversation title durable update unavailable for %s: %s", cid, exc)
    return {"success": memory_updated or durable_updated, "title": title}


@router.delete("/conversations/{conversation_id}")
def conversations_delete(
    conversation_id: str,
    user_id: str = Query(default="default"),
    mod_id: str = Query(default=""),
) -> dict:
    cid = str(conversation_id or "").strip()
    scope = _xcagi_resolve_session_scope(user_id, mod_id)
    memory_deleted = False
    with _conversation_lock:
        target_scopes = [scope]
        if not scope[1]:
            target_scopes = [key for key in _xcagi_user_sessions if key[0] == scope[0]]
        for key in target_scopes:
            bucket = _xcagi_user_sessions.get(key)
            if bucket is not None and bucket.pop(cid, None) is not None:
                memory_deleted = True

    durable_deleted = False
    try:
        from app.application.facades.conversation_facade import get_conversation_service

        durable_deleted = bool(get_conversation_service().delete_session(cid))
    except RECOVERABLE_ERRORS as exc:
        logger.warning("conversation durable delete unavailable for %s: %s", cid, exc)
    return {"success": memory_deleted or durable_deleted}
