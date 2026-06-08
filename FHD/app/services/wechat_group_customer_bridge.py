"""微信群 ↔ 市场用户绑定与星标摘要（桌面开发栈最小实现）。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def list_group_contacts(
    keyword: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """管理端微信群列表；未配置解密库时返回空列表。"""
    _ = keyword
    _ = limit
    return []


def get_bindings_for_user(user_id: int) -> list[dict[str, Any]]:
    _ = user_id
    return []


def save_bindings_for_user(user_id: int, contact_ids: list[Any]) -> dict[str, Any]:
    _ = user_id
    ids = [int(x) for x in contact_ids if str(x).strip().isdigit()]
    return {"success": True, "data": {"contact_ids": ids}}


def build_starred_group_feed(
    limit: int = 10,
    market_user_id: int | None = None,
) -> list[dict[str, Any]]:
    _ = limit
    _ = market_user_id
    return []


def sync_group_messages(
    market_user_id: int | None = None,
    group_limit: int = 30,
    message_limit: int = 80,
    force_refresh: bool = False,
) -> dict[str, Any]:
    _ = market_user_id
    _ = group_limit
    _ = message_limit
    _ = force_refresh
    return {
        "success": True,
        "synced": 0,
        "failed": 0,
        "message": "微信解密库未配置，跳过群消息同步",
    }


def sync_bound_groups_from_live_wechat(
    market_user_id: int,
    message_limit: int = 80,
    mode: str = "feed",
) -> dict[str, Any]:
    _ = market_user_id
    _ = message_limit
    _ = mode
    return {"success": True, "synced": 0}


def _latest_context_message(messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not messages:
        return None
    best: dict[str, Any] | None = None
    best_ts = -1.0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        ts = msg.get("timestamp") or msg.get("created_at") or 0
        try:
            val = float(ts)
        except (TypeError, ValueError):
            val = 0.0
        if val >= best_ts:
            best_ts = val
            best = msg
    return best
