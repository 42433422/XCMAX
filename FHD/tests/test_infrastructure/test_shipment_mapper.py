from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.infrastructure.mappers.shipment_mapper import shipment_to_db, shipment_to_domain
from app.legacy.domain.legacy_vo import ContactInfo, OrderNumber


def _shipment_record(**overrides):
    now = datetime.now()
    values = {
        "id": 5,
        "purchase_unit": "金汉武家私",
        "product_name": "黑棕面用修色精",
        "model_number": "方和",
        "quantity_kg": 12.0,
        "quantity_tins": 3,
        "tin_spec": 4.0,
        "unit_price": Decimal("48.00"),
        "amount": Decimal("576.00"),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "printed_at": None,
        "printer_name": None,
        "raw_text": "真实打单",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_shipment_to_domain_rebuilds_complete_shipment_item():
    record = _shipment_record()

    shipment = shipment_to_domain(record)

    assert isinstance(shipment.order_number, OrderNumber)
    assert isinstance(shipment.contact_info, ContactInfo)
    assert shipment.contact_info == ContactInfo.empty()
    assert shipment.created_at == record.created_at
    assert shipment.updated_at == record.updated_at
    assert len(shipment.items) == 1
    item = shipment.items[0]
    assert item.product_name == "黑棕面用修色精"
    assert item.model_number == "方和"
    assert item.quantity.tins == 3
    assert item.quantity.kg == 12.0
    assert item.quantity.spec_per_tin == 4.0
    assert item.unit_price.amount == 48.0
    assert item.amount.amount == 576.0
    assert shipment.total_quantity.tins == 3
    assert shipment.total_quantity.kg == 12.0
    assert shipment.total_amount.amount == 576.0


def test_print_status_round_trip_preserves_business_fields():
    record = _shipment_record()
    shipment = shipment_to_domain(record)

    shipment.mark_as_printed("Canon_TS3700_series")
    mapped = shipment_to_db(shipment)

    assert mapped["purchase_unit"] == record.purchase_unit
    assert mapped["product_name"] == record.product_name
    assert mapped["model_number"] == record.model_number
    assert mapped["quantity_kg"] == record.quantity_kg
    assert mapped["quantity_tins"] == record.quantity_tins
    assert mapped["tin_spec"] == record.tin_spec
    assert mapped["unit_price"] == record.unit_price
    assert mapped["amount"] == record.amount
    assert mapped["status"] == "printed"
    assert mapped["printer_name"] == "Canon_TS3700_series"


def test_shipment_to_domain_allows_legacy_empty_product_rows():
    record = _shipment_record(
        product_name="",
        model_number="",
        quantity_kg=0,
        quantity_tins=0,
        tin_spec=0,
        unit_price=0,
        amount=0,
    )

    shipment = shipment_to_domain(record)

    assert shipment.items == []
    assert shipment.total_amount.amount == 0
    assert shipment.total_quantity.kg == 0
