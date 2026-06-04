"""
采购应用服务 V2 — 事件驱动版本

来源：原采购逻辑散落于 app/services/purchase_service.py + legacy_inventory 路由。
本 V2 层在 PurchaseService 之上增加 NeuroBus 事件发布，保持与 Neuro-DDD 架构一致。

消失条件：采购领域完成 DDD 重构（引入 app/domain/purchase/ 聚合根）后，
本模块升级为正式的 PurchaseApplicationService，不再依赖 services 层。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.neuro_commands._base import NeuroCommandServiceBase


class PurchaseAppServiceV2(NeuroCommandServiceBase):
    """采购应用服务 V2

    查询类方法：直接委托 PurchaseService（同步，立即返回数据）。
    写操作方法：执行写操作后向 NeuroBus 发布业务事件，供下游处理器消费。
    """

    correlation_prefix = "purchase"
    event_source = "purchase_app_service_v2"

    def __init__(self) -> None:
        super().__init__()
        self._svc = None  # 懒加载，避免循环导入

    def _purchase_svc(self):
        if self._svc is None:
            from app.infrastructure.gateways.purchase_legacy import PurchaseService

            self._svc = PurchaseService()
        return self._svc

    # ── 供应商 ────────────────────────────────────────────────────

    def get_suppliers(
        self, status: str | None = None, keyword: str | None = None
    ) -> dict[str, Any]:
        return self._purchase_svc().get_suppliers(status=status, keyword=keyword)

    def get_supplier(self, supplier_id: int) -> dict[str, Any]:
        return self._purchase_svc().get_supplier(supplier_id)

    def get_supplier_summary(self) -> dict[str, Any]:
        return self._purchase_svc().get_supplier_summary()

    def create_supplier(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._purchase_svc().create_supplier(data)
        if result.get("success"):
            self._try_publish("purchase.supplier.created", {"supplier": result.get("data", {})})
        return result

    def update_supplier(self, supplier_id: int, data: dict[str, Any]) -> dict[str, Any]:
        result = self._purchase_svc().update_supplier(supplier_id, data)
        if result.get("success"):
            self._try_publish(
                "purchase.supplier.updated", {"supplier_id": supplier_id, "changes": data}
            )
        return result

    def delete_supplier(self, supplier_id: int) -> dict[str, Any]:
        result = self._purchase_svc().delete_supplier(supplier_id)
        if result.get("success"):
            self._try_publish("purchase.supplier.deleted", {"supplier_id": supplier_id})
        return result

    # ── 采购订单 ──────────────────────────────────────────────────

    def get_purchase_orders(
        self,
        supplier_id: int | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        return self._purchase_svc().get_purchase_orders(
            supplier_id=supplier_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )

    def get_purchase_order(self, order_id: int) -> dict[str, Any]:
        return self._purchase_svc().get_purchase_order(order_id)

    def create_purchase_order(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._purchase_svc().create_purchase_order(data)
        if result.get("success"):
            self._try_publish(
                "purchase.order.created",
                {"order_id": result.get("data", {}).get("id"), "data": data},
            )
        return result

    def update_purchase_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        result = self._purchase_svc().update_purchase_order(order_id, data)
        if result.get("success"):
            self._try_publish("purchase.order.updated", {"order_id": order_id, "changes": data})
        return result

    def approve_purchase_order(self, order_id: int, approver: str = "system") -> dict[str, Any]:
        result = self._purchase_svc().approve_purchase_order(order_id, approver)
        if result.get("success"):
            self._try_publish(
                "purchase.order.approved", {"order_id": order_id, "approver": approver}
            )
        return result

    def cancel_purchase_order(self, order_id: int) -> dict[str, Any]:
        result = self._purchase_svc().cancel_purchase_order(order_id)
        if result.get("success"):
            self._try_publish("purchase.order.cancelled", {"order_id": order_id})
        return result

    # ── 采购入库 ──────────────────────────────────────────────────

    def get_purchase_inbounds(
        self,
        supplier_id: int | None = None,
        order_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        return self._purchase_svc().get_purchase_inbounds(
            supplier_id=supplier_id,
            order_id=order_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )

    def create_purchase_inbound(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._purchase_svc().create_purchase_inbound(data)
        if result.get("success"):
            self._try_publish(
                "purchase.inbound.created",
                {"inbound_id": result.get("data", {}).get("id"), "data": data},
            )
        return result

    # ── 汇总 ──────────────────────────────────────────────────────

    def get_purchase_summary(self) -> dict[str, Any]:
        return self._purchase_svc().get_purchase_summary()


_purchase_app_service_v2: PurchaseAppServiceV2 | None = None


def get_purchase_app_service_v2() -> PurchaseAppServiceV2:
    global _purchase_app_service_v2
    if _purchase_app_service_v2 is None:
        _purchase_app_service_v2 = PurchaseAppServiceV2()
    return _purchase_app_service_v2
