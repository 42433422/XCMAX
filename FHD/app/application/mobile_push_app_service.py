"""移动端推送应用层（审批等路由调用）。"""

from __future__ import annotations

from typing import Any

from app.services.mobile_push import notify_user


def notify_mobile_user(
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> dict[str, bool]:
    return notify_user(user_id, title, body, data)
