from app.db.models import PurchaseUnit as PurchaseUnitModel
from app.domain.customer.entities import Customer, PurchaseUnit
from app.domain.value_objects import Address, ContactInfo


def purchase_unit_to_domain(db_model: PurchaseUnitModel) -> PurchaseUnit:
    # purchase_units schema 无 discount_rate 列；用 getattr 兜底以兼容已落地数据，
    # 仅在缺列/为 None 时回退默认 1.0，保留合法的 0.0 折扣语义。
    discount_value = getattr(db_model, "discount_rate", None)
    discount_rate = 1.0 if discount_value is None else discount_value
    return PurchaseUnit(
        id=db_model.id,
        unit_name=db_model.unit_name or "",
        contact_person=db_model.contact_person or "",
        contact_phone=db_model.contact_phone or "",
        address=db_model.address or "",
        discount_rate=discount_rate,
        is_active=bool(db_model.is_active),
        created_at=db_model.created_at,
        updated_at=db_model.updated_at,
    )


def purchase_unit_to_db(unit: PurchaseUnit) -> dict:
    return {
        "unit_name": unit.unit_name,
        "contact_person": unit.contact_person,
        "contact_phone": unit.contact_phone,
        "address": unit.address,
        "discount_rate": unit.discount_rate,
        "is_active": 1 if unit.is_active else 0,
    }


def customer_to_domain(db_model: PurchaseUnitModel) -> Customer:
    # ContactInfo 字段为 name/phone/address，且 address 需要 Address 值对象而非字符串；
    # 数据库里存的是地址字符串，仅在非空时用 Address.from_string 包装，否则置 None。
    address_str = db_model.address or ""
    return Customer(
        id=db_model.id,
        customer_name=db_model.unit_name or "",
        contact_info=ContactInfo(
            name=db_model.contact_person or "",
            phone=db_model.contact_phone or "",
            address=Address.from_string(address_str) if address_str else None,
        ),
        created_at=db_model.created_at,
        updated_at=db_model.updated_at,
    )
