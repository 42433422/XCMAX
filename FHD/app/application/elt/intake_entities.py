"""Count customers, purchase units, products and lines already on an intake row."""

from __future__ import annotations

from typing import Any, Iterable

from app.application.elt.targets.helpers import is_column_header_label

_CUSTOMER = ("customer_name", "客户名称", "客户")
_UNIT = ("purchase_unit", "unit", "购买单位", "购货单位", "单位")
_PRODUCT = ("product_name", "name", "产品名称", "品名", "产品")
_WRITTEN = {"new", "update"}


def _text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key not in data or data.get(key) is None:
            continue
        text = str(data.get(key)).strip()
        if not text:
            continue
        if is_column_header_label(text):
            return ""
        return text
    return ""


def count_import_entities(rows: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, int]:
    """Distinct values a preview will write. A column title is never an entity."""
    customers: set[str] = set()
    units: set[str] = set()
    products: set[str] = set()
    records = 0
    for action, data in rows:
        if action not in _WRITTEN or not isinstance(data, dict):
            continue
        customer = _text(data, _CUSTOMER)
        unit = _text(data, _UNIT)
        product = _text(data, _PRODUCT)
        if customer:
            customers.add(customer)
        if unit:
            units.add(unit)
        elif customer:
            units.add(customer)
        if product:
            products.add(product)
        if customer or unit or product:
            records += 1
    return {
        "customers": len(customers),
        "purchase_units": len(units),
        "products": len(products),
        "records": records,
    }


def entities_for_run(db: Any, run_id: str, owner_user_id: int) -> dict[str, int]:
    from app.application.elt.service_support import load_json
    from app.db.models.elt import EltRunRow

    stored = (
        db.query(EltRunRow.final_action, EltRunRow.normalized_json)
        .filter(EltRunRow.run_id == run_id, EltRunRow.owner_user_id == owner_user_id)
        .all()
    )
    return count_import_entities((str(action or ""), load_json(raw, {})) for action, raw in stored)
