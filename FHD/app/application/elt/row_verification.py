"""Read native ELT row effects without executing adapters or mutating their ledger."""

from __future__ import annotations

import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Float, Integer, Numeric, select
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.elt.service_support import load_json
from app.application.elt.targets.customer_product_support import CUSTOMER_MODEL_FIELDS
from app.application.elt.targets.customer_products import CustomerProductsAdapter
from app.application.elt.targets.customers import CustomerAdapter
from app.application.elt.targets.helpers import (
    decimal_or_none,
    decimal_or_zero,
    integer_or_zero,
    optional_text,
    parse_date,
)
from app.application.elt.targets.orders import PurchaseOrderAdapter, ShipmentAdapter
from app.application.elt.targets.products import ProductAdapter
from app.application.elt.targets.targets_base import json_safe
from app.db.models.elt import EltRun, EltRunRow
from app.db.models.product import Product
from app.db.models.purchase import PurchaseOrder, PurchaseOrderItem, Supplier
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.shipment import ShipmentRecord
from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint

_ADAPTERS = {
    "customers": CustomerAdapter,
    "products": ProductAdapter,
    "customer_products": CustomerProductsAdapter,
    "purchase_orders": PurchaseOrderAdapter,
    "shipment_records": ShipmentAdapter,
}
ROW_TARGETS = frozenset(_ADAPTERS)
_CUSTOMER_FIELDS = frozenset(CUSTOMER_MODEL_FIELDS)
_PRODUCT_FIELDS = frozenset(field.key for field in ProductAdapter.fields)
_ITEM_NUMBERS = frozenset(
    {
        "order_id",
        "product_id",
        "quantity",
        "unit_price",
        "amount",
        "received_quantity",
        "invoiced_quantity",
    }
)
_SHIPMENT_NUMBERS = frozenset(
    {"id", "unit_id", "quantity_kg", "quantity_tins", "tin_spec", "unit_price", "amount"}
)


def _object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("elt_effect_object_required")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("elt_effect_object_required")
    return value


def _identity(value: Any) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError("elt_effect_identity_invalid")
    return int(value)


def _equal(actual: Any, expected: Any, *, numeric: bool = False) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    if numeric:
        return decimal_or_none(actual) == decimal_or_none(expected)
    return str(json_safe(actual)) == str(json_safe(expected))


def _image(observed: Any, expected: dict[str, Any], numbers: frozenset[str] = frozenset()) -> None:
    if not isinstance(observed, dict) or not expected.keys() <= observed.keys():
        raise ValueError("elt_effect_snapshot_incomplete")
    if any(
        not _equal(observed[key], value, numeric=key in numbers) for key, value in expected.items()
    ):
        raise ValueError("elt_effect_snapshot_mismatch")


def _base(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not fields <= value.keys():
        raise ValueError("elt_effect_before_incomplete")
    return {key: value[key] for key in fields}


def _read(
    db: Session, tenant: int | None, model: Any, identity: int, fields: Any
) -> dict[str, Any]:
    # Column queries bypass ORM identity-map snapshots. The enclosing no_autoflush
    # also prevents unrelated dirty state from becoming a write during readback.
    row = (
        db.execute(
            select(*(getattr(model, key) for key in fields)).where(
                model.id == identity, model.tenant_id == tenant
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("elt_effect_record_missing_or_foreign")
    return dict(row)


def _stored_value(db: Session, model: Any, key: str, value: Any) -> Any:
    column_type = model.__table__.columns[key].type
    if not isinstance(column_type, Numeric) or value is None:
        return value
    value = decimal_or_none(value)
    dialect = db.get_bind(mapper=model).dialect
    implementation = column_type.dialect_impl(dialect)
    bind = implementation.bind_processor(dialect)
    result = implementation.result_processor(dialect, None)
    value = bind(value) if bind else value
    value = result(value) if result else value
    if isinstance(value, Decimal) and column_type.scale is not None:
        value = value.quantize(Decimal(1).scaleb(-column_type.scale), rounding=ROUND_HALF_UP)
    return value


def _customer(data: dict, before: dict | None, allowed: set[str], *, linked: bool) -> dict:
    name = str(data["customer_name"])
    if linked:
        name = name.strip()
    if before is None:
        return {
            "customer_name": name,
            **{key: optional_text(data.get(key)) for key in _CUSTOMER_FIELDS - {"customer_name"}},
        }
    expected = _base(before, _CUSTOMER_FIELDS)
    _image(expected, {"customer_name": name})
    expected.update(
        {key: data[key] for key in allowed & _CUSTOMER_FIELDS if data.get(key) not in (None, "")}
    )
    return expected


def _product(data: dict, before: dict | None, allowed: set[str], *, linked: bool) -> dict:
    unit = str(data.get("unit") or "")
    model = str(data.get("model_number") or "").strip()
    if before is None:
        return {
            "unit": unit,
            "name": str(data.get("name") or ""),
            "price": decimal_or_none(data.get("price")) or Decimal("0"),
            **{
                key: optional_text(data.get(key))
                for key in _PRODUCT_FIELDS - {"unit", "name", "price"}
            },
        }
    expected = _base(before, _PRODUCT_FIELDS)
    identity = {"unit": unit, **({"model_number": model} if model else {"name": str(data["name"])})}
    _image(expected, identity)
    for key in allowed & _PRODUCT_FIELDS:
        value = data.get(key)
        if value not in (None, ""):
            expected[key] = (
                (decimal_or_none(value) if key == "price" else optional_text(value))
                if linked
                else value
            )
    return expected


def _master_effect(
    row: EltRunRow, data: dict, after: dict, allowed: set[str], effects: dict, *, customer: bool
) -> None:
    before = _object(row.before_json)
    if row.final_action == "new" and row.match_ref in {None, ""}:
        raise ValueError("elt_effect_identity_missing")
    identity = _identity(row.match_ref)
    model = PurchaseUnit if customer else Product
    key = (model, identity)
    if row.final_action == "new" and key in effects:
        raise ValueError("elt_effect_duplicate_creation")
    if customer:
        previous = (
            {target: effects[key][column] for target, column in CUSTOMER_MODEL_FIELDS.items()}
            if key in effects
            else before
        )
        expected = _customer(
            data, None if row.final_action == "new" else previous, allowed, linked=False
        )
        _image(after, expected)
        effects[key] = {
            column: expected[target] for target, column in CUSTOMER_MODEL_FIELDS.items()
        }
    else:
        expected = _product(
            data,
            None if row.final_action == "new" else effects.get(key, before),
            allowed,
            linked=False,
        )
        _image(after, expected, frozenset({"price"}))
        effects[key] = expected


def _linked_effect(
    row: EltRunRow, data: dict, after: dict, allowed: set[str], effects: dict
) -> None:
    customer_id, product_id = CustomerProductsAdapter._parse_match_ref(str(row.match_ref or ""))
    customer_key, product_key = (
        (PurchaseUnit, _identity(customer_id)),
        (Product, _identity(product_id)),
    )
    before = _object(row.before_json)
    prior_customer = (
        {target: effects[customer_key][column] for target, column in CUSTOMER_MODEL_FIELDS.items()}
        if customer_key in effects
        else before.get("customer")
    )
    prior_product = effects.get(product_key, before.get("product"))
    if row.final_action == "update":
        prior_customer = _base(prior_customer, _CUSTOMER_FIELDS)
        prior_product = _base(prior_product, _PRODUCT_FIELDS)
    customer = _customer(data, prior_customer or None, allowed, linked=True)
    product = _product(
        CustomerProductsAdapter._product_data(data),
        None if row.final_action == "new" else prior_product,
        allowed & CustomerProductsAdapter._product_fields,
        linked=True,
    )
    _image(after.get("customer"), customer)
    _image(after.get("product"), product, frozenset({"price"}))
    _image(
        after.get("relationship"),
        {"customer_name": customer["customer_name"], "product_unit": product["unit"]},
    )
    effects[customer_key] = {
        column: customer[target] for target, column in CUSTOMER_MODEL_FIELDS.items()
    }
    if row.final_action == "new" and product_key in effects:
        raise ValueError("elt_effect_duplicate_creation")
    effects[product_key] = product


def _order_effect(
    db: Session, native: EltRun, row: EltRunRow, data: dict, after: dict, effects: dict
) -> None:
    identity = _identity(row.match_ref)
    item = _read(db, native.tenant_id, PurchaseOrderItem, identity, ("order_id", "product_id"))
    order = _read(db, native.tenant_id, PurchaseOrder, item["order_id"], ("supplier_id",))
    supplier = _read(db, native.tenant_id, Supplier, order["supplier_id"], ("name",))
    product = _read(
        db,
        native.tenant_id,
        Product,
        item["product_id"],
        ("model_number", "name", "unit", "specification"),
    )
    _image(supplier, {"name": str(data["supplier_name"])})
    model = str(data.get("product_model") or "").strip()
    _image(product, {"model_number": model} if model else {"name": str(data["product_name"])})
    expected_order = {
        "order_no": str(data["external_order_no"]),
        "supplier_id": order["supplier_id"],
        "order_date": parse_date(data["order_date"]),
        "status": "draft",
    }
    quantity, price = decimal_or_zero(data.get("quantity")), decimal_or_zero(data.get("unit_price"))
    expected_item = {
        "order_id": item["order_id"],
        "product_id": item["product_id"],
        "product_name": product["name"],
        "specification": product["specification"],
        "quantity": quantity,
        "unit": str(data.get("unit") or product["unit"] or "个"),
        "unit_price": price,
        "amount": quantity * price,
        "received_quantity": 0,
        "invoiced_quantity": 0,
        "status": "pending",
        "remark": None,
    }
    _image(
        after,
        {"item_id": identity, "order_id": item["order_id"]},
        frozenset({"item_id", "order_id"}),
    )
    _image(after.get("order_snapshot"), expected_order, frozenset({"supplier_id"}))
    _image(after.get("item_snapshot"), expected_item, _ITEM_NUMBERS)
    key = (PurchaseOrderItem, identity)
    if key in effects:
        raise ValueError("elt_effect_duplicate_creation")
    effects[key] = expected_item
    order_key = (PurchaseOrder, item["order_id"])
    if order_key in effects:
        _image(expected_order, effects[order_key], frozenset({"supplier_id"}))
    effects[order_key] = expected_order


def _shipment_effect(
    db: Session, native: EltRun, row: EltRunRow, data: dict, after: dict, effects: dict
) -> None:
    identity = _identity(row.match_ref)
    fingerprint = ShipmentAdapter()._fingerprint(
        data, {"file_sha256": native.file_sha256, "source_row": row.source_row}
    )
    tin_spec = decimal_or_none(data.get("tin_spec"))
    expected = {
        "purchase_unit": str(data["purchase_unit"]),
        "unit_id": None,
        "product_name": str(data["product_name"]),
        "model_number": optional_text(data.get("model_number")),
        "quantity_kg": float(decimal_or_zero(data.get("quantity_kg"))),
        "quantity_tins": integer_or_zero(data.get("quantity_tins")),
        "tin_spec": float(tin_spec) if tin_spec is not None else None,
        "unit_price": decimal_or_none(data.get("unit_price")) or Decimal("0"),
        "amount": decimal_or_none(data.get("amount")) or Decimal("0"),
        "status": "pending",
        "printed_at": None,
        "printer_name": None,
        "raw_text": json.dumps(json_safe(data), ensure_ascii=False),
        "parsed_data": json.dumps(
            {
                "external_order_no": data.get("external_order_no"),
                "elt_run_id": native.id,
                "elt_fingerprint": fingerprint,
            },
            ensure_ascii=False,
        ),
    }
    _image(after, {"id": identity, **expected}, _SHIPMENT_NUMBERS)
    proof = (
        db.execute(
            select(
                ShipmentEltImportFingerprint.shipment_id,
                ShipmentEltImportFingerprint.meta_json,
                ShipmentEltImportFingerprint.unit_name,
                ShipmentEltImportFingerprint.order_number,
                ShipmentEltImportFingerprint.source_kind,
            ).where(
                ShipmentEltImportFingerprint.tenant_key == f"tenant:{native.tenant_id}",
                ShipmentEltImportFingerprint.fingerprint == fingerprint,
            )
        )
        .mappings()
        .one_or_none()
    )
    if proof is None or _object(proof["meta_json"]) != {"run_id": native.id}:
        raise ValueError("elt_effect_original_fingerprint_missing")
    _image(
        dict(proof),
        {
            "shipment_id": identity,
            "unit_name": expected["purchase_unit"],
            "order_number": optional_text(data.get("external_order_no")),
            "source_kind": "general_elt",
        },
        frozenset({"shipment_id"}),
    )
    key = (ShipmentRecord, identity)
    if key in effects:
        raise ValueError("elt_effect_duplicate_creation")
    effects[key] = expected


def verify_row_effects(db: Session, native: EltRun, rows: list[EltRunRow]) -> dict[str, Any]:
    """Compare the approved row transitions and final scoped business records."""
    if native.target_type not in ROW_TARGETS:
        raise LookupError("elt_effect_target_unsupported")
    adapter = _ADAPTERS[native.target_type]()
    draft = _object(native.draft_json)
    raw_allowed = draft.get("allowed_update_fields", [])
    if not isinstance(raw_allowed, list) or any(not isinstance(key, str) for key in raw_allowed):
        raise ValueError("elt_effect_update_scope_invalid")
    allowed = set(raw_allowed)
    if not allowed <= {field.key for field in adapter.fields if field.updatable}:
        raise ValueError("elt_effect_update_scope_invalid")
    effects: dict[tuple[Any, int], dict[str, Any]] = {}
    checked = 0
    seen: set[int] = set()
    with db.no_autoflush:
        for row in sorted(rows, key=lambda item: item.id):
            if (row.run_id, row.tenant_id, row.owner_user_id) != (
                native.id,
                native.tenant_id,
                native.owner_user_id,
            ):
                raise ValueError("elt_effect_row_scope_mismatch")
            identity = _identity(row.id)
            if identity in seen:
                raise ValueError("elt_effect_duplicate_row")
            seen.add(identity)
            if row.final_action not in {"new", "update"}:
                continue
            if row.execution_status != "success" or row.final_action not in adapter.actions:
                raise ValueError("elt_effect_row_not_successful")
            data, after = _object(row.normalized_json), _object(row.after_json)
            if adapter.validate(data):
                raise ValueError("elt_effect_input_invalid")
            if native.target_type in {"customers", "products"}:
                _master_effect(
                    row, data, after, allowed, effects, customer=native.target_type == "customers"
                )
            elif native.target_type == "customer_products":
                _linked_effect(row, data, after, allowed, effects)
            elif native.target_type == "purchase_orders":
                _order_effect(db, native, row, data, after, effects)
            else:
                _shipment_effect(db, native, row, data, after, effects)
            checked += 1
        if not checked:
            # Skipped rows have no write receipt. Their earlier preview cannot
            # certify that the requested business records still exist now.
            raise LookupError("elt_effect_written_records_unavailable")
        for (model, identity), expected in effects.items():
            observed = _read(db, native.tenant_id, model, identity, expected)
            numbers = frozenset(
                key
                for key in expected
                if isinstance(model.__table__.columns[key].type, (Numeric, Float, Integer))
            )
            stored = {key: _stored_value(db, model, key, value) for key, value in expected.items()}
            _image(observed, stored, numbers)
    references = sorted((model.__tablename__, identity) for model, identity in effects)
    products_by_unit = Counter(
        str(expected["unit"]) for (model, _), expected in effects.items() if model is Product
    )
    return {
        "target_type": native.target_type,
        "rows_checked": checked,
        "business_records": dict(Counter(table for table, _ in references)),
        "business_refs_sha256": canonical_hash(references),
        **(
            {"verified_products_by_unit": dict(sorted(products_by_unit.items()))}
            if products_by_unit
            else {}
        ),
    }


def _execution_rows_current(
    db: Session, run: EltRun, expected_rows: dict[str, Any] | None = None
) -> bool:
    """Compare original committed row images using the existing target snapshot readers."""
    from app.application.elt.targets.customer_product_support import (
        customer_image_matches,
        customer_values,
    )
    from app.application.elt.targets.customer_products import CustomerProductsAdapter
    from app.application.elt.targets.helpers import (
        assert_created_row_unchanged,
        assert_snapshot_unchanged,
        decimal_or_none,
        decimal_or_zero,
        integer_or_zero,
        optional_text,
    )
    from app.application.elt.targets.orders import ShipmentAdapter
    from app.application.elt.targets.products import ProductAdapter
    from app.db.models import Product, PurchaseUnit, ShipmentRecord

    rows = db.query(EltRunRow).filter_by(
        run_id=run.id,
        tenant_id=run.tenant_id,
        owner_user_id=run.owner_user_id,
        execution_status="success",
    )
    for row in rows.yield_per(500):
        after = load_json(row.after_json, {})
        if not isinstance(after, dict) or not after or not isinstance(row.match_ref, str):
            return False
        if run.target_type == "shipment_records":
            record = (
                db.query(ShipmentRecord)
                .filter_by(id=row.match_ref, tenant_id=run.tenant_id)
                .one_or_none()
            )
            if (
                record is None
                or after.get("id") != record.id
                or not set(record.to_dict()) <= set(after)
            ):
                return False
            if not ShipmentAdapter._belongs_to_current_run(record, run.id):
                return False
            assert_snapshot_unchanged(record, after, "发货记录")
            data = load_json(row.normalized_json, {})
            tin_spec = decimal_or_none(data.get("tin_spec"))
            assert_snapshot_unchanged(
                record,
                {
                    "purchase_unit": str(data.get("purchase_unit") or ""),
                    "product_name": str(data.get("product_name") or ""),
                    "model_number": optional_text(data.get("model_number")),
                    "quantity_kg": float(decimal_or_zero(data.get("quantity_kg"))),
                    "quantity_tins": integer_or_zero(data.get("quantity_tins")),
                    "tin_spec": float(tin_spec) if tin_spec is not None else None,
                    # SQLAlchemy applies ShipmentRecord's zero defaults when
                    # the worker supplies an absent optional money value.
                    "unit_price": decimal_or_zero(data.get("unit_price")),
                    "amount": decimal_or_zero(data.get("amount")),
                },
                "已审批出货内容",
            )
            if (
                not db.query(PurchaseUnit.id)
                .filter_by(tenant_id=run.tenant_id, unit_name=record.purchase_unit, is_active=True)
                .first()
            ):
                return False
        else:
            customer_id, product_id = CustomerProductsAdapter._parse_match_ref(row.match_ref)
            customer = (
                db.query(PurchaseUnit)
                .filter_by(id=customer_id, tenant_id=run.tenant_id)
                .one_or_none()
            )
            product = (
                db.query(Product).filter_by(id=product_id, tenant_id=run.tenant_id).one_or_none()
            )
            customer_after, product_after = after.get("customer"), after.get("product")
            reviewed = (expected_rows or {}).get(str(row.id)) or {}
            expected_customer, expected_product = reviewed.get("customer"), reviewed.get("product")
            if (
                customer is None
                or product is None
                or not customer.is_active
                or not isinstance(customer_after, dict)
                or not isinstance(product_after, dict)
                or not set(customer_values(customer)) <= set(customer_after)
                or not {field.key for field in ProductAdapter.fields} <= set(product_after)
                or not customer_image_matches(customer, customer_after)
                or (
                    expected_rows is not None
                    and (
                        not isinstance(expected_customer, dict)
                        or not isinstance(expected_product, dict)
                        or not set(customer_values(customer)) <= set(expected_customer)
                        or not {field.key for field in ProductAdapter.fields}
                        <= set(expected_product)
                        or not customer_image_matches(customer, expected_customer)
                    )
                )
                or customer.unit_name != product.unit
                or after.get("relationship")
                != {"customer_name": customer.unit_name, "product_unit": product.unit}
            ):
                return False
            assert_created_row_unchanged(product, product_after, ProductAdapter.fields, "关联产品")
            if expected_rows is not None:
                assert isinstance(expected_product, dict)
                assert_created_row_unchanged(
                    product, expected_product, ProductAdapter.fields, "已审批产品内容"
                )
    return True
