"""Shipment bounded-context ports (canonical). New contracts land here."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.domain.shipment.aggregates import Shipment


class ShipmentDocumentGeneratorPort(ABC):
    """发货单文档生成端口（Port）。

    application 只依赖这个抽象，不依赖 legacy 模板实现、文件系统路径等细节。
    """

    @abstractmethod
    def generate(
        self,
        *,
        unit_name: str,
        products: list[dict[str, Any]],
        date: str | None = None,
        template_name: str | None = None,
        order_number: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

class ShipmentRecordCommandPort(ABC):
    """shipment_records 写操作端口（Command side）。"""

    @abstractmethod
    def clear_all(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def clear_by_unit(self, purchase_unit: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_record(
        self,
        record_id: int,
        *,
        unit_name: str | None = None,
        date: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_record(self, record_id: int) -> dict[str, Any]:
        raise NotImplementedError

class ShipmentRecordQueryPort(ABC):
    """出货记录查询端口（Read side）。"""

    @abstractmethod
    def query_shipments(
        self,
        *,
        unit_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """
        返回与历史接口尽量一致的结构：
        {
          "success": bool,
          "data": List[Dict[str, Any]],
          "total": int,
          "page": int,
          "per_page": int
        }
        """
        raise NotImplementedError

    @abstractmethod
    def search_shipments(self, query: str) -> list[dict[str, Any]]:
        """在 shipment_records 中模糊搜索（purchase_unit/product_name/model_number）。"""
        raise NotImplementedError

    @abstractmethod
    def get_shipment_by_id(self, order_id: str) -> dict[str, Any] | None:
        """根据 shipment_records.id 查询单条记录（用于 GET /orders/<order_number>）。"""
        raise NotImplementedError

    @abstractmethod
    def get_latest_shipments(self, limit: int) -> list[dict[str, Any]]:
        """获取最近创建的 shipment_records（用于 GET /orders/latest）。"""
        raise NotImplementedError

    @abstractmethod
    def get_shipment_records(
        self,
        unit_name: str | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取 shipment_records 列表（用于后台管理接口）。"""
        raise NotImplementedError

class ShipmentRecordStorePort(ABC):
    """出货记录写入端口（Port）。

    目标：统一所有写入都以 purchase_units 的规范单位名/ID 为准。
    """

    @abstractmethod
    def record_document_generation(
        self,
        *,
        unit_name: str,
        unit_id: int | None,
        products: list[dict[str, Any]],
        document_result: dict[str, Any],
        raw_text: str = "",
    ) -> dict[str, Any]:
        """记录一次发货单生成对应的出货记录。"""
        raise NotImplementedError

class ShipmentRepository(ABC):
    """发货单仓储接口 (Port)。"""

    @abstractmethod
    def save(self, shipment: Shipment) -> Shipment:
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, shipment_id: int) -> Shipment | None:
        raise NotImplementedError

    @abstractmethod
    def find_by_order_number(self, order_number: str) -> Shipment | None:
        raise NotImplementedError

    @abstractmethod
    def find_all(self, page: int = 1, per_page: int = 20) -> list[Shipment]:
        raise NotImplementedError

    @abstractmethod
    def find_by_unit(self, unit_name: str) -> list[Shipment]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, shipment_id: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

class PurchaseUnitQueryPort(ABC):
    """购买单位只读查询端口（用于后台管理/下拉列表）。"""

    @abstractmethod
    def list_purchase_units(self) -> list[str]:
        raise NotImplementedError
