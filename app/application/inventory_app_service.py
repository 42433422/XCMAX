"""库存 V1 应用服务：HTTP / planner 唯一入口。"""

from __future__ import annotations

from typing import Any

_inventory_app_service: "InventoryApplicationService | None" = None


class InventoryApplicationService:
    """编排库存用例；实现委托 ``InventoryService``（迁移期）。"""

    def __init__(self) -> None:
        from app.infrastructure.gateways.inventory import InventoryService

        self._inner = InventoryService()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def get_inventory_app_service() -> InventoryApplicationService:
    global _inventory_app_service
    if _inventory_app_service is None:
        _inventory_app_service = InventoryApplicationService()
    return _inventory_app_service
