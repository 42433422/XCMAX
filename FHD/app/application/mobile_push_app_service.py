"""移动端推送应用层（审批等路由调用）。"""

from __future__ import annotations

from typing import Any


def notify_mobile_user(
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> dict[str, bool]:
    from app.services.mobile_push import notify_user

    return notify_user(user_id, title=title, body=body, data=data)
