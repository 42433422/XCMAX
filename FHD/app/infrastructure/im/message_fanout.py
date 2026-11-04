"""IM 新消息的 WebSocket 实时扇出（网页端与手机端发消息接口共用）。

网页端 ``POST /api/im/conversations/{id}/messages`` 与手机端
``POST /api/mobile/v1/im/conversations/{id}/messages`` 落库后都走这里，
保证对方无论从哪端发消息都能实时收到同一组事件：
legacy ``message`` + 同步语义 ``im.message``。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_im_message_payloads(
    conversation_id: int, result: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 ``(legacy_payload, sync_payload)``，字段与历史网页端推送完全一致。"""
    legacy_payload = {
        "type": "message",
        "conversation_id": conversation_id,
        "message": result["message"],
    }
    sync_payload = {
        "type": "im.message",
        "conversation_id": conversation_id,
        "message": result["message"],
        "updated_at_ms": result.get("updated_at_ms"),
    }
    return legacy_payload, sync_payload


def im_message_member_ids(result: dict[str, Any]) -> list[int]:
    return [int(mid) for mid in (result.get("member_user_ids") or [])]


async def push_im_message_to_members(
    sender_id: int,
    conversation_id: int,
    result: dict[str, Any],
    *,
    hub: Any = None,
) -> list[int]:
    """把新消息推给会话中除发送者外的所有在线成员；返回会话成员 id 列表。"""
    if hub is None:
        from app.infrastructure.im.ws_hub import im_ws_hub as hub
    legacy_payload, sync_payload = build_im_message_payloads(conversation_id, result)
    member_ids = im_message_member_ids(result)
    for member_id in member_ids:
        if member_id != sender_id:
            await hub.send_to_user(member_id, legacy_payload)
            await hub.send_to_user(member_id, sync_payload)
    return member_ids
