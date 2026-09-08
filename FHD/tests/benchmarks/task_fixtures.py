"""Explicit, tenant-bound initial records for isolated task benchmarks."""

from typing import Any


def seed_initial_state(db: Any, records: list[dict[str, Any]], tenant_id: int) -> None:
    """Seed only declared business entities; caller owns the transaction."""
    from app.db.models import Customer, Product, PurchaseUnit, Warehouse

    models = {
        "customers": Customer,
        "products": Product,
        "purchase_units": PurchaseUnit,
        "warehouses": Warehouse,
    }
    for record in records:
        entity = record["entity"]
        if entity not in models:
            raise ValueError(f"Unsupported initial_state entity: {entity}")
        values = dict(record["values"])
        if "tenant_id" in values:
            raise ValueError("Initial state tenant is supplied by the benchmark context")
        model = models[entity]
        unknown = set(values) - set(model.__table__.columns.keys())
        if unknown:
            raise ValueError(f"Unknown initial_state fields: {sorted(unknown)}")
        db.add(model(**values, tenant_id=tenant_id))
    db.flush()
