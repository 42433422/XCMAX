"""Sales application API composed from queries, domain owners and an atomic workflow.

The public methods retain caller-owned transaction forwarding. Validation,
current-tenant references and replay identity are independent policies; the
workflow receives only the callbacks it invokes, never a facade/global namespace.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from decimal import Decimal
from typing import Any

from app.application.invoicing_service import credit_note, invoice
from app.application.payment_service import payment, refund
from app.application.sales import idempotency, references, validation
from app.application.sales.closed_loop import ClosedLoopRunner
from app.application.sales.contracts import ClosedLoopExecutionError as ClosedLoopExecutionError
from app.application.sales.contracts import FingerprintPorts, ReferencePorts, SalesOperations
from app.application.sales.quotes import SalesQuotes, generate_order_no
from app.application.sales.validation import to_decimal as _to_decimal
from app.application.sales_lifecycle_service import SalesLifecycleError, SalesLifecycleService
from app.db.models import SalesOrder
from app.db.models.sales import SALES_ORDER_STATUS_FLOW
from app.db.session import get_db
from app.domain.shared_services.fulfillment_service import FulfillmentService
from app.infrastructure.tenant_scope import TenantScopeError, current_tenant_id, tenant_id_for_write

logger = logging.getLogger(__name__)
_CLOSED_LOOP_FP_PREFIX = idempotency.CLOSED_LOOP_FP_PREFIX


class SalesAppService:
    """Explicit composition over sales domain owners and caller-owned sessions."""

    def _quotes(self) -> SalesQuotes:
        return SalesQuotes(get_db, self._generate_order_no, _to_decimal)

    def _closed_loop_runner(self) -> ClosedLoopRunner:
        return ClosedLoopRunner(
            SalesOperations(self.quote, self.confirm, self.deliver, self.invoice, self.payment),
            ReferencePorts(
                self._closed_loop_resolve_customer,
                self._closed_loop_resolve_products,
                self._closed_loop_resolve_warehouse,
                self._closed_loop_resolve_inventory_source,
            ),
            FingerprintPorts(
                self._closed_loop_composite_fingerprint,
                self._closed_loop_persist_fingerprint,
                self._closed_loop_verify_idempotent_fingerprint,
            ),
        )

    def query(
        self,
        status: str | None = None,
        customer_id: int | None = None,
        customer_name: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        return self._quotes().query(status, customer_id, customer_name, keyword, page, per_page)

    def quote(self, data: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
        return self._quotes().quote(data, db=db)

    @staticmethod
    def _lifecycle_service(db: Any) -> SalesLifecycleService:
        """构造生命周期服务：绑定当前会话与租户作用域。"""
        return SalesLifecycleService(db, tenant_id=current_tenant_id())

    @staticmethod
    def _order_result(order: SalesOrder) -> dict[str, Any]:
        return {
            "success": True,
            "message": f"销售订单 {order.order_no} 已推进至 {order.state}",
            "data": order.to_dict(),
        }

    def confirm(self, order_id: int, *, db: Any = None) -> dict[str, Any]:
        """委托生命周期确认；传入 db 时使用该会话且交由调用方管理事务。"""
        owned = db is None
        cm = nullcontext(db) if not owned else get_db()
        with cm as ctx:
            try:
                order = self._lifecycle_service(ctx).confirm(int(order_id))
            except SalesLifecycleError as exc:
                return {"success": False, "message": str(exc)}
            ctx.refresh(order)
            return self._order_result(order)

    def cancel(self, order_id: int) -> dict[str, Any]:
        """取消订单 → 委托 SalesLifecycleService.cancel。"""
        with get_db() as db:
            try:
                order = self._lifecycle_service(db).cancel(int(order_id))
            except SalesLifecycleError as exc:
                return {"success": False, "message": str(exc)}
            db.refresh(order)
            return self._order_result(order)

    def deliver(
        self,
        order_id: int,
        item_id: int,
        quantity: Decimal | float,
        *,
        warehouse_id: int,
        product_id: int | None = None,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        idempotency_key: str | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """交付（partial/backorder）→ 委托 FulfillmentService.deliver。

        可选 ``db``：调用方持有的会话，提供时作为 ``db=db`` 恰好透传一次给
        ``FulfillmentService.deliver``；缺省时由履行服务自开会话。
        """
        return FulfillmentService().deliver(
            order_id,
            item_id,
            float(quantity),
            warehouse_id=warehouse_id,
            product_id=product_id,
            batch_no=batch_no,
            location_id=location_id,
            operator=operator,
            remark=remark,
            idempotency_key=idempotency_key,
            db=db,
        )

    def invoice(
        self,
        order_id: int,
        *,
        partner_id: int | None = None,
        partner_name: str | None = None,
        amount: float | Decimal | None = None,
        journal_date: Any = None,
        description: str | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """开票 → 委托 invoicing_service.invoice。

        可选 ``db``：调用方持有的会话，提供时作为 ``db=db`` 恰好透传一次。
        """
        return invoice(
            order_id,
            partner_id=partner_id,
            partner_name=partner_name,
            amount=amount,
            journal_date=journal_date,
            description=description,
            db=db,
        )

    def credit_note(
        self, order_id: int, *, journal_date: Any = None, description: str | None = None
    ) -> dict[str, Any]:
        """贷项通知单 → 委托 invoicing_service.credit_note。"""
        return credit_note(order_id, journal_date=journal_date, description=description)

    def payment(
        self,
        order_id: int,
        amount: Any = None,
        *,
        partner_id: int | None = None,
        partner_name: str | None = None,
        reference: str | None = None,
        idempotency_key: str | None = None,
        journal_date: Any = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """登记收款 → 委托 payment_service.payment。

        可选 ``db``：调用方持有的会话，提供时作为 ``db=db`` 恰好透传一次。
        """
        return payment(
            sales_order_id=order_id,
            amount=amount,
            partner_id=partner_id,
            partner_name=partner_name,
            reference=reference,
            idempotency_key=idempotency_key,
            journal_date=journal_date,
            db=db,
        )

    def refund(
        self, allocation_id: int, *, reference: str | None = None, journal_date: Any = None
    ) -> dict[str, Any]:
        """收款退款/冲销 → 委托 payment_service.refund。"""
        return refund(allocation_id=allocation_id, reference=reference, journal_date=journal_date)

    def execute_closed_loop(self, payload: dict[str, Any]) -> dict[str, Any]:
        """销售到收款闭环的真实原子执行器（fail-closed）。

        只在一个外层 ``with get_db()`` 事务内调用 quote/confirm/deliver/invoice/
        payment 等专属拥有方服务，任一失败即整体回滚。任何校验失败或缺少租户
        上下文都返回结构化失败并写入零行，绝不返回被弃用的 NOT_READY 哨兵。
        """
        struct_err = self._closed_loop_validate_structure(payload)
        if struct_err:
            return struct_err
        idempotency_key = payload["idempotency_key"].strip()
        try:
            tenant_id = tenant_id_for_write()
        except TenantScopeError:
            return {
                "success": False,
                "error_code": "NO_TENANT_CONTEXT",
                "message": "缺少当前租户上下文，拒绝执行（零持久化）",
                "failed_step": "tenant",
            }
        reject_err = self._closed_loop_reject_tenant_id(payload)
        if reject_err:
            return reject_err
        arith_err = self._closed_loop_validate_arithmetic(payload)
        if arith_err:
            return arith_err
        try:
            with get_db() as db:
                result = self._closed_loop_run(db, payload, tenant_id, idempotency_key)
            return result
        except ClosedLoopExecutionError as exc:
            return {
                "success": False,
                "error_code": "CLOSED_LOOP_EXECUTION_FAILED",
                "failed_step": exc.step,
                "message": exc.message,
            }

    def _closed_loop_run(
        self, db, payload: dict[str, Any], tenant_id: int, idempotency_key: str
    ) -> dict[str, Any]:
        return self._closed_loop_runner().run(db, payload, tenant_id, idempotency_key)

    @staticmethod
    def _closed_loop_validate_structure(payload: Any) -> dict[str, Any] | None:
        return validation.validate_structure(payload)

    @staticmethod
    def _closed_loop_contains_tenant_id(value: Any) -> bool:
        return validation.contains_tenant_id(value)

    def _closed_loop_reject_tenant_id(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return validation.reject_tenant_id(payload)

    def _closed_loop_validate_arithmetic(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return validation.validate_arithmetic(payload)

    @staticmethod
    def _closed_loop_err(message: str) -> dict[str, Any]:
        return validation.invalid_payload(message)

    @staticmethod
    def _closed_loop_dec(value: Any) -> Decimal | None:
        return validation.finite_decimal(value)

    @staticmethod
    def _closed_loop_coerce_id(value: Any, step: str, label: str) -> int:
        return validation.coerce_entity_id(value, step, label)

    @staticmethod
    def _closed_loop_canon_dec(value: Any) -> str:
        return validation.canonical_decimal(value)

    @staticmethod
    def _closed_loop_order_no(idempotency_key: str, tenant_id: int) -> str:
        return idempotency.closed_loop_order_no(idempotency_key, tenant_id)

    @staticmethod
    def _closed_loop_composite_fingerprint(
        customer: dict[str, Any],
        products: list[dict[str, Any]],
        warehouse: dict[str, Any],
        order: dict[str, Any],
        fulfillment: dict[str, Any],
        invoice: dict[str, Any],
        pa: dict[str, Any],
    ) -> str:
        return idempotency.composite_fingerprint(
            customer, products, warehouse, order, fulfillment, invoice, pa
        )

    @staticmethod
    def _closed_loop_extract_fingerprint(remark: str | None) -> str | None:
        return idempotency.extract_fingerprint(remark)

    def _closed_loop_verify_idempotent_fingerprint(
        self, db, order_id: int, fingerprint: str
    ) -> None:
        return idempotency.verify_fingerprint(db, order_id, fingerprint)

    def _closed_loop_persist_fingerprint(self, db, order_id: int, fingerprint: str) -> None:
        return idempotency.persist_fingerprint(db, order_id, fingerprint)

    def _closed_loop_resolve_customer(
        self, db, order: dict[str, Any], tenant_id: int
    ) -> dict[str, Any]:
        return references.resolve_customer(db, order, tenant_id)

    def _closed_loop_resolve_products(
        self, db, order: dict[str, Any], tenant_id: int
    ) -> list[dict[str, Any]]:
        return references.resolve_products(db, order, tenant_id)

    def _closed_loop_resolve_warehouse(
        self, db, fulfillment: dict[str, Any], tenant_id: int
    ) -> dict[str, Any]:
        return references.resolve_warehouse(db, fulfillment, tenant_id)

    def _closed_loop_resolve_inventory_source(
        self, db, *, product_id: int, warehouse_id: int, quantity: Decimal, tenant_id: int
    ) -> dict[str, Any]:
        return references.resolve_inventory_source(
            db,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _generate_order_no() -> str:
        return generate_order_no()


__all__ = ["SalesAppService", "SALES_ORDER_STATUS_FLOW"]
