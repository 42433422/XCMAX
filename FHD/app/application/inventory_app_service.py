"""库存 HTTP 应用服务 — 委托 InventoryService facade（读路径）；写路径可逐步切 v2 事件驱动。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.facades.inventory_facade import InventoryService
from app.utils.operational_errors import RECOVERABLE_ERRORS


class InventoryAppService:
    def __init__(self) -> None:
        self._facade = InventoryService()

    def get_inventory(self, **kwargs: Any) -> dict:
        return self._facade.get_inventory(**kwargs)

    def export_inventory(self, *, output_format: str = "xlsx", **filters: Any) -> dict:
        from app.domain.app_pure.inventory_export import (
            render_inventory_csv,
            render_inventory_workbook,
        )

        renderer = {"xlsx": render_inventory_workbook, "csv": render_inventory_csv}[output_format]

        result = self._facade.get_inventory_export(**filters)
        if not result.get("success"):
            return result
        return {
            "success": True,
            "total": result["total"],
            "content": renderer(result["data"]),
        }

    def get_inventory_summary(self, warehouse_id: int | None = None) -> dict:
        return self._facade.get_inventory_summary(warehouse_id=warehouse_id)

    def get_inventory_transactions(self, **kwargs: Any) -> dict:
        return self._facade.get_inventory_transactions(**kwargs)

    def get_inventory_alert(self) -> dict:
        return self._facade.get_inventory_alert()

    def get_combined_alert(self, threshold: float | None = None) -> dict:
        inv_result = self.get_inventory_alert()
        inv_items = inv_result.get("data") or inv_result.get("alerts") or []
        mat_items: list = []
        try:
            from app.application import get_material_application_service

            mat_result = get_material_application_service().get_low_stock_materials(
                threshold=threshold
            )
            mat_items = mat_result.get("data") or []
        except RECOVERABLE_ERRORS:
            pass
        return {
            "success": True,
            "inventory_alerts": inv_items,
            "material_low_stock": mat_items,
            "total_alerts": len(inv_items) + len(mat_items),
        }

    def get_storage_locations(self, **kwargs: Any) -> dict:
        return self._facade.get_storage_locations(**kwargs)

    def create_storage_location(self, body: dict) -> dict:
        return self._facade.create_storage_location(body)

    def update_storage_location(self, location_id: int, body: dict) -> dict:
        return self._facade.update_storage_location(location_id, body)

    def get_warehouses(self, status: str | None = None) -> dict:
        return self._facade.get_warehouses(status=status)

    def get_warehouse(self, warehouse_id: int) -> dict:
        return self._facade.get_warehouse(warehouse_id)

    def create_warehouse(self, body: dict) -> dict:
        return self._facade.create_warehouse(body)

    def update_warehouse(self, warehouse_id: int, body: dict) -> dict:
        return self._facade.update_warehouse(warehouse_id, body)

    def delete_warehouse(self, warehouse_id: int) -> dict:
        return self._facade.delete_warehouse(warehouse_id)

    def inventory_in(self, **kwargs: Any) -> dict:
        return self._facade.inventory_in(**kwargs)

    def inventory_out(self, **kwargs: Any) -> dict:
        return self._facade.inventory_out(**kwargs)

    def inventory_transfer(self, **kwargs: Any) -> dict:
        return self._facade.inventory_transfer(**kwargs)

    @staticmethod
    def parse_optional_datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None


def verify_agent_stock_movement(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read the original claim and current stock; never post another movement."""
    from decimal import Decimal

    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.tool_permission import (
        _fingerprint,
        _reread_claim,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.agent_orchestrator.verification_transactions import (
        _decimal,
        _transaction_read_scope,
    )
    from app.db.models import (
        InventoryLedger,
        InventoryTransaction,
        Product,
        StorageLocation,
        Warehouse,
    )
    from app.domain.shared_services.inventory_movements import _positive_id, _stock_out_warehouse_id

    source, params, data = "inventory_sql", step.params, output.get("data")
    inbound = step.action == "stock_in"
    if (
        not isinstance(data, dict)
        or type(data.get("ledger_id")) is not int
        or data["ledger_id"] <= 0
    ):
        return _report("inconclusive", "result_inventory_identity_missing", source)
    if not inbound and data.get("already_posted"):
        return _report("inconclusive", "result_inventory_movement_unavailable", source)
    key = idempotency_scope_key(context, step.tool_id, step.action, params)
    receipt = _reread_claim(key, durable_read_only=True)
    if receipt is None or receipt.get("inflight") or not isinstance(receipt.get("output"), dict):
        return _report("inconclusive", "result_receipt_unavailable", source)
    if receipt.get("fingerprint") != _fingerprint(params, context) or canonical_hash(
        receipt["output"]
    ) != canonical_hash(output):
        return _report("failed", "result_receipt_mismatch", source)
    quantity = _decimal(params.get("quantity"))
    total = _decimal(data.get("total_quantity" if inbound else "remaining_quantity")).quantize(
        Decimal("0.0001")
    )
    if quantity <= 0 or _decimal(data.get("quantity")) != quantity:
        return _report("failed", "result_inventory_state_mismatch", source)
    signed_quantity = quantity if inbound else -quantity
    with _transaction_read_scope(context, {"tool.inventory.query_transactions"}, "inventory") as (
        db,
        tenant,
    ):
        ledger = (
            db.query(InventoryLedger)
            .filter_by(id=data["ledger_id"], tenant_id=tenant)
            .one_or_none()
        )
        if ledger is None:
            return _report("failed", "result_inventory_state_mismatch", source)
        for model, key_name, label_name, row_id in (
            (Product, "product_id", "model_number", ledger.product_id),
            (Warehouse, "warehouse_id", "warehouse_name", ledger.warehouse_id),
        ):
            query = db.query(model).filter(model.tenant_id == tenant)
            if model is Warehouse and not inbound:
                warehouse_id, _, _ = _stock_out_warehouse_id(db, params.get(key_name))
                query = query.filter(model.id == warehouse_id)
            elif params.get(key_name) is not None:
                query = query.filter(model.id == _positive_id(params[key_name]))
            else:
                column = Product.model_number if model is Product else Warehouse.name
                query = query.filter(column == params.get(label_name))
            rows = query.limit(2).all()
            if len(rows) != 1 or rows[0].id != row_id:
                return _report("failed", "result_inventory_identity_mismatch", source)
            row = rows[0]
            label = row.model_number if model is Product else row.name
            if params.get(label_name) and params[label_name] != label:
                return _report("failed", "result_inventory_identity_mismatch", source)
            if model is Warehouse and row.status != "active":
                return _report("failed", "result_inventory_state_mismatch", source)
        if (
            ((inbound or params.get("batch_no")) and ledger.batch_no != params.get("batch_no"))
            or _decimal(ledger.quantity) != total
            or _decimal(ledger.available_quantity) < 0
            or _decimal(ledger.reserved_quantity) < 0
            or _decimal(ledger.available_quantity) + _decimal(ledger.reserved_quantity) != total
        ):
            return _report("failed", "result_inventory_state_mismatch", source)
        if params.get("location_id") is not None:
            location = (
                db.query(StorageLocation)
                .filter_by(
                    id=_positive_id(params["location_id"]),
                    tenant_id=tenant,
                    warehouse_id=ledger.warehouse_id,
                )
                .one_or_none()
            )
            if location is None or location.id != ledger.location_id:
                return _report("failed", "result_inventory_identity_mismatch", source)
        movements = (
            db.query(InventoryTransaction)
            .filter_by(
                tenant_id=tenant,
                ledger_id=ledger.id,
                transaction_type="in" if inbound else "out",
                document_posting=not inbound,
                product_id=ledger.product_id,
                warehouse_id=ledger.warehouse_id,
                quantity=signed_quantity,
                after_quantity=total,
                **{
                    name: params.get(name)
                    for name in (
                        "batch_no",
                        "location_id",
                        "reference_type",
                        "reference_id",
                        "operator",
                        "remark",
                    )
                },
            )
            .limit(2)
            .all()
        )
        # The original API returns a ledger id, not a movement id. Ambiguous
        # matches cannot become proof of a particular movement or its authorship.
        if len(movements) != 1:
            return _report("inconclusive", "result_inventory_movement_unavailable", source)
        movement = movements[0]
        price = _decimal(params["unit_price"]) if params.get("unit_price") is not None else None
        amount = (quantity * price).quantize(Decimal("0.01")) if price else None
        if (
            _decimal(movement.before_quantity) + signed_quantity
            != _decimal(movement.after_quantity)
            or movement.unit_price
            != (price.quantize(Decimal("0.0001")) if price is not None else None)
            or movement.total_amount != amount
        ):
            return _report("failed", "result_inventory_state_mismatch", source)
        return _report(
            "verified",
            "result_verified",
            source,
            tenant_id=str(tenant),
            ledger_id=ledger.id,
            movement_id=movement.id,
            product_id=ledger.product_id,
            warehouse_id=ledger.warehouse_id,
            quantity=str(quantity),
            total_quantity=str(total),
            scope="current_inventory_state",
            attribution="not_inferred",
            receipt_sha256=canonical_hash(receipt["output"]),
            receipt_key_sha256=canonical_hash(key),
        )
