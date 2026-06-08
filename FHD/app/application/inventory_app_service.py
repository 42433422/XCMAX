"""库存 HTTP 应用服务 — 委托 InventoryService facade（读路径）；写路径可逐步切 v2 事件驱动。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.facades.inventory_facade import InventoryService


class InventoryAppService:
    def __init__(self) -> None:
        self._facade = InventoryService()

    def get_inventory(self, **kwargs: Any) -> dict:
        return self._facade.get_inventory(**kwargs)

    def get_inventory_summary(self, warehouse_id: int | None = None) -> dict:
        return self._facade.get_inventory_summary(warehouse_id=warehouse_id)

    def get_inventory_transactions(self, **kwargs: Any) -> dict:
        return self._facade.get_inventory_transactions(**kwargs)

    def get_inventory_alert(self) -> dict:
        return self._facade.get_inventory_alert()

    def get_combined_alert(self, threshold: float | None = None) -> dict:
        inv_result = self.get_inventory_alert()
        inv_items = inv_result.get("data") or inv_result.get("alerts") or []
        mat_items: list = []
        try:
            from app.application import get_material_application_service

            mat_result = get_material_application_service().get_low_stock_materials(threshold=threshold)
            mat_items = mat_result.get("data") or []
        except Exception:
            pass
        return {
            "success": True,
            "inventory_alerts": inv_items,
            "material_low_stock": mat_items,
            "total_alerts": len(inv_items) + len(mat_items),
        }

    def get_storage_locations(self, **kwargs: Any) -> dict:
        return self._facade.get_storage_locations(**kwargs)

    def create_storage_location(self, body: dict) -> dict:
        return self._facade.create_storage_location(body)

    def update_storage_location(self, location_id: int, body: dict) -> dict:
        return self._facade.update_storage_location(location_id, body)

    def get_warehouses(self, status: str | None = None) -> dict:
        return self._facade.get_warehouses(status=status)

    def get_warehouse(self, warehouse_id: int) -> dict:
        return self._facade.get_warehouse(warehouse_id)

    def create_warehouse(self, body: dict) -> dict:
        return self._facade.create_warehouse(body)

    def update_warehouse(self, warehouse_id: int, body: dict) -> dict:
        return self._facade.update_warehouse(warehouse_id, body)

    def delete_warehouse(self, warehouse_id: int) -> dict:
        return self._facade.delete_warehouse(warehouse_id)

    def inventory_in(self, **kwargs: Any) -> dict:
        return self._facade.inventory_in(**kwargs)

    def inventory_out(self, **kwargs: Any) -> dict:
        return self._facade.inventory_out(**kwargs)

    def inventory_transfer(self, **kwargs: Any) -> dict:
        return self._facade.inventory_transfer(**kwargs)

    @staticmethod
    def parse_optional_datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None
