"""移动端推送 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways.mobile import notify_user


class MobilePushApplicationService:
    def notify_user(self, *args: Any, **kwargs: Any) -> Any:
        return notify_user(*args, **kwargs)


def get_mobile_push_app_service() -> MobilePushApplicationService:
    return MobilePushApplicationService()


def notify_mobile_user(*args: Any, **kwargs: Any) -> Any:
    """兼容 approval 路由等历史调用方。"""
    return notify_user(*args, **kwargs)
