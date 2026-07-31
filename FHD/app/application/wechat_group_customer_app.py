"""Application facade for WeChat group customer bindings."""

from __future__ import annotations

from typing import Any


def build_starred_group_feed(
    limit: int = 10,
    market_user_id: int | None = None,
) -> list[dict[str, Any]]:
    from app.services.wechat_group_customer_bridge import build_starred_group_feed as _build

    return _build(limit=limit, market_user_id=market_user_id)


def sync_group_messages(
    *,
    market_user_id: int | None = None,
    group_limit: int = 30,
    message_limit: int = 80,
    force_refresh: bool = False,
) -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import sync_group_messages as _sync

    return _sync(
        market_user_id=market_user_id,
        group_limit=group_limit,
        message_limit=message_limit,
        force_refresh=force_refresh,
    )


def sync_bound_groups_from_live_wechat(
    market_user_id: int,
    message_limit: int = 80,
    mode: str = "feed",
) -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import (
        sync_bound_groups_from_live_wechat as _sync_bound,
    )

    return _sync_bound(
        market_user_id=market_user_id,
        message_limit=message_limit,
        mode=mode,
    )


def latest_context_message(messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    from app.services.wechat_group_customer_bridge import _latest_context_message as _latest

    return _latest(messages)


def list_group_contacts(*, keyword: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    from app.services.wechat_group_customer_bridge import list_group_contacts as _list

    return _list(keyword=keyword, limit=limit)


def get_bindings_for_user(user_id: int) -> list[dict[str, Any]]:
    from app.services.wechat_group_customer_bridge import get_bindings_for_user as _get

    return _get(user_id)


def save_bindings_for_user(user_id: int, contact_ids: list[Any]) -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import save_bindings_for_user as _save

    return _save(user_id, contact_ids)


__all__ = [
    "build_starred_group_feed",
    "sync_group_messages",
    "sync_bound_groups_from_live_wechat",
    "latest_context_message",
    "list_group_contacts",
    "get_bindings_for_user",
    "save_bindings_for_user",
]
