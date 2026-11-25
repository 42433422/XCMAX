"""Atomic supplier return against the original approved inbound receipt.

The same source receipt identity governs stock movements and AP reversal.
No independent stock or finance ledger is created. Never call outside the
authorized purchase ToolSpec runtime; its approval is independently rechecked.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.db.models import (
    InventoryLedger, InventoryTransaction, PurchaseInbound, PurchaseInboundItem,
    PurchaseReturn, PurchaseReturnItem, Supplier, Warehouse,
)
from app.db.models.approval import ApprovalAction, ApprovalRecord, ApprovalRequest, ApprovalStatus
from app.db.session import get_db
from app.domain.shared_services.inventory_movements import _move_available
from app.infrastructure.tenant_scope import current_tenant_id


class PurchaseReturnRefused(ValueError):
    """No externally visible stock or accounting side effect is authorized."""


def _items_by_source(value: Any) -> dict[int, Decimal]:
    if not isinstance(value, list) or not value:
        raise PurchaseReturnRefused("采购退货必须提供原入库行和正数数量")
    parsed: dict[int, Decimal] = {}
    for row in value:
        if (
            not isinstance(row, dict)
            or type(row.get("inbound_item_id")) is not int
            or row["inbound_item_id"] <= 0
            or set(row) != {"inbound_item_id", "quantity"}
        ):
            raise PurchaseReturnRefused("退货行只能包含原入库行 ID 和数量")
        item_id = row["inbound_item_id"]
        if item_id in parsed:
            raise PurchaseReturnRefused("退货原入库行不能重复")
        try:
            quantity = Decimal(str(row["quantity"]))
            if (
                isinstance(row["quantity"], bool)
                or not quantity.is_finite()
                or quantity <= 0
                or quantity != quantity.quantize(Decimal("0.0001"))
            ):
                raise ValueError("invalid quantity")
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PurchaseReturnRefused("退货数量必须是正数且最多四位小数") from exc
        parsed[item_id] = quantity
    return parsed


def _replay_matches(original: PurchaseReturn, source: dict[int, Decimal]) -> bool:
    return original.status == "posted" and len(original.items) == len(source) and all(
        item.inbound_item_id in source
        and Decimal(str(item.quantity)) == source[item.inbound_item_id]
        for item in original.items
    )


def post_purchase_return(data: dict[str, Any]) -> dict[str, Any]:
    """Post receipt-specific goods out and reverse AP in one SQL transaction.

    Input must match the exact approved snapshot: return_no, inbound_id, items.
    Replayed return identities return their original receipt, never post twice.
    """
    from app.db.models.accounting import JournalEntry
    from app.db.models.user import User
    from app.domain.shared_services.accounting_services import create_journal_entry
    from app.domain.shared_services.purchase_service import _line_amount, _write_lock

    tenant_id = current_tenant_id()
    if type(tenant_id) is not int or tenant_id <= 0:
        return {"success": False, "reason_code": "tenant_context_required"}
    try:
        return_no = str(data.get("return_no") or "").strip()
        inbound_id = data.get("inbound_id")
        approval_id = data.get("approval_request_id")
        if (
            not return_no or len(return_no) > 50
            or type(inbound_id) is not int or inbound_id <= 0
            or type(approval_id) is not int or approval_id <= 0
        ):
            raise PurchaseReturnRefused("退货单及原审批、入库身份不能为空")
        source = _items_by_source(data.get("items"))
    except (AttributeError, PurchaseReturnRefused) as exc:
        return {"success": False, "reason_code": "return_request_invalid", "message": str(exc)}

    with get_db() as db:
        try:
            _write_lock(db)
            # Lock the real approval and source receipt in the same unit of work.
            approval = (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.id == approval_id,
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.status == ApprovalStatus.APPROVED.value,
                    ApprovalRequest.business_type == "purchase_return",
                    ApprovalRequest.business_id == inbound_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if (
                approval is None or approval.approved_by is None
                or approval.applicant_id == approval.approved_by
                or db.query(ApprovalRecord.id).filter(
                    ApprovalRecord.request_id == approval_id,
                    ApprovalRecord.approver_id == approval.approved_by,
                    ApprovalRecord.action == ApprovalAction.APPROVE.value,
                    ApprovalRecord.tenant_id == tenant_id,
                    ApprovalRecord.is_passed.is_(True),
                ).first() is None
            ):
                raise PurchaseReturnRefused("原退货审批缺失、无独立批准人或无审计回执")
            # This decision remains valid only while its approving identity is
            # still active and belongs to the same source enterprise.
            live_reviewer = (
                db.query(User)
                .filter(
                    User.id == approval.approved_by,
                    User.is_active.is_(True),
                    User.tenant_id == tenant_id,
                )
                .with_for_update(read=True)
                .one_or_none()
            )
            if live_reviewer is None:
                raise PurchaseReturnRefused("原审批人已被撤权或转出企业，需重新审批")
            try:
                approved = json.loads(approval.business_data or "{}")
                approved_items = _items_by_source(approved.get("items"))
            except (ValueError, TypeError, AttributeError) as exc:
                raise PurchaseReturnRefused("原审批快照缺失或无效") from exc
            if (
                approved.get("return_no") != return_no
                or approved.get("inbound_id") != inbound_id
                or approved_items != source
            ):
                raise PurchaseReturnRefused("退货申请与原审批冻结明细不一致")

            existing = (
                db.query(PurchaseReturn)
                .filter(
                    PurchaseReturn.tenant_id == tenant_id,
                    PurchaseReturn.return_no == return_no,
                )
                .with_for_update()
                .one_or_none()
            )
            if existing is not None:
                if existing.approval_request_id == approval_id and existing.inbound_id == inbound_id and _replay_matches(existing, source):
                    return {
                        "success": True, "idempotent": True, "return_id": existing.id,
                        "journal_entry_id": existing.journal_entry_id,
                    }
                raise PurchaseReturnRefused("退货业务身份已使用且原始明细冲突")
            if db.query(PurchaseReturn.id).filter(
                PurchaseReturn.tenant_id == tenant_id,
                PurchaseReturn.approval_request_id == approval_id,
            ).first() is not None:
                raise PurchaseReturnRefused("审批凭证已用于其他退货单，禁止重复执行")
            receipt = (
                db.query(PurchaseInbound)
                .filter(
                    PurchaseInbound.id == inbound_id,
                    PurchaseInbound.tenant_id == tenant_id,
                    PurchaseInbound.status == "completed",
                )
                .with_for_update()
                .one_or_none()
            )
            if receipt is None:
                raise PurchaseReturnRefused("原入库单不存在或并非完成状态")
            supplier = db.query(Supplier).filter(
                Supplier.id == receipt.supplier_id,
                Supplier.tenant_id == tenant_id,
                Supplier.status == "active",
            ).one_or_none()
            warehouse = db.query(Warehouse).filter(
                Warehouse.id == receipt.warehouse_id,
                Warehouse.tenant_id == tenant_id,
                Warehouse.status == "active",
            ).one_or_none()
            if supplier is None or warehouse is None:
                raise PurchaseReturnRefused("原供应商或原仓库不存在、已停用或跨租户")
            inbound_lines = {
                row.id: row for row in db.query(PurchaseInboundItem)
                .filter(
                    PurchaseInboundItem.inbound_id == inbound_id,
                    PurchaseInboundItem.tenant_id == tenant_id,
                    PurchaseInboundItem.id.in_(source),
                )
                .order_by(PurchaseInboundItem.id)
                .with_for_update().all()
            }
            if set(inbound_lines) != set(source):
                raise PurchaseReturnRefused("退货行与原已完成入库凭证不匹配")

            # Verify original posted batch movements and AP source before
            # reversing any stock or payable. A missing source blocks posting.
            expected_by_stock: dict[
                tuple[int, int, str | None, int | None], Decimal
            ] = {}
            for origin in receipt.items:
                if origin.tenant_id != tenant_id:
                    raise PurchaseReturnRefused("原入库行租户不一致")
                key = (
                    origin.product_id, receipt.warehouse_id,
                    origin.batch_no, origin.location_id,
                )
                expected_by_stock[key] = expected_by_stock.get(key, Decimal("0")) + Decimal(
                    str(origin.quantity)
                )
            observed_by_stock: dict[
                tuple[int, int, str | None, int | None], Decimal
            ] = {}
            transactions = db.query(InventoryTransaction).filter(
                InventoryTransaction.tenant_id == tenant_id,
                InventoryTransaction.reference_type == "purchase_inbound",
                InventoryTransaction.reference_id == receipt.id,
            ).all()
            for transaction in transactions:
                if transaction.transaction_type != "in":
                    raise PurchaseReturnRefused("原入库库存流水方向异常")
                key = (
                    transaction.product_id, transaction.warehouse_id,
                    transaction.batch_no, transaction.location_id,
                )
                observed_by_stock[key] = observed_by_stock.get(key, Decimal("0")) + Decimal(
                    str(transaction.quantity)
                )
            if not expected_by_stock or expected_by_stock != observed_by_stock:
                raise PurchaseReturnRefused("原入库批次流水未独立对齐，禁止退货")
            source_journals = db.query(JournalEntry).filter(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.reference_type == "purchase_inbound",
                JournalEntry.reference_id == receipt.id,
            ).all()
            original_total = Decimal(str(receipt.total_amount or 0))
            computed_original = sum(
                (
                    Decimal(str(line.quantity)) * Decimal(str(line.unit_price or 0))
                ).quantize(Decimal("0.01"))
                for line in receipt.items
            )
            if original_total != computed_original:
                raise PurchaseReturnRefused("原入库合计金额与原明细不一致")
            if original_total > 0:
                if len(source_journals) != 1:
                    raise PurchaseReturnRefused("原入库应付凭证缺失或重复")
                original_journal = source_journals[0]
                if (
                    original_journal.status != "posted"
                    or original_journal.reversed_at is not None
                    or Decimal(str(original_journal.debit_total or 0)) != original_total
                    or Decimal(str(original_journal.credit_total or 0)) != original_total
                    or sum(
                        (Decimal(str(line.debit or 0)) for line in original_journal.lines
                         if line.account_code == "1401"), Decimal("0")
                    ) != original_total
                    or sum(
                        (Decimal(str(line.credit or 0)) for line in original_journal.lines
                         if line.account_code == "2201"), Decimal("0")
                    ) != original_total
                ):
                    raise PurchaseReturnRefused("原入库应付凭证未过账或金额不匹配")
            elif source_journals:
                raise PurchaseReturnRefused("零金额入库存在来源不明的财务凭证")

            now = datetime.now()
            total = Decimal("0")
            posted = PurchaseReturn(
                tenant_id=tenant_id, return_no=return_no,
                approval_request_id=approval_id, inbound_id=inbound_id,
                supplier_id=receipt.supplier_id, warehouse_id=receipt.warehouse_id,
                total_amount=Decimal("0"), status="posted", posted_at=now,
            )
            db.add(posted)
            db.flush()
            for line_id, quantity in sorted(source.items()):
                origin = inbound_lines[line_id]
                previous = (
                    db.query(PurchaseReturnItem.quantity)
                    .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.return_id)
                    .filter(
                        PurchaseReturn.tenant_id == tenant_id,
                        PurchaseReturn.status == "posted",
                        PurchaseReturnItem.inbound_item_id == line_id,
                        PurchaseReturnItem.tenant_id == tenant_id,
                    ).all()
                )
                returned = sum((Decimal(str(row[0])) for row in previous), Decimal("0"))
                if returned + quantity > Decimal(str(origin.quantity)):
                    raise PurchaseReturnRefused("累计退货数量超出原入库行")
                ledgers = (
                    db.query(InventoryLedger)
                    .filter(
                        InventoryLedger.tenant_id == tenant_id,
                        InventoryLedger.product_id == origin.product_id,
                        InventoryLedger.warehouse_id == receipt.warehouse_id,
                        InventoryLedger.batch_no == origin.batch_no,
                        InventoryLedger.location_id == origin.location_id,
                    )
                    .with_for_update().limit(2).all()
                )
                if len(ledgers) != 1:
                    raise PurchaseReturnRefused("原批次或库位库存身份缺失或重复")
                ledger = ledgers[0]
                before = Decimal(str(ledger.quantity or 0))
                if not _move_available(db, ledger, -quantity, now):
                    raise PurchaseReturnRefused("原库存已预留、数量不足或并发改变")
                unit_price = Decimal(str(origin.unit_price or 0))
                amount = _line_amount(quantity, unit_price)
                total += amount
                db.add(
                    PurchaseReturnItem(
                        tenant_id=tenant_id, return_id=posted.id,
                        inbound_item_id=line_id, product_id=origin.product_id,
                        batch_no=origin.batch_no, location_id=origin.location_id,
                        quantity=quantity, unit_price=unit_price, amount=amount,
                    )
                )
                db.add(
                    InventoryTransaction(
                        tenant_id=tenant_id, ledger_id=ledger.id,
                        transaction_type="out", document_posting=False,
                        product_id=origin.product_id, warehouse_id=receipt.warehouse_id,
                        location_id=origin.location_id, batch_no=origin.batch_no,
                        quantity=-quantity, before_quantity=before,
                        after_quantity=before - quantity, unit_price=unit_price,
                        total_amount=-amount, reference_type="purchase_return",
                        reference_id=posted.id, transaction_date=now,
                        remark=f"原入库单 {inbound_id} 退货: {return_no}", created_at=now,
                    )
                )
            posted.total_amount = total
            journal_id = None
            if total > 0:
                journal = create_journal_entry(
                    {
                        "entry_no": f"PR-{tenant_id}-{posted.id}",
                        "description": f"采购退货反冲: {return_no}",
                        "reference_type": "purchase_return",
                        "reference_id": posted.id,
                        "lines": [
                            {
                                "account_code": "2201", "debit": total, "credit": 0,
                                "partner_id": posted.supplier_id,
                            },
                            {
                                "account_code": "1401", "debit": 0, "credit": total,
                            },
                        ],
                    },
                    db=db,
                )
                if journal.get("success") is not True:
                    raise PurchaseReturnRefused(
                        journal.get("message") or "退货应付反冲凭证无法持久化"
                    )
                journal_id = journal["data"]["id"]
                posted.journal_entry_id = journal_id
            # The original order's net received quantity is a derived projection
            # of posted inbounds minus posted returns, never a second ledger.
            db.flush()
            if receipt.order_id is not None:
                from app.domain.shared_services.purchase_service import PurchaseService

                PurchaseService()._update_order_received_quantity(db, receipt.order_id)
            db.commit()
            return {
                "success": True,
                "idempotent": False,
                "return_id": posted.id,
                "journal_entry_id": journal_id,
                "amount": str(total),
                "bank_settlement_verified": False,
            }
        except (PurchaseReturnRefused, IntegrityError) as exc:
            db.rollback()
            return {
                "success": False,
                "reason_code": (
                    "return_business_conflict"
                    if isinstance(exc, PurchaseReturnRefused)
                    else "return_db_unique_conflict"
                ),
                "message": str(exc),
            }
