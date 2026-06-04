"""Inventory persistence port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class InventoryRepository(ABC):
    @abstractmethod
    def get_warehouses(self, db: Any, *, status: str | None = None) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def get_warehouse(self, db: Any, warehouse_id: int) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    def get_inventory_ledger(
        self,
        db: Any,
        *,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_no: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Any], int]:
        raise NotImplementedError
