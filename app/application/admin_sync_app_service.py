"""管理端同步 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import cs_operations as cs

_admin_sync_app_service: AdminSyncApplicationService | None = None


class AdminSyncApplicationService:
    def list_sync_conflicts(self, *args: Any, **kwargs: Any) -> Any:
        return cs.list_sync_conflicts(*args, **kwargs)

    def fetch_inbox_row(self, *args: Any, **kwargs: Any) -> Any:
        return cs.fetch_inbox_row(*args, **kwargs)

    def mark_inbox_skipped(self, *args: Any, **kwargs: Any) -> Any:
        return cs.mark_inbox_skipped(*args, **kwargs)


def get_admin_sync_app_service() -> AdminSyncApplicationService:
    global _admin_sync_app_service
    if _admin_sync_app_service is None:
        _admin_sync_app_service = AdminSyncApplicationService()
    return _admin_sync_app_service
