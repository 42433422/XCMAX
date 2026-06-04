"""库存相关 Facade（已废弃）：请使用各域 ``get_*_app_service()``。"""

from __future__ import annotations

import warnings

from app.application.inventory_app_service import get_inventory_app_service
from app.application.purchase_app_service import get_purchase_app_service
from app.application.report_app_service import get_report_app_service
from app.infrastructure.gateways.inventory import InventoryService as _InventoryService

warnings.warn(
    "inventory_facade 已废弃；请使用 get_inventory_app_service / get_purchase_app_service / get_report_app_service",
    DeprecationWarning,
    stacklevel=2,
)


class _AppServiceCallable:
    """兼容 ``ServiceClass()`` 旧写法，实例即应用服务单例。"""

    def __init__(self, getter):
        self._getter = getter

    def __call__(self):
        return self._getter()


PurchaseService = _AppServiceCallable(get_purchase_app_service)
ReportService = _AppServiceCallable(get_report_app_service)
# 历史测试 patch 仍指向 services 层实现类名
InventoryService = _InventoryService

__all__ = [
    "InventoryService",
    "PurchaseService",
    "ReportService",
    "get_inventory_app_service",
]
