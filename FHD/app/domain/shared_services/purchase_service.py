"""
采购管理服务模块

提供供应商、采购订单、采购入库等业务逻辑。
"""

import hashlib
import json
import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Product,
    PurchaseInbound,
    PurchaseInboundItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReturn,
    PurchaseReturnItem,
    Supplier,
)
from app.db.session import get_db
from app.domain.shared_services.inventory_service import InventoryService
from app.domain.shared_services.purchase_service_supplier_mixin import (
    DATE_FIELDS,
    PurchaseSupplierMixin,
    as_date,
    items_without_product,
    page_result,
)
from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _write_lock(db):
    if db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        db.execute(text("BEGIN IMMEDIATE"))


def _line_values(item):
    try:
        quantity = Decimal(str(item.get("quantity", 0)))
        price = Decimal(str(item.get("unit_price", 0)))
        if (
            not quantity.is_finite()
            or not price.is_finite()
            or quantity <= 0
            or price < 0
            or quantity != quantity.quantize(Decimal("0.0001"))
            or price != price.quantize(Decimal("0.0001"))
        ):
            raise ValueError("采购数量或单价无效")
        return quantity, price
    except InvalidOperation as exc:
        raise ValueError("采购数量或单价无效") from exc


def _line_amount(quantity: Decimal, price: Decimal) -> Decimal:
    """Per-line currency amount matches persisted NUMERIC(18, 2) and journal totals."""
    return (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def purchase_execution_number(action: str, run_id: str, step_id: str, tenant_id: str) -> str:
    """Use original AgentRun identity in the existing unique business document number."""
    if not all((run_id, step_id, tenant_id)):
        raise ValueError("采购执行缺少原任务身份")
    digest = hashlib.sha256(
        json.dumps([action, run_id, step_id, str(tenant_id)], separators=(",", ":")).encode()
    ).hexdigest()[:36]
    return ("AGPI-" if action == "create_inbound" else "AGPO-") + digest


class PurchaseService(PurchaseSupplierMixin, NeuroEventPublisherMixin):
    """采购管理服务类"""

    def get_purchase_orders(
        self,
        supplier_id: int | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(PurchaseOrder).join(Supplier)

            if supplier_id:
                query = query.filter(PurchaseOrder.supplier_id == supplier_id)
            if status:
                query = query.filter(PurchaseOrder.status == status)
            if start_date:
                query = query.filter(PurchaseOrder.order_date >= start_date)
            if end_date:
                query = query.filter(PurchaseOrder.order_date <= end_date)

            total = query.count()
            orders = (
                query.order_by(PurchaseOrder.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

            result = []
            for order in orders:
                order_dict = self._model_to_dict(order)
                order_dict["supplier_name"] = order.supplier.name if order.supplier else None
                order_dict["items"] = (
                    [self._model_to_dict(item) for item in order.items] if order.items else []
                )
                result.append(order_dict)

            return page_result(result, total, page, per_page)

    def get_purchase_order(self, order_id: int) -> dict[str, Any]:
        with get_db() as db:
            order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
            if not order:
                return {"success": False, "message": "采购订单不存在"}

            order_dict = self._model_to_dict(order)
            order_dict["supplier_name"] = order.supplier.name if order.supplier else None
            order_dict["warehouse_name"] = order.warehouse.name if order.warehouse else None
            order_dict["items"] = []
            for item in order.items:
                item_dict = self._model_to_dict(item)
                item_dict["product_name"] = item.product.name if item.product else None
                order_dict["items"].append(item_dict)

            return {"success": True, "data": order_dict}

    def create_purchase_order(self, data: dict[str, Any]) -> dict[str, Any]:
        if invalid := items_without_product(data.get("items") or []):
            return invalid
        with get_db() as db:
            try:
                order_no = data.get("order_no") or self._generate_order_no()
                total_amount = Decimal(0)

                order = PurchaseOrder(
                    order_no=order_no,
                    supplier_id=data.get("supplier_id"),
                    warehouse_id=data.get("warehouse_id"),
                    order_date=as_date(data.get("order_date"), datetime.now().date()),
                    delivery_date=as_date(data.get("delivery_date")),
                    total_amount=0,
                    status="draft",
                    remark=data.get("remark"),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(order)
                db.flush()

                items_data = data.get("items", [])
                for item_data in items_data:
                    product = (
                        db.query(Product).filter(Product.id == item_data.get("product_id")).first()
                    )
                    quantity, unit_price = _line_values(item_data)
                    amount = _line_amount(quantity, unit_price)
                    total_amount += amount

                    item = PurchaseOrderItem(
                        order_id=order.id,
                        product_id=item_data.get("product_id"),
                        product_name=(product.name if product else item_data.get("product_name")),
                        specification=item_data.get("specification"),
                        quantity=quantity,
                        unit=item_data.get("unit", "个"),
                        unit_price=unit_price,
                        amount=amount,
                        received_quantity=0,
                        invoiced_quantity=0,
                        status="pending",
                        remark=item_data.get("remark"),
                        created_at=datetime.now(),
                    )
                    db.add(item)

                order.total_amount = Decimal(str(total_amount))
                db.commit()
                db.refresh(order)

                # Sample Neuro-DDD closed loop: emit order.created after durable commit.
                try:
                    from app.neuro_bus.domains.order_domain import get_order_domain

                    get_order_domain().emit_order_created(
                        order_id=str(order.id),
                        customer_id=str(order.supplier_id or ""),
                        items=list(items_data or []),
                        total_amount=Decimal(str(total_amount or 0)),
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("emit_order_created skipped", exc_info=True)

                return {
                    "success": True,
                    "data": self._model_to_dict(order),
                    "message": "采购订单创建成功",
                }
            except IntegrityError:
                db.rollback()
                return {"success": False, "message": "采购订单身份冲突，未重复创建"}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("创建采购订单失败: %s", e)
                return {"success": False, "message": str(e)}

    def update_purchase_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if set(data) - {
            "supplier_id",
            "warehouse_id",
            "order_date",
            "delivery_date",
            "remark",
            "items",
        }:
            return {"success": False, "message": "订单身份、审批状态及金额只能由原业务动作变更"}
        if invalid := items_without_product(data.get("items") or []):
            return invalid
        with get_db() as db:
            try:
                _write_lock(db)
                order = (
                    db.query(PurchaseOrder)
                    .filter(PurchaseOrder.id == order_id)
                    .with_for_update()
                    .first()
                )
                if not order:
                    return {"success": False, "message": "采购订单不存在"}

                if order.status not in ("draft", "rejected"):
                    return {"success": False, "message": "只有草稿状态的订单可以修改"}

                for key, value in data.items():
                    if key == "items":
                        continue
                    if key in DATE_FIELDS:
                        value = as_date(value)
                    if hasattr(order, key):
                        setattr(order, key, value)
                order.updated_at = datetime.now()

                if "items" in data:
                    db.query(PurchaseOrderItem).filter(
                        PurchaseOrderItem.order_id == order_id
                    ).delete()
                    total_amount = Decimal(0)

                    for item_data in data["items"]:
                        product = (
                            db.query(Product)
                            .filter(Product.id == item_data.get("product_id"))
                            .first()
                        )
                        quantity, unit_price = _line_values(item_data)
                        amount = _line_amount(quantity, unit_price)
                        total_amount += amount

                        item = PurchaseOrderItem(
                            order_id=order.id,
                            product_id=item_data.get("product_id"),
                            product_name=(
                                product.name if product else item_data.get("product_name")
                            ),
                            specification=item_data.get("specification"),
                            quantity=quantity,
                            unit=item_data.get("unit", "个"),
                            unit_price=unit_price,
                            amount=amount,
                            received_quantity=0,
                            invoiced_quantity=0,
                            status="pending",
                            remark=item_data.get("remark"),
                            created_at=datetime.now(),
                        )
                        db.add(item)

                    order.total_amount = Decimal(str(total_amount))

                db.commit()
                db.refresh(order)
                return {"success": True, "data": self._model_to_dict(order)}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("更新采购订单失败: %s", e)
                return {"success": False, "message": str(e)}

    def approve_purchase_order(self, order_id: int, approver: str) -> dict[str, Any]:
        with get_db() as db:
            try:
                _write_lock(db)
                order = (
                    db.query(PurchaseOrder)
                    .filter(PurchaseOrder.id == order_id)
                    .with_for_update()
                    .first()
                )
                if not order:
                    return {"success": False, "message": "采购订单不存在"}

                if order.status != "draft":
                    return {"success": False, "message": "只有草稿状态的订单可以审核"}
                lines = [
                    _line_amount(
                        *_line_values({"quantity": item.quantity, "unit_price": item.unit_price})
                    )
                    for item in order.items
                ]
                expected = sum(lines, Decimal("0"))
                if (
                    not lines
                    or expected != Decimal(str(order.total_amount))
                    or any(
                        amount != Decimal(str(item.amount or 0))
                        for amount, item in zip(lines, order.items)
                    )
                ):
                    raise ValueError("采购审批需要金额与数量一致的原订单明细")
                supplier = (
                    db.query(Supplier)
                    .filter(
                        Supplier.id == order.supplier_id,
                        Supplier.tenant_id == order.tenant_id,
                    )
                    .with_for_update()
                    .first()
                )
                if supplier is None or supplier.status != "active":
                    raise ValueError("采购供应商不存在或未启用")
                credit = Decimal(str(supplier.credit_limit or 0))
                if credit > 0:
                    outstanding = sum(
                        (
                            Decimal(str(row.total_amount or 0)) - Decimal(str(row.paid_amount or 0))
                            for row in db.query(PurchaseOrder)
                            .filter(
                                PurchaseOrder.supplier_id == supplier.id,
                                PurchaseOrder.tenant_id == order.tenant_id,
                                PurchaseOrder.status.in_(("approved", "partial", "completed")),
                            )
                            .all()
                        ),
                        Decimal(0),
                    )
                    if outstanding + Decimal(str(order.total_amount or 0)) > credit:
                        raise ValueError("采购订单超出原供应商已配置的信用额度")

                order.status = "approved"
                order.approver = approver
                order.approve_date = datetime.now()
                order.updated_at = datetime.now()

                for item in order.items:
                    item.status = "approved"

                db.commit()
                return {"success": True, "message": "审核成功", "data": self._model_to_dict(order)}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("审核采购订单失败: %s", e)
                return {"success": False, "message": str(e)}

    def cancel_purchase_order(self, order_id: int) -> dict[str, Any]:
        with get_db() as db:
            try:
                _write_lock(db)
                order = (
                    db.query(PurchaseOrder)
                    .filter(PurchaseOrder.id == order_id)
                    .with_for_update()
                    .first()
                )
                if not order:
                    return {"success": False, "message": "采购订单不存在"}

                if order.status not in {"draft", "rejected", "approved"}:
                    return {"success": False, "message": "已履约或终态的采购订单不可取消"}
                if (
                    Decimal(str(order.paid_amount or 0)) != 0
                    or any(
                        Decimal(str(item.received_quantity or 0)) > 0
                        or Decimal(str(item.invoiced_quantity or 0)) > 0
                        for item in order.items
                    )
                    or db.query(PurchaseInbound.id)
                    .filter(
                        PurchaseInbound.order_id == order.id,
                        PurchaseInbound.tenant_id == order.tenant_id,
                        PurchaseInbound.status == "completed",
                    )
                    .first()
                    is not None
                ):
                    return {
                        "success": False,
                        "message": "采购订单已有入库、开票或付款，须通过原业务冲销，不得直接取消",
                    }

                order.status = "cancelled"
                order.updated_at = datetime.now()

                for item in order.items:
                    item.status = "cancelled"

                db.commit()
                return {
                    "success": True,
                    "message": "订单已取消",
                    "data": self._model_to_dict(order),
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("取消采购订单失败: %s", e)
                return {"success": False, "message": str(e)}

    def create_purchase_inbound(self, data: dict[str, Any]) -> dict[str, Any]:
        if invalid := items_without_product(data.get("items") or []):
            return invalid
        with get_db() as db:
            try:
                _write_lock(db)
                self._validate_receiving_order(db, data)
                inbound_no = data.get("inbound_no") or self._generate_inbound_no()
                total_amount = Decimal(0)
                inventory_service = InventoryService()

                inbound = PurchaseInbound(
                    inbound_no=inbound_no,
                    order_id=data.get("order_id"),
                    supplier_id=data.get("supplier_id"),
                    warehouse_id=data.get("warehouse_id"),
                    inbound_date=as_date(data.get("inbound_date"), datetime.now().date()),
                    total_amount=0,
                    status="draft",
                    handler=data.get("handler"),
                    remark=data.get("remark"),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(inbound)
                db.flush()

                items_data = data.get("items", [])
                for item_data in items_data:
                    product = (
                        db.query(Product).filter(Product.id == item_data.get("product_id")).first()
                    )
                    quantity, unit_price = _line_values(item_data)
                    amount = _line_amount(quantity, unit_price)
                    total_amount += amount

                    item = PurchaseInboundItem(
                        inbound_id=inbound.id,
                        product_id=item_data.get("product_id"),
                        order_item_id=item_data.get("order_item_id"),
                        product_name=(product.name if product else item_data.get("product_name")),
                        batch_no=item_data.get("batch_no"),
                        quantity=quantity,
                        unit=item_data.get("unit", "个"),
                        unit_price=unit_price,
                        amount=amount,
                        location_id=item_data.get("location_id"),
                        remark=item_data.get("remark"),
                        created_at=datetime.now(),
                    )
                    db.add(item)

                    warehouse_id = data.get("warehouse_id")
                    if warehouse_id is None:
                        raise ValueError("采购入库缺少 warehouse_id")
                    result = inventory_service.inventory_in(
                        product_id=item_data.get("product_id"),
                        warehouse_id=int(warehouse_id),
                        quantity=float(quantity),
                        batch_no=item_data.get("batch_no"),
                        location_id=item_data.get("location_id"),
                        unit_price=float(unit_price),
                        reference_type="purchase_inbound",
                        reference_id=inbound.id,
                        operator=data.get("handler"),
                        remark=f"采购入库单: {inbound_no}",
                        session=db,
                    )
                    if not result.get("success"):
                        raise ValueError(result.get("message") or "库存入库失败")

                inbound.total_amount = Decimal(str(total_amount))
                inbound.status = "completed"
                order_id = data.get("order_id")
                if order_id is not None:
                    # SessionLocal has autoflush=False: make new inbound items visible
                    # to the exact-source progress query before posting a payable.
                    db.flush()
                    self._update_order_received_quantity(db, int(order_id))

                # Inventory, receipt, order progress and payable share one transaction.
                journal_id = None
                if total_amount > 0:
                    from app.domain.shared_services.accounting_services import create_journal_entry

                    journal = create_journal_entry(
                        {
                            "description": f"采购入库: {inbound_no}",
                            "reference_type": "purchase_inbound",
                            "reference_id": inbound.id,
                            "lines": [
                                {"account_code": "1401", "debit": total_amount, "credit": 0},
                                {
                                    "account_code": "2201",
                                    "debit": 0,
                                    "credit": total_amount,
                                    "partner_id": inbound.supplier_id,
                                    "partner_name": inbound.supplier.name
                                    if inbound.supplier
                                    else None,
                                },
                            ],
                        },
                        db=db,
                    )
                    if journal.get("success") is not True:
                        raise ValueError(journal.get("message") or "采购应付记账失败")
                    journal_id = journal["data"]["id"]
                db.commit()
                db.refresh(inbound)

                self._publish_event(
                    "inventory.inbound_created",
                    {
                        "inbound_id": inbound.id,
                        "inbound_no": inbound.inbound_no,
                        "supplier_id": inbound.supplier_id,
                        "warehouse_id": inbound.warehouse_id,
                        "total_amount": float(inbound.total_amount or 0),
                        "items": data.get("items", []),
                    },
                )
                return {
                    "success": True,
                    "data": {**self._model_to_dict(inbound), "journal_entry_id": journal_id},
                    "message": "入库成功",
                }
            except IntegrityError:
                db.rollback()
                return {"success": False, "message": "采购入库身份冲突，未重复入库"}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("创建采购入库单失败: %s", e)
                return {"success": False, "message": str(e)}

    def _validate_receiving_order(self, db, data):
        if data.get("order_id") is None:
            return  # Standalone manual receipts keep their existing separate authority.
        order = (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.id == int(data["order_id"]))
            .with_for_update()
            .first()
        )
        if order is None or order.status not in {"approved", "partial"}:
            raise ValueError("采购入库需要原已审批且未完成的采购订单")
        if (
            data.get("supplier_id") != order.supplier_id
            or data.get("warehouse_id") != order.warehouse_id
        ):
            raise ValueError("采购入库供应商或仓库与原订单不一致")
        original = {row.id: row for row in order.items}
        received = {}
        if not data.get("items"):
            raise ValueError("采购入库缺少订单明细")
        for item in data["items"]:
            row = original.get(item.get("order_item_id"))
            quantity, price = _line_values(item)
            if (
                row is None
                or row.product_id != item.get("product_id")
                or not quantity.is_finite()
                or quantity <= 0
                or not price.is_finite()
                or price != Decimal(str(row.unit_price or 0))
            ):
                raise ValueError("采购入库明细或单价不符合原审批订单")
            received[row.id] = received.get(row.id, Decimal(0)) + quantity
            if Decimal(str(row.received_quantity or 0)) + received[row.id] > Decimal(
                str(row.quantity)
            ):
                raise ValueError("采购入库数量超出原审批订单剩余额度")

    def _update_order_received_quantity(self, db, order_id: int):
        order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
        if not order:
            return

        for item in order.items:
            inbound_items = (
                db.query(PurchaseInboundItem)
                .join(PurchaseInbound, PurchaseInbound.id == PurchaseInboundItem.inbound_id)
                .filter(
                    PurchaseInboundItem.order_item_id == item.id,
                    PurchaseInboundItem.tenant_id == order.tenant_id,
                    PurchaseInbound.order_id == order.id,
                    PurchaseInbound.tenant_id == order.tenant_id,
                    PurchaseInbound.status == "completed",
                )
                .all()
            )
            gross_received = sum((Decimal(str(i.quantity)) for i in inbound_items), Decimal("0"))
            # Posted returns are subtracted by the original receipt-line ID.
            return_items = (
                db.query(PurchaseReturnItem)
                .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.return_id)
                .join(
                    PurchaseInboundItem,
                    PurchaseInboundItem.id == PurchaseReturnItem.inbound_item_id,
                )
                .filter(
                    PurchaseReturn.tenant_id == order.tenant_id,
                    PurchaseReturnItem.tenant_id == order.tenant_id,
                    PurchaseInboundItem.tenant_id == order.tenant_id,
                    PurchaseReturn.status == "posted",
                    PurchaseInboundItem.order_item_id == item.id,
                )
                .all()
            )
            returned = sum((Decimal(str(i.quantity)) for i in return_items), Decimal("0"))
            received = gross_received - returned
            if received < 0:
                raise ValueError("采购退货超过原入库数量，原账本需先独立核对")
            item.received_quantity = received

            if Decimal(str(item.quantity)) <= received:
                item.status = "completed"
            elif received > 0:
                item.status = "partial"
            else:
                item.status = "approved"

        all_completed = all(
            Decimal(str(item.quantity)) <= Decimal(str(item.received_quantity or 0))
            for item in order.items
        )
        any_received = any(Decimal(str(item.received_quantity or 0)) > 0 for item in order.items)

        if all_completed:
            order.status = "completed"
        elif any_received:
            order.status = "partial"
        elif order.status in {"partial", "completed"}:
            order.status = "approved"

    def post_purchase_return(self, data: dict[str, Any]) -> dict[str, Any]:
        """Post only source receipt quantities frozen by an approved request."""
        from app.domain.shared_services.purchase_return_posting import post_purchase_return

        return post_purchase_return(data)

    def reconcile_purchase_inbound(self, inbound_id: int) -> dict[str, Any]:
        """Read-only cross-check: source receipt ↔ batch movements ↔ AP journal.

        This is an independent query of the original rows in the same database,
        NOT independent banking, customer sign-off or supplier settlement.
        """
        from collections import defaultdict

        from app.db.models.accounting import JournalEntry
        from app.db.models.inventory import InventoryTransaction
        from app.domain.context.current_request import current_tenant_id

        tenant_id = current_tenant_id()
        if tenant_id is None:
            return {"success": False, "reason_code": "tenant_context_required"}
        with get_db() as db:
            receipt = (
                db.query(PurchaseInbound)
                .filter(
                    PurchaseInbound.id == inbound_id,
                    PurchaseInbound.tenant_id == tenant_id,
                )
                .one_or_none()
            )
            if receipt is None or receipt.status != "completed":
                return {
                    "success": False,
                    "reason_code": "completed_purchase_receipt_required",
                }

            issues: list[str] = []
            expected: dict[tuple[int, int, str | None, int | None], Decimal] = defaultdict(
                lambda: Decimal("0")
            )
            source_total = Decimal("0")
            if not receipt.items:
                issues.append("receipt_items_missing")
            for item in receipt.items:
                if item.tenant_id != tenant_id or item.product_id is None:
                    issues.append("receipt_item_tenant_or_identity_conflict")
                    continue
                quantity = Decimal(str(item.quantity))
                if not quantity.is_finite() or quantity <= 0:
                    issues.append("receipt_item_quantity_invalid")
                    continue
                key = (
                    item.product_id,
                    receipt.warehouse_id,
                    item.batch_no,
                    item.location_id,
                )
                expected[key] += quantity
                source_total += _line_amount(quantity, Decimal(str(item.unit_price or 0)))
                if Decimal(str(item.amount or 0)) != _line_amount(
                    quantity, Decimal(str(item.unit_price or 0))
                ):
                    issues.append("receipt_item_amount_mismatch")

            postings = (
                db.query(InventoryTransaction)
                .filter(
                    InventoryTransaction.tenant_id == tenant_id,
                    InventoryTransaction.reference_type == "purchase_inbound",
                    InventoryTransaction.reference_id == receipt.id,
                )
                .all()
            )
            actual: dict[tuple[int, int, str | None, int | None], Decimal] = defaultdict(
                lambda: Decimal("0")
            )
            for txn in postings:
                if txn.transaction_type != "in":
                    issues.append("unexpected_purchase_stock_movement")
                    continue
                actual[(txn.product_id, txn.warehouse_id, txn.batch_no, txn.location_id)] += (
                    Decimal(str(txn.quantity))
                )
            if dict(actual) != dict(expected):
                issues.append("purchase_batch_stock_mismatch")

            total = Decimal(str(receipt.total_amount or 0))
            if total != source_total:
                issues.append("purchase_receipt_total_mismatch")
            entries = (
                db.query(JournalEntry)
                .filter(
                    JournalEntry.tenant_id == tenant_id,
                    JournalEntry.reference_type == "purchase_inbound",
                    JournalEntry.reference_id == receipt.id,
                )
                .all()
            )
            journal_id = entries[0].id if len(entries) == 1 else None
            if total > 0:
                if len(entries) != 1:
                    issues.append("purchase_payable_journal_missing_or_duplicate")
                else:
                    entry = entries[0]
                    debit = sum(
                        (Decimal(str(line.debit or 0)) for line in entry.lines),
                        Decimal("0"),
                    )
                    credit = sum(
                        (Decimal(str(line.credit or 0)) for line in entry.lines),
                        Decimal("0"),
                    )
                    asset = sum(
                        (
                            Decimal(str(line.debit or 0))
                            for line in entry.lines
                            if line.account_code == "1401"
                        ),
                        Decimal("0"),
                    )
                    payable = sum(
                        (
                            Decimal(str(line.credit or 0))
                            for line in entry.lines
                            if line.account_code == "2201"
                        ),
                        Decimal("0"),
                    )
                    if (
                        entry.status != "posted"
                        or entry.reversed_at is not None
                        or debit != total
                        or credit != total
                        or asset != total
                        or payable != total
                    ):
                        issues.append("purchase_payable_journal_amount_or_status_mismatch")
            elif entries:
                issues.append("unexpected_zero_amount_purchase_journal")

            issues = sorted(set(issues))
            return {
                "success": not issues,
                "posting_consistent": not issues,
                "issues": issues,
                "receipt_id": receipt.id,
                "receipt_no": receipt.inbound_no,
                "source_amount": str(total),
                "source_line_count": len(receipt.items),
                "inventory_posting_count": len(postings),
                "journal_id": journal_id,
                "scope": "same_database_cross_table_only",
                "bank_settlement_verified": False,
                "customer_signoff_verified": False,
            }

    def get_purchase_inbounds(
        self,
        supplier_id: int | None = None,
        order_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(PurchaseInbound)

            if supplier_id:
                query = query.filter(PurchaseInbound.supplier_id == supplier_id)
            if order_id:
                query = query.filter(PurchaseInbound.order_id == order_id)
            if start_date:
                query = query.filter(PurchaseInbound.inbound_date >= start_date)
            if end_date:
                query = query.filter(PurchaseInbound.inbound_date <= end_date)

            total = query.count()
            inbounds = (
                query.order_by(PurchaseInbound.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

            result = []
            for inbound in inbounds:
                inbound_dict = self._model_to_dict(inbound)
                inbound_dict["supplier_name"] = inbound.supplier.name if inbound.supplier else None
                inbound_dict["warehouse_name"] = (
                    inbound.warehouse.name if inbound.warehouse else None
                )
                inbound_dict["items"] = (
                    [self._model_to_dict(item) for item in inbound.items] if inbound.items else []
                )
                result.append(inbound_dict)

            return page_result(result, total, page, per_page)


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(PurchaseService, "app.domain.shared_services.purchase_service")
