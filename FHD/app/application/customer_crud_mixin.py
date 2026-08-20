import logging
from typing import TYPE_CHECKING, Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class CustomerCrudMixin:
    if TYPE_CHECKING:

        def _get_session(self) -> Any: ...

    def get_all(
        self, keyword: str | None = None, page: int = 1, per_page: int = 20
    ) -> dict[str, Any]:
        """获取所有购买单位（分页）"""
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                query = session.query(PurchaseUnitModel).filter(PurchaseUnitModel.is_active == True)

                if keyword:
                    pattern = f"%{keyword}%"
                    query = query.filter(PurchaseUnitModel.unit_name.like(pattern))

                total = query.count()
                units = (
                    query.order_by(PurchaseUnitModel.unit_name)
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )

                return {
                    "success": True,
                    "data": [
                        {
                            "id": unit.id,
                            "customer_name": unit.unit_name,
                            "contact_person": unit.contact_person or "",
                            "contact_phone": unit.contact_phone or "",
                            "contact_address": unit.address or "",
                            "created_at": unit.created_at.isoformat() if unit.created_at else None,
                            "updated_at": unit.updated_at.isoformat() if unit.updated_at else None,
                        }
                        for unit in units
                    ],
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                }
            finally:
                session.close()

        except RECOVERABLE_ERRORS:
            logger.exception("获取客户列表失败")
            return {"success": False, "message": "获取客户列表失败", "data": [], "total": 0}

    def get_by_id(self, customer_id: int) -> dict[str, Any]:
        """根据 ID 获取单个购买单位"""
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                unit = (
                    session.query(PurchaseUnitModel)
                    .filter(PurchaseUnitModel.id == customer_id)
                    .first()
                )

                if not unit:
                    return {"success": False, "message": "客户不存在", "data": None}

                return {
                    "success": True,
                    "data": {
                        "id": unit.id,
                        "customer_name": unit.unit_name,
                        "contact_person": unit.contact_person or "",
                        "contact_phone": unit.contact_phone or "",
                        "contact_address": unit.address or "",
                        "created_at": unit.created_at.isoformat() if unit.created_at else None,
                        "updated_at": unit.updated_at.isoformat() if unit.updated_at else None,
                    },
                }
            finally:
                session.close()

        except RECOVERABLE_ERRORS:
            logger.exception("获取客户失败")
            return {"success": False, "message": "获取客户失败", "data": None}

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建购买单位"""
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                customer_name = data.get("customer_name")
                if not customer_name:
                    return {"success": False, "message": "客户名称不能为空"}

                existing = (
                    session.query(PurchaseUnitModel)
                    .filter(PurchaseUnitModel.unit_name == customer_name)
                    .first()
                )

                if existing:
                    return {"success": False, "message": "客户名称已存在"}

                unit = PurchaseUnitModel(
                    unit_name=customer_name,
                    contact_person=data.get("contact_person", ""),
                    contact_phone=data.get("contact_phone", ""),
                    address=data.get("contact_address", ""),
                )

                session.add(unit)
                session.commit()
                session.refresh(unit)

                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_customer_changed,
                    )

                    neuro_notify_customer_changed(
                        "created", customer_id=unit.id, customer_name=unit.unit_name
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_customer_changed skipped", exc_info=True)

                return {
                    "success": True,
                    "message": "客户创建成功",
                    "data": {
                        "id": unit.id,
                        "customer_name": unit.unit_name,
                        "contact_person": unit.contact_person or "",
                        "contact_phone": unit.contact_phone or "",
                        "contact_address": unit.address or "",
                        "created_at": unit.created_at.isoformat() if unit.created_at else None,
                        "updated_at": unit.updated_at.isoformat() if unit.updated_at else None,
                    },
                }
            finally:
                session.close()

        except RECOVERABLE_ERRORS:
            logger.exception("创建客户失败")
            return {"success": False, "message": "创建客户失败"}

    def update(self, customer_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """更新购买单位"""
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                unit = (
                    session.query(PurchaseUnitModel)
                    .filter(PurchaseUnitModel.id == customer_id)
                    .first()
                )

                if not unit:
                    return {"success": False, "message": "客户不存在"}

                if "customer_name" in data:
                    existing = (
                        session.query(PurchaseUnitModel)
                        .filter(
                            PurchaseUnitModel.unit_name == data["customer_name"],
                            PurchaseUnitModel.id != customer_id,
                        )
                        .first()
                    )
                    if existing:
                        return {"success": False, "message": "客户名称已存在"}
                    unit.unit_name = data["customer_name"]

                if "contact_person" in data:
                    unit.contact_person = data["contact_person"]
                if "contact_phone" in data:
                    unit.contact_phone = data["contact_phone"]
                if "contact_address" in data:
                    unit.address = data["contact_address"]

                session.commit()
                session.refresh(unit)

                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_customer_changed,
                    )

                    neuro_notify_customer_changed(
                        "updated", customer_id=unit.id, customer_name=unit.unit_name
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_customer_changed skipped", exc_info=True)

                return {
                    "success": True,
                    "message": "客户更新成功",
                    "data": {
                        "id": unit.id,
                        "customer_name": unit.unit_name,
                        "contact_person": unit.contact_person or "",
                        "contact_phone": unit.contact_phone or "",
                        "contact_address": unit.address or "",
                        "created_at": unit.created_at.isoformat() if unit.created_at else None,
                        "updated_at": unit.updated_at.isoformat() if unit.updated_at else None,
                    },
                }
            finally:
                session.close()

        except RECOVERABLE_ERRORS:
            logger.exception("更新客户失败")
            return {"success": False, "message": "更新客户失败"}

    def _check_shipment_associations(self, unit_name: str) -> dict[str, Any]:
        """检查购买单位是否有关联的发货记录

        Returns:
            {
                "has_associations": bool,
                "shipment_count": int,
                "sample_records": list - 最近3条发货记录示例
            }
        """
        try:
            from app.db.models.shipment import ShipmentRecord
            from app.db.session import get_db

            with get_db() as db:
                records = (
                    db.query(ShipmentRecord)
                    .filter(ShipmentRecord.purchase_unit == unit_name)
                    .order_by(ShipmentRecord.created_at.desc())
                    .limit(3)
                    .all()
                )

                total_count = (
                    db.query(ShipmentRecord)
                    .filter(ShipmentRecord.purchase_unit == unit_name)
                    .count()
                )

                sample_records = []
                for r in records:
                    sample_records.append(
                        {
                            "id": r.id,
                            "product_name": r.product_name,
                            "quantity_kg": r.quantity_kg,
                            "created_at": r.created_at.isoformat() if r.created_at else None,
                        }
                    )

                return {
                    "has_associations": total_count > 0,
                    "shipment_count": total_count,
                    "sample_records": sample_records,
                }
        except RECOVERABLE_ERRORS:
            logger.warning("检查发货记录关联失败", exc_info=True)
            return {
                "has_associations": False,
                "shipment_count": 0,
                "sample_records": [],
                "message": "关联发货记录检查失败",
            }

    def delete(self, customer_id: int, force: bool = False) -> dict[str, Any]:
        """删除购买单位

        Args:
            customer_id: 客户ID
            force: 是否强制删除（忽略关联检查）

        Returns:
            删除结果，包含关联检查信息
        """
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                unit = (
                    session.query(PurchaseUnitModel)
                    .filter(PurchaseUnitModel.id == customer_id)
                    .first()
                )

                if not unit:
                    return {"success": False, "message": "客户不存在", "deleted_count": 0}

                unit_name = unit.unit_name

                association_check = self._check_shipment_associations(unit_name)

                if association_check.get("has_associations") and not force:
                    return {
                        "success": False,
                        "message": f"无法删除客户「{unit_name}」，存在 {association_check['shipment_count']} 条关联发货记录",
                        "deleted_count": 0,
                        "has_associations": True,
                        "association_details": {
                            "shipment_count": association_check["shipment_count"],
                            "sample_records": association_check["sample_records"],
                        },
                        "suggestion": "请先删除关联的发货记录，或使用 force=True 强制删除",
                    }

                session.delete(unit)
                session.commit()

                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_customer_changed,
                    )

                    neuro_notify_customer_changed(
                        "deleted", customer_id=customer_id, customer_name=unit.unit_name
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_customer_changed skipped", exc_info=True)

                return {
                    "success": True,
                    "message": "客户删除成功",
                    "deleted_count": 1,
                    "has_associations": False,
                }
            finally:
                session.close()

        except RECOVERABLE_ERRORS:
            logger.exception("删除客户失败")
            return {"success": False, "message": "删除客户失败", "deleted_count": 0}

    def batch_delete(self, ids: list[int], force: bool = False) -> dict[str, Any]:
        """批量删除购买单位

        Args:
            ids: 客户ID列表
            force: 是否强制删除（忽略关联检查）

        Returns:
            删除结果，包含关联检查信息
        """
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                units = session.query(PurchaseUnitModel).filter(PurchaseUnitModel.id.in_(ids)).all()

                if not units:
                    return {"success": False, "message": "未找到要删除的客户", "deleted_count": 0}

                if not force:
                    affected_units = []
                    for unit in units:
                        check = self._check_shipment_associations(unit.unit_name)
                        if check.get("has_associations"):
                            affected_units.append(
                                {
                                    "id": unit.id,
                                    "unit_name": unit.unit_name,
                                    "shipment_count": check["shipment_count"],
                                    "sample_records": check["sample_records"],
                                }
                            )

                    if affected_units:
                        return {
                            "success": False,
                            "message": f"存在 {len(affected_units)} 个客户关联发货记录，无法批量删除",
                            "deleted_count": 0,
                            "has_associations": True,
                            "affected_units": affected_units,
                            "suggestion": "请先删除关联的发货记录，或使用 force=True 强制删除",
                        }

                for unit in units:
                    session.delete(unit)

                session.commit()

                return {
                    "success": True,
                    "message": f"成功删除 {len(units)} 条记录",
                    "deleted_count": len(units),
                }
            finally:
                session.close()

        except RECOVERABLE_ERRORS:
            logger.exception("批量删除失败")
            return {"success": False, "message": "批量删除失败", "deleted_count": 0}
