"""Cross-PR value fidelity and preview safety, using only synthetic records."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.application.elt.errors import EltError
from app.application.elt.service_execution import _unconfirmed_mappings
from app.application.elt.targets.targets_base import TargetAdapter, TargetField, strict_decimal
from app.application.elt.transforms import apply_transform


@pytest.mark.parametrize("confidence", [0, -1, 0.89, 1.1, "NaN", "Infinity", None])
def test_invalid_or_low_mapping_confidence_requires_confirmation(confidence):
    mapping = {"source": "名字", "target": "customer_name", "confidence": confidence}
    assert _unconfirmed_mappings([mapping]) == [mapping]
    assert _unconfirmed_mappings([{**mapping, "confirmed": True}]) == []


@pytest.mark.parametrize("confidence", [0.9, 1, "0.99"])
def test_confident_mapping_can_proceed(confidence):
    assert not _unconfirmed_mappings([{"source": "名字", "confidence": confidence}])


@pytest.mark.parametrize("value", ["NaN", "Infinity", Decimal("NaN"), Decimal("Infinity")])
def test_nonfinite_numbers_are_field_errors(value):
    adapter = TargetAdapter()
    adapter.fields = (TargetField("quantity", "数量", type="number", scale=2),)
    assert adapter.validate({"quantity": value})[0]["code"] == "ELT_NUMBER_INVALID"
    with pytest.raises(EltError):
        strict_decimal(value)
    with pytest.raises(EltError):
        apply_transform(value, {"op": "number"}, {})


def test_large_decimal_scale_is_not_rounded_by_context():
    adapter = TargetAdapter()
    adapter.fields = (TargetField("price", "金额", type="number", scale=2),)
    assert adapter.validate({"price": "123456789012345678901234567890.001"})
    assert adapter.validate({"price": "0.00000"}) == []


def test_custom_full_datetime_format_survives_date_transform():
    rule = {"op": "date", "formats": ["%d-%m-%Y %H:%M"]}
    assert apply_transform("07-11-2026 08:30", rule, {}) == "2026-11-07"
    assert (
        apply_transform("07-11-2026 08:30", {**rule, "op": "datetime"}, {}) == "2026-11-07 08:30:00"
    )


@pytest.mark.parametrize("change", [{"unit_price": "12"}, {"amount": "24"}, {"tin_spec": "5"}])
def test_shipment_different_business_values_are_not_silently_skipped(monkeypatch, change):
    from app.application.elt.targets import orders

    monkeypatch.setattr(orders, "tenant_id_for_write", lambda: 1)
    adapter, db, context = orders.ShipmentAdapter(), MagicMock(), {}
    query = db.query.return_value
    query.filter.return_value = query
    query.first.return_value = None
    row = {
        "purchase_unit": "合成客户",
        "product_name": "合成商品",
        "quantity_kg": "2",
        "unit_price": "10",
        "amount": "20",
        "tin_spec": "1",
    }

    def preview(data):
        return adapter.preview(db, data, allowed_update_fields=set(), context=context).action

    assert preview(row) == "new"
    assert preview({**row, **change}) == "new"
    assert preview(row) == "skip"


def test_purchase_different_quantities_are_not_silently_skipped():
    from app.application.elt.targets.orders import PurchaseOrderAdapter

    adapter, db, context = PurchaseOrderAdapter(), MagicMock(), {}
    db.query.return_value.filter.return_value.first.side_effect = [
        None,
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
        None,
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
        None,
    ]
    row = {
        "external_order_no": "PO-synthetic",
        "supplier_name": "合成供应商",
        "product_name": "合成商品",
        "order_date": "2026-11-07",
        "quantity": "1",
    }

    def preview(data):
        return adapter.preview(db, data, allowed_update_fields=set(), context=context).action

    assert preview(row) == "new"
    assert preview({**row, "quantity": "2"}) == "new"
    assert preview(row) == "skip"


def test_attendance_distinct_clock_times_survive_preview():
    from app.application.elt.targets.batch import AttendanceAdapter

    adapter, context = AttendanceAdapter(), {"upload_path": "synthetic.xlsx"}
    row = {"employee_name": "合成员工", "work_date": "2026-11-07", "clock_in": "08:00"}

    def preview(data):
        return adapter.preview(None, data, allowed_update_fields=set(), context=context).action

    assert preview(row) == "new"
    assert preview({**row, "clock_in": "13:00"}) == "new"
    assert preview(row) == "skip"
