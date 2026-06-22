from datetime import datetime

from app.db.models import PurchaseUnit as PurchaseUnitModel
from app.db.session import get_db
from app.domain.customer.entities import Customer, PurchaseUnit
from app.infrastructure.mappers.customer_mapper import (
    customer_to_domain,
    purchase_unit_to_db,
    purchase_unit_to_domain,
)
from app.infrastructure.repositories.customer_repository import CustomerRepository
from app.infrastructure.tenant_scope import apply_tenant_filter, tenant_id_for_write


class SQLAlchemyCustomerRepository(CustomerRepository):
    """客户仓储 SQLAlchemy 实现 - 使用 products.db（已合并 purchase_units 表）"""

    def _to_unit_domain(self, db_model: PurchaseUnitModel) -> PurchaseUnit:
        return purchase_unit_to_domain(db_model)

    def _to_unit_db(self, unit: PurchaseUnit) -> dict:
        return purchase_unit_to_db(unit)

    def save_customer(self, customer: Customer) -> Customer:
        with get_db() as db:
            existing = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.unit_name == customer.customer_name)
                .first()
            )
            # ContactInfo.address 现为 Address 值对象（或 None），DB address 列为字符串，
            # 落库前转为完整地址字符串；旧代码的 .person 应为 .name。
            contact = customer.contact_info
            address_str = contact.address.to_full_string() if contact.address else ""
            if existing:
                existing.contact_person = contact.name
                existing.contact_phone = contact.phone
                existing.address = address_str
                existing.updated_at = datetime.now()
                db.commit()
                db.refresh(existing)
                return self._to_unit_domain(existing)
            unit = PurchaseUnitModel(
                unit_name=customer.customer_name,
                contact_person=contact.name,
                contact_phone=contact.phone,
                address=address_str,
                tenant_id=tenant_id_for_write(),
            )
            db.add(unit)
            db.commit()
            db.refresh(unit)
            return self._to_unit_domain(unit)

    def find_customer_by_id(self, customer_id: int) -> Customer | None:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.id == customer_id)
                .first()
            )
            if not model:
                return None
            return customer_to_domain(model)

    def find_customer_by_name(self, name: str) -> Customer | None:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.unit_name == name)
                .first()
            )
            if not model:
                return None
            return customer_to_domain(model)

    def find_all_customers(self) -> list[Customer]:
        with get_db() as db:
            models = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.is_active == True)
                .all()
            )
            return [customer_to_domain(m) for m in models]

    def delete_customer(self, customer_id: int) -> bool:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.id == customer_id)
                .first()
            )
            if model:
                db.delete(model)
                db.commit()
                return True
            return False

    def save_purchase_unit(self, unit: PurchaseUnit) -> PurchaseUnit:
        with get_db() as db:
            if unit.id:
                existing = (
                    apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                    .filter(PurchaseUnitModel.id == unit.id)
                    .first()
                )
                if existing:
                    for key, value in self._to_unit_db(unit).items():
                        setattr(existing, key, value)
                    existing.updated_at = datetime.now()
                    db.commit()
                    db.refresh(existing)
                    return self._to_unit_domain(existing)

            db_model = PurchaseUnitModel(**self._to_unit_db(unit))
            if getattr(db_model, "tenant_id", None) is None:
                db_model.tenant_id = tenant_id_for_write()
            db.add(db_model)
            db.commit()
            db.refresh(db_model)
            unit.id = db_model.id
            return unit

    def find_purchase_unit_by_id(self, unit_id: int) -> PurchaseUnit | None:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.id == unit_id)
                .first()
            )
            return self._to_unit_domain(model) if model else None

    def find_purchase_unit_by_name(self, name: str) -> PurchaseUnit | None:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.unit_name == name)
                .first()
            )
            return self._to_unit_domain(model) if model else None

    def find_all_purchase_units(self) -> list[PurchaseUnit]:
        with get_db() as db:
            models = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.is_active == 1)
                .all()
            )
            return [self._to_unit_domain(m) for m in models]

    def delete_purchase_unit(self, unit_id: int) -> bool:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(PurchaseUnitModel), PurchaseUnitModel)
                .filter(PurchaseUnitModel.id == unit_id)
                .first()
            )
            if model:
                db.delete(model)
                db.commit()
                return True
            return False
