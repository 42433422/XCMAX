import json
from datetime import datetime
from typing import Any

from app.db.models import ShipmentRecord
from app.domain.shipment.aggregates import Shipment, ShipmentItem
from app.legacy.domain.legacy_vo import ContactInfo, Money, OrderNumber, Quantity


def shipment_to_domain(db_record: ShipmentRecord) -> Shipment:
    try:
        parsed = json.loads(db_record.parsed_data or "{}")
    except (TypeError, ValueError):
        parsed = {}
    parsed = parsed if isinstance(parsed, dict) else {}
    products = parsed.get("items") or parsed.get("products") or []
    if len(products) <= 1 and db_record.product_name:
        products = [
            {
                "product_name": db_record.product_name,
                "model_number": db_record.model_number,
                "quantity_tins": db_record.quantity_tins,
                "tin_spec": db_record.tin_spec,
                "unit_price": float(db_record.unit_price or 0),
                "amount": float(db_record.amount or 0),
            }
        ]
    return Shipment(
        id=db_record.id,
        order_number=OrderNumber(str(db_record.id)),
        purchase_unit_name=db_record.purchase_unit or "",
        contact_info=ContactInfo(parsed.get("contact_person", ""), parsed.get("contact_phone", "")),
        items=[ShipmentItem.from_dict(item) for item in products],
        total_quantity=Quantity(db_record.quantity_tins, db_record.quantity_kg, db_record.tin_spec),
        total_amount=Money(float(db_record.amount or 0)),
        status=db_record.status or "pending",
        created_at=db_record.created_at or datetime.now(),
        updated_at=db_record.updated_at or datetime.now(),
        printed_at=db_record.printed_at,
        printer_name=db_record.printer_name,
        raw_text=db_record.raw_text,
        metadata=parsed,
    )


def shipment_to_db(shipment: Shipment) -> dict[str, Any]:
    return {
        "purchase_unit": shipment.purchase_unit_name,
        "product_name": shipment.items[0].product_name if shipment.items else "",
        "model_number": shipment.items[0].model_number if shipment.items else "",
        "quantity_kg": shipment.total_quantity.kg,
        "quantity_tins": shipment.total_quantity.tins,
        "tin_spec": shipment.total_quantity.spec_per_tin,
        "unit_price": shipment.items[0].unit_price.amount if shipment.items else 0,
        "amount": shipment.total_amount.amount,
        "status": shipment.status,
        "created_at": shipment.created_at,
        "updated_at": shipment.updated_at,
        "printed_at": shipment.printed_at,
        "printer_name": shipment.printer_name,
        "raw_text": shipment.raw_text,
        "parsed_data": json.dumps({**shipment.metadata, **shipment.to_dict()}, ensure_ascii=False),
    }
