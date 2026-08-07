"""MRP 生产制造服务模块

提供 BOM 管理、生产工单下达、领料、完工入库等业务逻辑。
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.db.models import InventoryLedger
from app.db.models.mrp import Bom, BomLine, ManufacturingOrder, ManufacturingOrderLine
from app.db.session import get_db
from app.services.inventory_service import InventoryService
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ManufacturingService:
    """MRP 生产制造服务类"""

    def __init__(self) -> None:
        self.inventory_service = InventoryService()

    @staticmethod
    def _decimal_to_float(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        return value

    # ------------------------------------------------------------------
    # BOM 管理
    # ------------------------------------------------------------------
    def create_bom(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建 BOM 及多条 BomLine。"""
        with get_db() as db:
            try:
                bom = Bom(
                    code=data.get("code"),
                    product_id=data.get("product_id"),
                    product_name=data.get("product_name"),
                    quantity=data.get("quantity", 1),
                    status=data.get("status", "active"),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                for line in data.get("lines", []):
                    bom.lines.append(
                        BomLine(
                            product_id=line.get("product_id"),
                            product_name=line.get("product_name"),
                            quantity=self._decimal_to_float(line.get("quantity", 0)),
                            unit=line.get("unit", "个"),
                        )
                    )
                db.add(bom)
                db.commit()
                db.refresh(bom)
                return {"success": True, "data": bom.to_dict()}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("创建 BOM 失败: %s", e)
                return {"success": False, "message": str(e)}

    def query_boms(
        self,
        status: str | None = None,
        product_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(Bom)
            if status:
                query = query.filter(Bom.status == status)
            if product_id:
                query = query.filter(Bom.product_id == product_id)
            total = query.count()
            items = (
                query.order_by(Bom.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            return {
                "success": True,
                "data": [bom.to_dict() for bom in items],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    def get_bom(self, bom_id: int) -> dict[str, Any]:
        with get_db() as db:
            bom = db.query(Bom).filter(Bom.id == bom_id).first()
            if not bom:
                return {"success": False, "message": "BOM 不存在"}
            return {"success": True, "data": bom.to_dict()}

    # ------------------------------------------------------------------
    # 生产工单
    # ------------------------------------------------------------------
    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        """按 bom_id/quantity 生成生产工单，并根据 BOM 展开生成工单用料行。"""
        with get_db() as db:
            try:
                bom = db.query(Bom).filter(Bom.id == data.get("bom_id")).first()
                if not bom:
                    return {"success": False, "message": "BOM 不存在"}

                quantity = int(data.get("quantity", 1))
                order_no = data.get("order_no") or f"MO-{datetime.now().strftime('%Y%m%d%H%M%S')}"

                order = ManufacturingOrder(
                    order_no=order_no,
                    bom_id=bom.id,
                    product_id=bom.product_id,
                    product_name=bom.product_name,
                    quantity=quantity,
                    warehouse_id=data.get("warehouse_id"),
                    status="draft",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(order)
                db.flush()

                for line in bom.lines:
                    db.add(
                        ManufacturingOrderLine(
                            order_id=order.id,
                            product_id=line.product_id,
                            product_name=line.product_name,
                            quantity=float(line.quantity or 0) * quantity,
                            consumed_quantity=0,
                            unit=line.unit,
                        )
                    )
                db.commit()
                db.refresh(order)
                return {"success": True, "data": order.to_dict()}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("创建生产工单失败: %s", e)
                return {"success": False, "message": str(e)}

    def confirm_order(self, order_id: int) -> dict[str, Any]:
        """工单下达：draft → confirmed。"""
        with get_db() as db:
            try:
                order = db.query(ManufacturingOrder).filter(ManufacturingOrder.id == order_id).first()
                if not order:
                    return {"success": False, "message": "工单不存在"}
                if order.status != "draft":
                    return {"success": False, "message": f"工单状态 {order.status} 不可下达"}
                order.status = "confirmed"
                order.updated_at = datetime.now()
                db.commit()
                db.refresh(order)
                return {"success": True, "message": "工单已下达", "data": order.to_dict()}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("下达工单失败: %s", e)
                return {"success": False, "message": str(e)}

    def consume(self, order_id: int, warehouse_id: int, operator: str | None = None) -> dict[str, Any]:
        """领料：校验原料库存，足够则扣减原料并更新已领料量，工单 → in_progress。"""
        # Phase 1: 校验工单状态与原料库存
        with get_db() as db:
            order = db.query(ManufacturingOrder).filter(ManufacturingOrder.id == order_id).first()
            if not order:
                return {"success": False, "message": "工单不存在"}
            if order.status != "confirmed":
                return {"success": False, "message": f"工单状态 {order.status} 不可领料"}

            lines_data = [
                (line.id, line.product_id, line.product_name, float(line.quantity or 0))
                for line in order.lines
            ]
            for _line_id, product_id, product_name, qty in lines_data:
                ledger = (
                    db.query(InventoryLedger)
                    .filter(
                        InventoryLedger.product_id == product_id,
                        InventoryLedger.warehouse_id == warehouse_id,
                        InventoryLedger.available_quantity >= qty,
                    )
                    .first()
                )
                if not ledger:
                    return {
                        "success": False,
                        "message": f"原料 {product_name}（id={product_id}）库存不足或不存在",
                    }

        # Phase 2: 逐项调用库存出库扣减原料
        for line_id, product_id, _product_name, qty in lines_data:
            result = self.inventory_service.inventory_out(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=qty,
                reference_type="manufacturing",
                reference_id=order_id,
                operator=operator,
                remark=f"生产领料-工单{order_id}",
            )
            if not result.get("success"):
                return {"success": False, "message": f"领料失败: {result.get('message')}"}

        # Phase 3: 更新已领料量与工单状态
        with get_db() as db:
            order = db.query(ManufacturingOrder).filter(ManufacturingOrder.id == order_id).first()
            for line in order.lines:
                line.consumed_quantity = line.quantity
            order.status = "in_progress"
            order.updated_at = datetime.now()
            db.commit()
            db.refresh(order)
            return {
                "success": True,
                "message": "领料成功",
                "data": order.to_dict(),
                "consumed": [qty for _line_id, _pid, _name, qty in lines_data],
            }

    def finish(self, order_id: int, warehouse_id: int, operator: str | None = None) -> dict[str, Any]:
        """完工：成品入库 → done。"""
        with get_db() as db:
            order = db.query(ManufacturingOrder).filter(ManufacturingOrder.id == order_id).first()
            if not order:
                return {"success": False, "message": "工单不存在"}
            if order.status != "in_progress":
                return {"success": False, "message": f"工单状态 {order.status} 不可完工"}
            product_id, quantity = (
                order.product_id,
                order.quantity,
            )

        result = self.inventory_service.inventory_in(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=float(quantity),
            reference_type="manufacturing",
            reference_id=order_id,
            operator=operator,
            remark=f"生产完工入库-工单{order_id}",
        )
        if not result.get("success"):
            return {"success": False, "message": f"完工入库失败: {result.get('message')}"}

        with get_db() as db:
            order = db.query(ManufacturingOrder).filter(ManufacturingOrder.id == order_id).first()
            order.status = "done"
            order.updated_at = datetime.now()
            db.commit()
            db.refresh(order)
            return {
                "success": True,
                "message": "完工入库成功",
                "data": order.to_dict(),
                "inbound": result.get("data"),
            }

    def query_orders(
        self,
        status: str | None = None,
        product_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(ManufacturingOrder)
            if status:
                query = query.filter(ManufacturingOrder.status == status)
            if product_id:
                query = query.filter(ManufacturingOrder.product_id == product_id)
            total = query.count()
            items = (
                query.order_by(ManufacturingOrder.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            return {
                "success": True,
                "data": [order.to_dict() for order in items],
                "total": total,
                "page": page,
                "per_page": per_page,
            }


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(ManufacturingService, "app.services.manufacturing_service")