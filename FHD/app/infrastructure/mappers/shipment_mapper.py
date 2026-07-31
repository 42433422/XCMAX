from typing import Any

from app.db.models import ShipmentRecord
from app.domain.shipment.aggregates import Shipment, ShipmentItem
from app.legacy.domain.legacy_vo import ContactInfo, Money, OrderNumber, Quantity


def shipment_to_domain(db_record: ShipmentRecord) -> Shipment:
    shipment = Shipment(
        id=db_record.id,
        order_number=OrderNumber(str(db_record.id)),
        purchase_unit_name=db_record.purchase_unit or "",
        contact_info=ContactInfo.empty(),
        status=db_record.status or "pending",
        created_at=db_record.created_at,
        updated_at=db_record.updated_at,
        printed_at=db_record.printed_at,
        printer_name=db_record.printer_name,
        raw_text=db_record.raw_text,
    )
    product_name = str(db_record.product_name or "").strip()
    if product_name:
        shipment.add_item(
            ShipmentItem(
                product_name=product_name,
                model_number=str(db_record.model_number or ""),
                quantity=Quantity(
                    tins=int(db_record.quantity_tins or 0),
                    kg=float(db_record.quantity_kg or 0),
                    spec_per_tin=float(db_record.tin_spec or 0),
                ),
                unit_price=Money(float(db_record.unit_price or 0)),
                amount=Money(float(db_record.amount or 0)),
            )
        )
        shipment.created_at = db_record.created_at
        shipment.updated_at = db_record.updated_at
    return shipment


def shipment_to_db(shipment: Shipment) -> dict[str, Any]:
    item = shipment.items[0] if shipment.items else None
    return {
        "purchase_unit": shipment.purchase_unit_name,
        "product_name": item.product_name if item else "",
        "model_number": item.model_number if item else "",
        "quantity_kg": shipment.total_quantity.kg,
        "quantity_tins": shipment.total_quantity.tins,
        "tin_spec": item.quantity.spec_per_tin if item else 0,
        "unit_price": item.unit_price.amount if item else 0,
        "amount": shipment.total_amount.amount,
        "status": shipment.status,
        "created_at": shipment.created_at,
        "updated_at": shipment.updated_at,
        "printed_at": shipment.printed_at,
        "printer_name": shipment.printer_name,
        "raw_text": shipment.raw_text,
    }
