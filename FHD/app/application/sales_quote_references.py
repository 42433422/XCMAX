"""Resolve named quote references before writing any order or item."""

from typing import Any

from app.db.models import Customer, Product


def resolve_quote_references(
    db: Any, data: dict, items: list[dict]
) -> tuple[Any, list[tuple[dict, Any]]]:
    customer_id = data.get("customer_id")
    name = str(data.get("customer_name") or "").strip()
    if customer_id:
        customer = db.query(Customer).filter(Customer.id == int(customer_id)).first()
        if customer is None or (name and customer.customer_name != name):
            raise ValueError("客户编号不存在或与客户名称不符")
    else:
        matches = db.query(Customer).filter(Customer.customer_name == name).limit(2).all()
        if len(matches) > 1:
            raise ValueError("客户名称不存在或存在重名，请选择明确的客户")
        if matches:
            customer = matches[0]
        else:
            from app.db.models.purchase_unit import PurchaseUnit
            from app.infrastructure.tenant_scope import current_tenant_id

            tenant_id = current_tenant_id()
            if not tenant_id:
                raise ValueError("缺少客户所属租户")
            units = (
                db.query(PurchaseUnit)
                .filter(PurchaseUnit.tenant_id == tenant_id, PurchaseUnit.unit_name == name)
                .limit(2)
                .all()
            )
            if len(units) != 1:
                raise ValueError("客户名称不存在或存在重名，请选择明确的客户")
            unit = units[0]
            # Keep the bridge transient until all product references are valid.
            customer = Customer(
                customer_name=unit.unit_name,
                contact_person=unit.contact_person,
                contact_phone=unit.contact_phone,
                contact_address=unit.address,
                tenant_id=tenant_id,
            )
    resolved = []
    for item in items:
        product_id = item.get("product_id")
        model = str(item.get("model_number") or "").strip()
        product = None
        if product_id:
            product = db.query(Product).filter(Product.id == int(product_id)).first()
            if product is None or (model and product.model_number != model):
                raise ValueError("产品编号不存在或与产品型号不符")
        elif model:
            matches = db.query(Product).filter(Product.model_number == model).limit(2).all()
            if len(matches) != 1:
                raise ValueError("产品型号不存在或存在重复，请选择明确的产品")
            product = matches[0]
        resolved.append((item, product))
    return customer, resolved
