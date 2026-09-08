"""微信联系人情报注入 AI 对话（服务器=AI 第一载体，聊天智慧进 prompt）。

数据来源：微信同步基建（本机 → /api/ops/wechat/ingest → wechat_contacts / wechat_messages）。
解析策略：
1. 显式指定：请求 context 携带 ``wechat_contact_key`` 时直接取该联系人；
2. 自动匹配：消息文本中出现已同步联系人的 display_name（最长优先）时取该联系人。

输出为紧凑情报 payload（身份绑定 + 客户档案 + 最近消息），由
``PromptsMixin._format_wechat_contact_block`` 渲染进 system prompt。
任何失败都静默降级为 None —— 情报注入绝不阻断聊天主链路。
"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

_MESSAGE_LIMIT = 12
_CONTENT_CAP = 300


def _trim_messages(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in (rows or [])[-_MESSAGE_LIMIT:]:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if len(content) > _CONTENT_CAP:
            content = content[:_CONTENT_CAP] + "…"
        out.append(
            {
                "role": str(row.get("role") or "other"),
                "content": content,
                "msg_ts": str(row.get("msg_ts") or ""),
            }
        )
    return out


def resolve_wechat_chat_context(
    message: str, context: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """为一次聊天解析微信联系人情报；无命中/异常返回 None。"""
    try:
        from app.application.wechat_ingest_service import (
            build_contact_context,
            list_wechat_contacts,
        )

        ctx = context if isinstance(context, dict) else {}
        tenant_raw = ctx.get("tenant_id")
        try:
            tenant_id = int(tenant_raw) if tenant_raw not in (None, "") else None
        except (TypeError, ValueError):
            tenant_id = None

        contact_key = str(ctx.get("wechat_contact_key") or "").strip()
        matched_by = "explicit"
        if not contact_key:
            listing = list_wechat_contacts(tenant_id=tenant_id, limit=500)
            raw_items = listing.get("items")
            items = raw_items if isinstance(raw_items, list) else []
            text = str(message or "")
            best_name = ""
            best_key = ""
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("display_name") or "").strip()
                key = str(item.get("contact_key") or "").strip()
                # 名字太短容易误命中（单字姓氏）；要求 >=2 且真实出现在消息里
                if len(name) < 2 or name not in text:
                    continue
                if len(name) > len(best_name):
                    best_name, best_key = name, key
            if not best_key:
                return None
            contact_key, matched_by = best_key, "auto_match"

        payload = build_contact_context(
            contact_key, tenant_id=tenant_id, limit=_MESSAGE_LIMIT, include_messages=True
        )
        if not payload.get("success") or not payload.get("known"):
            return None
        return {
            "contact_key": contact_key,
            "matched_by": matched_by,
            "contact": payload.get("contact") or {},
            "customer": payload.get("customer"),
            "recent_messages": _trim_messages(payload.get("recent_messages")),
            "message_count": int(payload.get("message_count") or 0),
        }
    except BOUNDARY_ERRORS:  # 情报注入必须绝不阻断聊天（插件隔离边界）
        logger.warning("wechat chat context resolve failed", exc_info=True)
        return None
