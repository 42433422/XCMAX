import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.domain.customer.entities import PurchaseUnit
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

class CustomerRelationshipMixin:
    if TYPE_CHECKING:

        def _get_session(self) -> Any: ...

    def get_purchase_unit_by_name(self, name: str) -> PurchaseUnit | None:
        """根据名称获取购买单位（用于内部业务）"""
        try:
            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                unit = (
                    session.query(PurchaseUnitModel)
                    .filter(
                        PurchaseUnitModel.unit_name == name, PurchaseUnitModel.is_active == True
                    )
                    .first()
                )

                if unit:
                    return PurchaseUnit(
                        id=unit.id,
                        unit_name=unit.unit_name,
                        contact_person=unit.contact_person or "",
                        contact_phone=unit.contact_phone or "",
                        address=unit.address or "",
                        discount_rate=unit.discount_rate or 1.0,
                        is_active=bool(unit.is_active),
                        created_at=unit.created_at,
                        updated_at=unit.updated_at,
                    )
                return None
            finally:
                session.close()

        except RECOVERABLE_ERRORS as e:
            logger.exception("查询购买单位失败: %s", e)
            return None

    def match_purchase_unit(self, input_name: str) -> PurchaseUnit | None:
        """智能匹配购买单位（模糊匹配）"""
        try:
            name = str(input_name or "").strip()
            if not name:
                # 空串在 Python 中属于任意字符串的子串，若参与子串匹配会误命中第一条记录
                return None

            session = self._get_session()
            try:
                from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

                exact = (
                    session.query(PurchaseUnitModel)
                    .filter(
                        PurchaseUnitModel.unit_name == name, PurchaseUnitModel.is_active == True
                    )
                    .first()
                )

                if exact:
                    return PurchaseUnit(
                        id=exact.id,
                        unit_name=exact.unit_name,
                        contact_person=exact.contact_person or "",
                        contact_phone=exact.contact_phone or "",
                        address=exact.address or "",
                    )

                all_units = (
                    session.query(PurchaseUnitModel)
                    .filter(PurchaseUnitModel.is_active == True)
                    .all()
                )

                # 子串匹配仅用于较长名称，避免单字/短串误命中多个客户
                if len(name) >= 2:
                    for unit in all_units:
                        un = unit.unit_name or ""
                        if name in un or un in name:
                            return PurchaseUnit(
                                id=unit.id,
                                unit_name=unit.unit_name,
                                contact_person=unit.contact_person or "",
                                contact_phone=unit.contact_phone or "",
                                address=unit.address or "",
                            )

                return None
            finally:
                session.close()

        except RECOVERABLE_ERRORS as e:
            logger.exception("匹配购买单位失败：%s", e)
            return None

    def add_address(self, data: dict[str, Any]) -> dict[str, Any]:
        """新增客户地址（送货 delivery / 发票 invoice）。

        若 ``is_default`` 为真，则先取消该客户其他默认地址，保证默认地址唯一。
        """
        try:
            session = self._get_session()
            try:
                from app.db.models.crm import CustomerAddress
                from app.db.models.customer import Customer

                customer_id = data.get("customer_id")
                if customer_id is None:
                    return {"success": False, "message": "客户ID不能为空"}

                customer = session.query(Customer).filter(Customer.id == customer_id).first()
                if not customer:
                    return {"success": False, "message": "客户不存在"}

                address_type = data.get("address_type", "delivery")
                if address_type not in ("invoice", "delivery"):
                    return {"success": False, "message": "地址类型必须为 invoice 或 delivery"}

                is_default = 1 if data.get("is_default") else 0
                if is_default:
                    session.query(CustomerAddress).filter(
                        CustomerAddress.customer_id == customer_id,
                        CustomerAddress.is_default == 1,
                    ).update({"is_default": 0})

                addr = CustomerAddress(
                    customer_id=customer_id,
                    address_type=address_type,
                    contact_person=data.get("contact_person", ""),
                    phone=data.get("phone", ""),
                    address=data.get("address", ""),
                    is_default=is_default,
                )
                session.add(addr)
                session.commit()
                session.refresh(addr)

                return {"success": True, "message": "地址添加成功", "data": addr.to_dict()}
            finally:
                session.close()
        except RECOVERABLE_ERRORS as e:
            logger.exception("添加客户地址失败: %s", e)
            return {"success": False, "message": str(e)}

    def get_addresses(self, customer_id: int) -> dict[str, Any]:
        """查询客户所有地址。"""
        try:
            session = self._get_session()
            try:
                from app.db.models.crm import CustomerAddress

                addresses = (
                    session.query(CustomerAddress)
                    .filter(CustomerAddress.customer_id == customer_id)
                    .order_by(CustomerAddress.is_default.desc(), CustomerAddress.id)
                    .all()
                )
                return {
                    "success": True,
                    "data": [a.to_dict() for a in addresses],
                    "count": len(addresses),
                }
            finally:
                session.close()
        except RECOVERABLE_ERRORS as e:
            logger.exception("查询客户地址失败: %s", e)
            return {"success": False, "message": str(e), "data": [], "count": 0}

    def set_credit_limit(self, customer_id: int, limit: float | Decimal) -> dict[str, Any]:
        """设置客户信用额度。"""
        try:
            session = self._get_session()
            try:
                from app.db.models.customer import Customer

                customer = session.query(Customer).filter(Customer.id == customer_id).first()
                if not customer:
                    return {"success": False, "message": "客户不存在"}

                customer.credit_limit = limit
                customer.is_credit_limited = 1 if limit else 0
                session.commit()
                session.refresh(customer)

                return {
                    "success": True,
                    "message": "信用额度设置成功",
                    "data": {
                        "id": customer.id,
                        "customer_name": customer.customer_name,
                        "credit_limit": float(customer.credit_limit or 0),
                        "credit_used": float(customer.credit_used or 0),
                        "is_credit_limited": customer.is_credit_limited,
                    },
                }
            finally:
                session.close()
        except RECOVERABLE_ERRORS as e:
            logger.exception("设置信用额度失败: %s", e)
            return {"success": False, "message": str(e)}

    def get_suppliers(
        self, status: str | None = None, keyword: str | None = None
    ) -> dict[str, Any]:
        """供应商查询薄封装，复用 purchase_service 的 PurchaseService。"""
        from app.services.purchase_service import PurchaseService

        return PurchaseService().get_suppliers(status=status, keyword=keyword)

    def get_supplier(self, supplier_id: int) -> dict[str, Any]:
        """供应商详情薄封装，复用 purchase_service 的 PurchaseService。"""
        from app.services.purchase_service import PurchaseService

        return PurchaseService().get_supplier(supplier_id)
