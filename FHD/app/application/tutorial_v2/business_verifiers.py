"""Sales, import, and evidence-trace verifiers for Tutorial V2."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.tutorial_v2.common import SALES_SENTENCE
from app.application.tutorial_v2.common import json_load as _load_json
from app.db.models.accounting import JournalEntry
from app.db.models.agent import AgentTaskExecutionRecord, AgentTaskRecord
from app.db.models.approval import ApprovalRequest
from app.db.models.customer import Customer
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.db.models.inventory import InventoryLedger
from app.db.models.product import Product
from app.db.models.receivable_allocation import ReceivableAllocation
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.tutorial import TutorialRun
from app.infrastructure.tenant_scope import tenant_scope


class TutorialBusinessVerifierMixin:
    if TYPE_CHECKING:
        _observed_task_execution_count: Any

    def _sales_entities(self, db: Session, run: TutorialRun) -> dict[str, Any]:
        tenant_id = run.workspace.tutorial_tenant_id
        with tenant_scope(tenant_id):
            customer_rows = db.query(Customer).filter(Customer.customer_name == "客户B").all()
            product_rows = db.query(Product).filter(Product.name == "A 产品").all()
            inventory_rows = []
            if len(product_rows) == 1:
                inventory_rows = (
                    db.query(InventoryLedger)
                    .filter(InventoryLedger.product_id == product_rows[0].id)
                    .all()
                )
            orders = db.query(SalesOrder).filter(SalesOrder.customer_name == "客户B").all()
            items = []
            allocations = []
            entries = []
            if len(orders) == 1:
                items = (
                    db.query(SalesOrderItem).filter(SalesOrderItem.order_id == orders[0].id).all()
                )
                allocations = (
                    db.query(ReceivableAllocation)
                    .filter(ReceivableAllocation.sales_order_id == orders[0].id)
                    .all()
                )
                entries = (
                    db.query(JournalEntry)
                    .filter(
                        (JournalEntry.reference_type == "sale")
                        & (JournalEntry.reference_id == orders[0].id)
                        | JournalEntry.id.in_(
                            [row.journal_entry_id for row in allocations if row.journal_entry_id]
                        )
                    )
                    .all()
                )
        return {
            "customers": customer_rows,
            "products": product_rows,
            "inventory": inventory_rows,
            "orders": orders,
            "items": items,
            "allocations": allocations,
            "entries": entries,
        }

    def _verify_sales_waiting(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        tenant_id = run.workspace.tutorial_tenant_id
        with tenant_scope(tenant_id):
            approvals = (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.status.in_(["pending", "in_progress"]))
                .all()
            )
            matching = [
                item
                for item in approvals
                if SALES_SENTENCE in str(item.business_data or "")
                or SALES_SENTENCE in str(item.description or "")
                or SALES_SENTENCE in str(item.title or "")
            ]
            order_count = db.query(SalesOrder).filter(SalesOrder.customer_name == "客户B").count()
            item_count = db.query(SalesOrderItem).count()
            allocation_count = db.query(ReceivableAllocation).count()
            voucher_count = db.query(JournalEntry).count()
            products = db.query(Product).filter(Product.name == "A 产品").all()
            inventory_rows = []
            if len(products) == 1:
                inventory_rows = (
                    db.query(InventoryLedger)
                    .filter(InventoryLedger.product_id == products[0].id)
                    .all()
                )
        inventory = int(inventory_rows[0].quantity or 0) if len(inventory_rows) == 1 else -1
        ok = (
            len(matching) == 1
            and order_count == 0
            and item_count == 0
            and allocation_count == 0
            and voucher_count == 0
            and inventory == 100
        )
        return (
            ok,
            "verification_passed" if ok else "approval_not_ready",
            [{"type": "approval_request", "id": matching[0].id}] if ok else [],
            {
                "pending_approval_count": len(matching),
                "sales_order_count": order_count,
                "sales_order_item_count": item_count,
                "allocation_count": allocation_count,
                "journal_entry_count": voucher_count,
                "inventory": inventory,
            },
        )

    def _verify_sales_approval_reviewed(
        self, db: Session, run: TutorialRun, context: dict[str, Any]
    ):
        ok, _code, refs, counts = self._verify_sales_waiting(db, run, context)
        detail_opened = bool(context.get("target_visible")) and self._visited(
            context, {"approval-workspace"}
        )
        return (
            bool(ok and detail_opened),
            "verification_passed" if ok and detail_opened else "approval_detail_not_viewed",
            refs if ok and detail_opened else [],
            {**counts, "approval_detail_opened": int(detail_opened)},
        )

    def _closed_loop_result(self, db: Session, run: TutorialRun):
        data = self._sales_entities(db, run)
        products = data["products"]
        inventory_rows = data["inventory"]
        orders = data["orders"]
        items = data["items"]
        allocations = data["allocations"]
        entries = data["entries"]
        order = orders[0] if len(orders) == 1 else None
        product = products[0] if len(products) == 1 else None
        inventory = inventory_rows[0] if len(inventory_rows) == 1 else None
        item_ok = (
            len(items) == 1
            and Decimal(str(items[0].quantity or 0)) == Decimal("10")
            and Decimal(str(items[0].unit_price or 0)) == Decimal("100")
        )
        allocation_ok = (
            len(allocations) == 1
            and Decimal(str(allocations[0].allocated_amount or 0)) == Decimal("1000")
            and allocations[0].status == "paid"
        )
        entries_ok = len(entries) >= 2 and all(
            entry.status == "posted"
            and Decimal(str(entry.debit_total or 0)) == Decimal(str(entry.credit_total or 0))
            for entry in entries
        )
        ok = bool(
            len(data["customers"]) == 1
            and product is not None
            and inventory is not None
            and int(inventory.quantity or 0) == 90
            and int(inventory.available_quantity or 0) == 90
            and order is not None
            and order.invoice_status == "invoiced"
            and order.payment_state == "paid"
            and Decimal(str(order.total_amount or 0)) == Decimal("1000")
            and item_ok
            and allocation_ok
            and entries_ok
        )
        refs: list[dict[str, Any]] = []
        if ok and order is not None and product is not None and inventory is not None:
            refs = [
                {"type": "sales_order", "id": order.id},
                {"type": "sales_order_item", "id": items[0].id},
                {"type": "product", "id": product.id},
                {"type": "inventory_ledger", "id": inventory.id},
                {"type": "receivable_allocation", "id": allocations[0].id},
                *[
                    {
                        "type": "journal_entry",
                        "id": entry.id,
                        "role": "invoice" if entry.reference_type == "sale" else "payment",
                    }
                    for entry in entries
                ],
            ]
        invoice_vouchers = sum(entry.reference_type == "sale" for entry in entries)
        payment_vouchers = sum(entry.reference_type == "payment" for entry in entries)
        counts = {
            "sales_order_count": len(orders),
            "sales_order_item_count": len(items),
            "inventory": int(inventory.quantity or 0) if inventory else -1,
            "allocation_count": len(allocations),
            "journal_entry_count": len(entries),
            "invoice_voucher_count": invoice_vouchers,
            "payment_voucher_count": payment_vouchers,
            "balanced_journal_entry_count": sum(
                Decimal(str(entry.debit_total or 0)) == Decimal(str(entry.credit_total or 0))
                for entry in entries
            ),
            "order_total": float(order.total_amount or 0) if order else 0,
            "invoice_status": str(order.invoice_status or "") if order else "",
            "payment_state": str(order.payment_state or "") if order else "",
            "allocated_amount": float(allocations[0].allocated_amount or 0)
            if len(allocations) == 1
            else 0,
        }
        return ok, refs, counts

    def _verify_sales_closed_loop(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "sales_result_not_ready", refs, counts

    def _etl_rows(self, db: Session, run: TutorialRun) -> list[EtlRun]:
        with tenant_scope(run.workspace.tutorial_tenant_id):
            return cast(
                list[EtlRun],
                db.query(EtlRun)
                .join(EtlUpload, EtlUpload.id == EtlRun.upload_id)
                .filter(EtlRun.owner_user_id == run.user_id)
                .filter(EtlUpload.file_name.like("xcagi-tutorial-business-import%"))
                .order_by(EtlRun.created_at.desc())
                .all(),
            )

    def _verify_etl_preview(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        runs = self._etl_rows(db, run)
        previews = [item for item in runs if item.status in {"preview_ready", "completed"}]
        row_count = 0
        if previews:
            with tenant_scope(run.workspace.tutorial_tenant_id):
                row_count = db.query(EtlRunRow).filter(EtlRunRow.run_id == previews[0].id).count()
        ok = bool(previews) and row_count > 0
        return (
            ok,
            "verification_passed" if ok else "etl_preview_not_ready",
            [{"type": "etl_run", "id": previews[0].id}] if ok else [],
            {"preview_run_count": len(previews), "preview_row_count": row_count},
        )

    def _verify_etl_completed(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        runs = self._etl_rows(db, run)
        completed = [item for item in runs if item.status == "completed"]
        successful = 0
        referenced = 0
        error_rows = 0
        if completed:
            with tenant_scope(run.workspace.tutorial_tenant_id):
                rows = db.query(EtlRunRow).filter(EtlRunRow.run_id == completed[0].id).all()
            successful = sum(row.execution_status == "success" for row in rows)
            referenced = sum(bool(row.match_ref or _load_json(row.after_json, {})) for row in rows)
            error_rows = sum(row.execution_status == "failed" for row in rows)
        ok = bool(completed) and successful > 0 and referenced > 0
        return (
            ok,
            "verification_passed" if ok else "etl_result_not_ready",
            [{"type": "etl_run", "id": completed[0].id}] if ok else [],
            {
                "completed_run_count": len(completed),
                "successful_row_count": successful,
                "referenced_row_count": referenced,
                "error_row_count": error_rows,
            },
        )

    def _visited(
        self, context: dict[str, Any], expected: set[str], *, require_target: bool = False
    ) -> bool:
        route_ok = str(context.get("visited_route") or "") in expected
        return route_ok and (not require_target or bool(context.get("target_visible")))

    def _verify_trace_task(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"chat", "task-workspace"}, require_target=True):
            return False, "trace_view_required", [], {}
        tasks = (
            db.query(AgentTaskRecord)
            .filter(
                AgentTaskRecord.tenant_id == str(run.workspace.tutorial_tenant_id),
                AgentTaskRecord.user_id == str(run.user_id),
                AgentTaskRecord.status == "completed",
            )
            .order_by(AgentTaskRecord.updated_at.desc())
            .all()
        )
        matching = [
            task
            for task in tasks
            if SALES_SENTENCE in str(task.title or "")
            or SALES_SENTENCE in str(task.metadata_json or "")
        ]
        execution_count = 0
        if len(matching) == 1:
            execution_count = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.task_id == matching[0].task_id)
                .count()
            )
            execution_count += self._observed_task_execution_count(db, run, matching[0])
        ok = len(matching) == 1 and execution_count > 0
        return (
            ok,
            "verification_passed" if ok else "trace_result_not_ready",
            [{"type": "agent_task", "id": matching[0].task_id}] if ok else [],
            {"sales_task_count": len(matching), "execution_count": execution_count},
        )

    def _verify_trace_approval(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"approval-workspace"}, require_target=True):
            return False, "trace_view_required", [], {}
        with tenant_scope(run.workspace.tutorial_tenant_id):
            rows = db.query(ApprovalRequest).filter(ApprovalRequest.status == "approved").all()
        matching = [row for row in rows if SALES_SENTENCE in str(row.business_data or "")]
        ok = len(matching) == 1
        return (
            ok,
            "verification_passed" if ok else "trace_result_not_ready",
            [{"type": "approval_request", "id": matching[0].id}] if ok else [],
            {"approved_request_count": len(matching)},
        )

    def _verify_trace_order(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"orders"}, require_target=True):
            return False, "trace_view_required", [], {}
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "trace_result_not_ready", refs, counts

    def _verify_trace_inventory(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"inventory"}, require_target=True):
            return False, "trace_view_required", [], {}
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "trace_result_not_ready", refs, counts

    def _verify_trace_finance(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"kitten-finance"}, require_target=True):
            return False, "trace_view_required", [], {}
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "trace_result_not_ready", refs, counts

    def _verify_trace_import(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"business-docking"}, require_target=True):
            return False, "trace_view_required", [], {}
        return self._verify_etl_completed(db, run, context)
