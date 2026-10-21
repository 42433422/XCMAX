from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.application.ports.shipment_record_store import ShipmentRecordStorePort
from app.db.models import ShipmentRecord
from app.db.session import get_db
from app.domain.shipment.shipment_quantities import (
    resolve_shipment_quantity,
    validate_shipment_products,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class SQLAlchemyShipmentRecordStore(ShipmentRecordStorePort):
    """出货记录写入（SQLAlchemy 实现）。"""

    def record_document_generation(
        self,
        *,
        unit_name: str,
        unit_id: int | None,
        products: list[dict[str, Any]],
        document_result: dict[str, Any],
        raw_text: str = "",
    ) -> dict[str, Any]:
        validate_shipment_products(products)
        # 现有 schema 是“扁平记录”，历史上也通常只存首个产品 + 汇总
        first = (products or [{}])[0] or {}
        product_name = first.get("name") or first.get("product_name") or ""
        model_number = first.get("model_number") or first.get("型号") or ""
        quantity_tins, quantity_kg, tin_spec = resolve_shipment_quantity(first)
        unit_price = first.get("unit_price")
        if unit_price is None:
            unit_price = first.get("price", 0.0)
        amount = first.get("amount")
        if amount is None:
            try:
                amount = float(unit_price or 0) * float(quantity_kg or 0)
            except RECOVERABLE_ERRORS:
                amount = 0.0

        now = datetime.now()
        parsed_data_json = json.dumps(
            {
                "purchase_unit": unit_name,
                "products": products,
                "document": {
                    "doc_name": document_result.get("doc_name"),
                    "file_path": document_result.get("file_path"),
                    "order_number": document_result.get("order_number"),
                    "date": document_result.get("date"),
                    "total_amount": document_result.get("total_amount"),
                    "total_quantity": document_result.get("total_quantity"),
                },
            },
            ensure_ascii=False,
        )

        with get_db() as db:
            record = ShipmentRecord(
                purchase_unit=unit_name,
                unit_id=unit_id,
                product_name=product_name or unit_name,
                model_number=model_number,
                quantity_kg=float(quantity_kg or 0.0),
                quantity_tins=int(quantity_tins or 0),
                tin_spec=tin_spec,
                unit_price=float(unit_price or 0.0),
                amount=float(amount or 0.0),
                status="pending",
                created_at=now,
                updated_at=now,
                raw_text=raw_text or "",
                parsed_data=parsed_data_json,
            )
            from app.infrastructure.tenant_scope import current_tenant_id

            tenant_id = current_tenant_id()
            if isinstance(tenant_id, int):
                record.tenant_id = tenant_id
            db.add(record)
            db.commit()
            db.refresh(record)
            record_id = record.id

        return {"success": True, "record_id": record_id}
