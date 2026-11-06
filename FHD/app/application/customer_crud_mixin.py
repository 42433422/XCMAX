import logging
from typing import TYPE_CHECKING, Any

from app.infrastructure.tenant_scope import (
    apply_tenant_filter,
    current_tenant_id,
    owned_tenant_id,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _scoped_units(query: Any, model: Any) -> Any:
    """Tenant-scoped when a server tenant is active; legacy callers stay unchanged."""
    if current_tenant_id() is None and owned_tenant_id() is None:
        return query
    return apply_tenant_filter(query, model)


def _explicit_version(data: dict[str, Any]) -> tuple[int | None, bool]:
    """Return (version, invalid). Missing key means the caller did not opt in."""
    if "expected_version" not in data:
        return None, False
    raw = data.get("expected_version")
    if isinstance(raw, bool):
        return None, True
    if isinstance(raw, int):
        return raw, False
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip()), False
    return None, True


def _versioned_update(
    session: Any, model: Any, customer_id: int, data: dict[str, Any], expected: int
) -> int:
    """Atomic compare-and-set. Returns the number of rows the database changed."""
    from sqlalchemy import text
    from sqlalchemy import update as sql_update

    values: dict[str, Any] = {"version": model.version + 1}
    if "customer_name" in data:
        values["unit_name"] = data["customer_name"]
    if "contact_person" in data:
        values["contact_person"] = data["contact_person"]
    if "contact_phone" in data:
        values["contact_phone"] = data["contact_phone"]
    if "contact_address" in data:
        values["address"] = data["contact_address"]
    conditions = [model.id == customer_id, model.version == expected]
    tenant_id = current_tenant_id()
    if tenant_id is not None:
        conditions.append(model.tenant_id == tenant_id)
    statement = (
        sql_update(model)
        .where(*conditions)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(statement)
    matched = result.rowcount
    if matched is None or matched < 0:
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "sqlite":
            matched = int(session.execute(text("SELECT changes()")).scalar_one())
        else:
            matched = 0
    return int(matched)


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

                query = _scoped_units(
                    session.query(PurchaseUnitModel).filter(PurchaseUnitModel.is_active == True),
                    PurchaseUnitModel,
                )

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
                    apply_tenant_filter(session.query(PurchaseUnitModel), PurchaseUnitModel)
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
                    _scoped_units(session.query(PurchaseUnitModel), PurchaseUnitModel)
                    .filter(PurchaseUnitModel.unit_name == customer_name)
                    .first()
                )

                if existing:
                    return {"success": False, "message": "客户名称已存在"}

                stamped = owned_tenant_id()
                if stamped is None:
                    stamped = current_tenant_id()
                unit = PurchaseUnitModel(
                    unit_name=customer_name,
                    contact_person=data.get("contact_person", ""),
                    contact_phone=data.get("contact_phone", ""),
                    address=data.get("contact_address", ""),
                    tenant_id=stamped,
                    is_active=True,
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
                    _scoped_units(session.query(PurchaseUnitModel), PurchaseUnitModel)
                    .filter(PurchaseUnitModel.id == customer_id)
                    .first()
                )

                if not unit:
                    return {"success": False, "message": "客户不存在"}

                expected_version, version_invalid = _explicit_version(data)
                if version_invalid:
                    return {
                        "success": False,
                        "error_code": "version_conflict",
                        "message": "客户版本不正确，本次修改没有写入",
                    }

                if "customer_name" in data:
                    existing = (
                        _scoped_units(session.query(PurchaseUnitModel), PurchaseUnitModel)
                        .filter(
                            PurchaseUnitModel.unit_name == data["customer_name"],
                            PurchaseUnitModel.id != customer_id,
                        )
                        .first()
                    )
                    if existing:
                        return {"success": False, "message": "客户名称已存在"}

                if expected_version is not None:
                    session.expunge(unit)
                    matched = _versioned_update(
                        session, PurchaseUnitModel, customer_id, data, expected_version
                    )
                    if matched != 1:
                        session.rollback()
                        return {
                            "success": False,
                            "error_code": "version_conflict",
                            "message": "客户版本已变化，本次修改没有写入",
                        }
                    session.commit()
                    unit = (
                        _scoped_units(session.query(PurchaseUnitModel), PurchaseUnitModel)
                        .filter(PurchaseUnitModel.id == customer_id)
                        .first()
                    )
                else:
                    if "customer_name" in data:
                        unit.unit_name = data["customer_name"]
                    if "contact_person" in data:
                        unit.contact_person = data["contact_person"]
                    if "contact_phone" in data:
                        unit.contact_phone = data["contact_phone"]
                    if "contact_address" in data:
                        unit.address = data["contact_address"]
                    current_version = getattr(unit, "version", None)
                    if isinstance(current_version, int) and not isinstance(current_version, bool):
                        unit.version = current_version + 1
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

                saved = {
                    "id": unit.id,
                    "customer_name": unit.unit_name,
                    "contact_person": unit.contact_person or "",
                    "contact_phone": unit.contact_phone or "",
                    "contact_address": unit.address or "",
                    "created_at": unit.created_at.isoformat() if unit.created_at else None,
                    "updated_at": unit.updated_at.isoformat() if unit.updated_at else None,
                }
                saved_version = getattr(unit, "version", None)
                if isinstance(saved_version, int) and not isinstance(saved_version, bool):
                    saved["version"] = saved_version
                return {"success": True, "message": "客户更新成功", "data": saved}
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
                    _scoped_units(session.query(PurchaseUnitModel), PurchaseUnitModel)
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

                units = (
                    _scoped_units(session.query(PurchaseUnitModel), PurchaseUnitModel)
                    .filter(PurchaseUnitModel.id.in_(ids))
                    .all()
                )

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
