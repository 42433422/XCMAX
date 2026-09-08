"""Read-only classification of the legacy overloaded Product.unit field."""

from collections import defaultdict

from app.infrastructure.repositories.product_query_helpers import TRIVIAL_MEASURE_UNITS


def classify_product_units(products: list[dict], customers: list[dict]) -> list[dict]:
    """Never infer a measurement unit for a legacy customer-owned product."""
    index = defaultdict(list)
    for customer in customers:
        tenant = customer.get("tenant_id")
        name = str(customer.get("unit_name") or "").strip()
        if tenant is not None and name and customer.get("is_active", True):
            index[(tenant, name)].append(customer["id"])
    result = []
    for product in products:
        tenant = product.get("tenant_id")
        unit = str(product.get("unit") or "").strip()
        matches = sorted(set(index.get((tenant, unit), [])))
        if tenant is None:
            state = "missing_tenant"
        elif unit in TRIVIAL_MEASURE_UNITS and matches:
            state = "ambiguous_measure_or_customer"
        elif unit in TRIVIAL_MEASURE_UNITS:
            state = "measurement_unit"
        elif len(matches) == 1:
            state = "customer_link_requires_measurement"
        elif len(matches) > 1:
            state = "ambiguous_customer"
        else:
            state = "unresolved_unit"
        result.append(
            {
                "product_id": product["id"],
                "tenant_id": tenant,
                "classification": state,
                "candidate_customer_ids": matches if tenant is not None else [],
            }
        )
    return result


def inspect_product_units(db) -> list[dict]:
    """Inspect persisted rows for the current tenant without flushing pending writes."""
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import TenantScopeError, current_tenant_id

    tenant = current_tenant_id()
    if tenant is None or tenant <= 0:
        raise TenantScopeError("产品单位迁移检查需要明确租户")
    with db.no_autoflush:
        customers = [
            {
                "id": row.id,
                "tenant_id": tenant,
                "unit_name": row.unit_name,
                "is_active": row.is_active,
            }
            for row in db.query(PurchaseUnit.id, PurchaseUnit.unit_name, PurchaseUnit.is_active)
            .filter(PurchaseUnit.tenant_id == tenant)
            .all()
        ]
        products = [
            {"id": row.id, "tenant_id": tenant, "unit": row.unit}
            for row in db.query(Product.id, Product.unit)
            .filter(Product.tenant_id == tenant)
            .order_by(Product.id)
            .all()
        ]
    return classify_product_units(products, customers)
