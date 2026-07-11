"""移动端推送应用层（审批等路由调用）。"""

from __future__ import annotations

from typing import Any


def notify_mobile_user(
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    *,
    audience: str = "enterprise",
    tenant_id: int | None = None,
) -> dict[str, bool]:
    from app.services.mobile_push import notify_user

    return notify_user(
        user_id,
        title=title,
        body=body,
        data=data,
        audience=audience,
        tenant_id=tenant_id,
    )


def ensure_mobile_notification_schema(db: Any) -> None:
    from app.services.mobile_push import ensure_mobile_notification_schema as ensure_schema

    ensure_schema(db)


def notification_scope_for_user(user: Any) -> tuple[str, int]:
    from app.services.mobile_push import notification_scope_for_user as resolve_scope

    return resolve_scope(user)
