"""Application facade for WeChat group customer bindings."""

from __future__ import annotations

from typing import Any


def list_group_contacts(*, keyword: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    from app.services.wechat_group_customer_bridge import list_group_contacts as _list

    return _list(keyword=keyword, limit=limit)


def get_bindings_for_user(user_id: int) -> list[dict[str, Any]]:
    from app.services.wechat_group_customer_bridge import get_bindings_for_user as _get

    return _get(user_id)


def save_bindings_for_user(user_id: int, contact_ids: list[Any]) -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import save_bindings_for_user as _save

    return _save(user_id, contact_ids)
