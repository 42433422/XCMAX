"""移动端 API 扩展 — 客服相关纯计算辅助函数。"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_user_id(user: Any) -> int:
    try:
        raw = getattr(user, "id", None)
        return int(raw or 0)
    except (AttributeError, TypeError, ValueError):
        pass
    raw = getattr(user, "__dict__", {}).get("id")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    try:
        from sqlalchemy import inspect as sa_inspect

        identity = sa_inspect(user).identity or ()
        return int(identity[0]) if identity else 0
    except Exception:  # noqa: BLE001
        return 0


def _safe_user_text(user: Any, key: str) -> str:
    try:
        return str(getattr(user, key, "") or "").strip()
    except (AttributeError, TypeError):
        return str(getattr(user, "__dict__", {}).get(key) or "").strip()


def _mobile_cs_source_id(user: Any) -> str:
    uid = _safe_user_id(user)
    return f"mobile:{uid or 'anonymous'}"


def _mobile_cs_source_name(user: Any) -> str:
    display = (
        _safe_user_text(user, "display_name") or _safe_user_text(user, "username") or "移动端用户"
    )
    return f"手机端 {display}"


def _coerce_user_cs_reply(result: dict[str, Any], fallback: str) -> str:
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        error = str(data.get("error") or "").strip()
        if data.get("ok") is False or error:
            logger.info("user-cs employee returned non-fatal error for mobile cs: %s", error[:200])
            return fallback
        items = data.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                for key in ("message_text", "reply", "answer", "summary"):
                    val = str(first.get(key) or "").strip()
                    if val:
                        return val
            elif isinstance(first, str) and first.strip():
                return first.strip()
        summary = str(data.get("summary") or "").strip()
        if summary:
            return summary
    error = str((result or {}).get("error") or "").strip() if isinstance(result, dict) else ""
    if error:
        logger.info("user-cs employee failed for mobile cs: %s", error[:200])
    return fallback


def _service_request_to_cs_messages(row: Any) -> list[dict[str, Any]]:
    created = row.created_at.isoformat() if getattr(row, "created_at", None) else ""
    updated = row.updated_at.isoformat() if getattr(row, "updated_at", None) else created
    messages = [
        {
            "message_id": f"sr_{row.id}_user",
            "sender": "user",
            "body": row.description or row.title or "",
            "timestamp": created,
            "msg_type": "text",
        }
    ]
    extra: dict[str, Any] = {}
    if row.extra_data:
        try:
            raw = json.loads(row.extra_data)
            if isinstance(raw, dict):
                extra = raw
        except (TypeError, json.JSONDecodeError):
            extra = {}
    reply = str(extra.get("ai_reply") or row.response or "").strip()
    if reply:
        messages.append(
            {
                "message_id": f"sr_{row.id}_cs",
                "sender": "cs",
                "body": reply,
                "timestamp": updated,
                "msg_type": "text",
            }
        )
    return messages
