"""Read-only, tenant-bound entity candidates for sales planning."""

from typing import Any

from sqlalchemy import or_

from app.db.models import Customer, Product
from app.infrastructure.tenant_scope import current_tenant_id


def sales_entity_candidates(db: Any, *, customer_name: str, product_name: str) -> dict[str, Any]:
    """Resolve exact names/model numbers; never create missing business records."""
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise ValueError("Sales entity resolution requires a tenant context")
    customer_name, product_name = customer_name.strip(), product_name.strip()
    if not customer_name or not product_name:
        raise ValueError("Customer and product names are required")
    with db.no_autoflush:
        customers = (
            db.query(Customer)
            .filter(Customer.tenant_id == tenant_id, Customer.customer_name == customer_name)
            .order_by(Customer.id)
            .limit(21)
            .all()
        )
        products = (
            db.query(Product)
            .filter(
                Product.tenant_id == tenant_id,
                or_(Product.name == product_name, Product.model_number == product_name),
            )
            .order_by(Product.id)
            .limit(21)
            .all()
        )
    return {
        "customer_candidates": [
            {"id": row.id, "name": row.customer_name} for row in customers[:20]
        ],
        "product_candidates": [
            {
                "id": row.id,
                "name": row.name,
                "model_number": row.model_number,
                "unit": row.unit,
                "price": str(row.price) if row.price is not None else None,
            }
            for row in products[:20]
        ],
        "customer_unique": len(customers) == 1,
        "product_unique": len(products) == 1,
        "customers_truncated": len(customers) > 20,
        "products_truncated": len(products) > 20,
    }
