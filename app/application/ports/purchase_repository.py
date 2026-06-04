"""Purchase persistence port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class PurchaseRepository(ABC):
    @abstractmethod
    def get_suppliers(
        self, db: Any, *, status: str | None = None, keyword: str | None = None
    ) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def get_supplier(self, db: Any, supplier_id: int) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    def get_purchase_orders(
        self,
        db: Any,
        *,
        supplier_id: int | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Any], int]:
        raise NotImplementedError
