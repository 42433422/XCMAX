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
