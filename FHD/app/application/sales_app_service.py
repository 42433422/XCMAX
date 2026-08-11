"""
销售应用服务门面（Sales-to-Payment 闭环，W1-09）

本模块是 `sales` 能力工具的只读 / 受控写入**组合门面**（composition only），
本身**不复制**任何状态迁移、履行、库存、分配、退款或贷项通知单领域逻辑：

- 查询 / 报价创建：保留在本门面（只读检索 + 单据创建）。
- 生命周期迁移（confirm / cancel）：委托 ``SalesLifecycleService``。
- 履行动作（deliver）：委托 ``FulfillmentService``。
- 开票 / 贷项通知单（invoice / credit_note）：委托 ``app.application.invoicing_service``。
- 收款 / 退款（payment / refund）：委托 ``app.application.payment_service``（snake_case）。

门面只做参数透传与结果规整，业务副作用统一由各专属模块负责。
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_

from app.application.invoicing_service import credit_note, invoice
from app.application.payment_service import payment, refund
from app.application.sales_lifecycle_service import (
    SalesLifecycleError,
    SalesLifecycleService,
)
from app.db.models import Customer, Product, SalesOrder, SalesOrderItem, Warehouse
from app.db.models.sales import SALES_ORDER_STATUS_FLOW
from app.db.session import get_db
from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    tenant_id_for_write,
)
from app.services.fulfillment_service import FulfillmentService

logger = logging.getLogger(__name__)

# 复合幂等指纹在既有 remark 字段内的命名空间前缀（不影响顶层 idempotency 标记）。
_CLOSED_LOOP_FP_PREFIX = "w1-10-closed-loop-composite"


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


class ClosedLoopExecutionError(RuntimeError):
    """闭环执行失败：携带失败步骤，用于触发外层事务整体回滚。"""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


class SalesAppService:
    """销售应用服务门面：组合委托，不含领域副作用逻辑。"""

    # ── 查询（保留在本门面，只读）──────────────────────────────

    def query(
        self,
        status: str | None = None,
        customer_id: int | None = None,
        customer_name: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """按状态/客户/关键字查询销售订单列表。"""
        with get_db() as db:
            q = db.query(SalesOrder)
            if status:
                q = q.filter(SalesOrder.status == status)
            if customer_id:
                q = q.filter(SalesOrder.customer_id == customer_id)
            if customer_name:
                q = q.filter(SalesOrder.customer_name == customer_name)
            if keyword:
                like = f"%{keyword}%"
                q = q.filter(SalesOrder.order_no.like(like) | SalesOrder.customer_name.like(like))
            total = q.count()
            orders = (
                q.order_by(SalesOrder.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
            )
            return {
                "success": True,
                "data": [o.to_dict() for o in orders],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    # ── 报价创建（保留在本门面，单据创建）───────────────────────

    def quote(self, data: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
        """创建报价单（state=quote），明细项由 items 提供。

        可选 ``idempotency_key``：同 key 重复调用不重复建单（端到端幂等，GAP-3）。
        可选 ``db``：调用方持有的 SQLAlchemy 会话。提供时使用该精确对象并交由调用方
        负责提交/回滚（本方法仅 flush/refresh，不 commit/rollback/close）；缺省时沿用
        本模块 ``get_db()`` 自有会话并自行提交。
        """
        customer_id = data.get("customer_id")
        items_data = data.get("items") or []
        if not customer_id:
            return {"success": False, "message": "缺少 customer_id"}
        if not isinstance(items_data, list) or not items_data:
            return {"success": False, "message": "缺少 items 明细"}

        idempotency_key = str(data.get("idempotency_key") or "").strip() or None
        idem_marker = f"idempotency:sales_quote:{idempotency_key}" if idempotency_key else None

        owned = db is None
        cm = nullcontext(db) if not owned else get_db()
        with cm as ctx:
            # 端到端幂等：同 key 已建单则直接返回既有单，不重复创建。
            # 精确键边界匹配：仅当 remark 恰好等于标记，或标记后紧跟换行且下一行以复合
            # 指纹命名空间开头（复合执行器在下一行写入 ``w1-10-closed-loop-composite:``）
            # 时才视为同一幂等键。绝不使用未转义的裸前缀匹配，否则键 ``abc`` 会误匹配已
            # 持久化的 ``abcd``，且键内 ``%`` / ``_`` 会被当作 SQL LIKE 通配符跨键误匹配。
            # 复合分支只接受 ``marker + "\n" + _CLOSED_LOOP_FP_PREFIX + ":"`` 这一精确的
            # 分隔符-命名空间边界，绝不把标记后紧跟任意第二行（如无关文本）当作幂等重放
            # 候选。``autoescape`` 对 LIKE 元字符（``\\`` ``%`` ``_``）做安全转义，配合
            # ``ESCAPE '\'`` 保证键内元字符按字面匹配。
            if idem_marker:
                existing = (
                    ctx.query(SalesOrder)
                    .filter(
                        or_(
                            SalesOrder.remark == idem_marker,
                            SalesOrder.remark.startswith(
                                idem_marker + "\n" + _CLOSED_LOOP_FP_PREFIX + ":",
                                autoescape=True,
                                escape="\\",
                            ),
                        )
                    )
                    .order_by(SalesOrder.id.desc())
                    .first()
                )
                if existing is not None:
                    return {
                        "success": True,
                        "message": f"报价单已存在（幂等）: {existing.order_no}",
                        "data": existing.to_dict(),
                        "idempotent": True,
                    }

            customer = ctx.query(Customer).filter(Customer.id == int(customer_id)).first()
            if customer is None:
                return {"success": False, "message": f"客户不存在: customer_id={customer_id}"}

            total_amount = 0.0
            order_no = data.get("order_no") or self._generate_order_no()
            order = SalesOrder(
                order_no=order_no,
                customer_id=customer.id,
                customer_name=customer.customer_name,
                state="quote",
                status="quote",
                quote_date=data.get("quote_date", datetime.now().date()),
                total_amount=Decimal("0"),
                paid_amount=Decimal("0"),
                currency=data.get("currency", "CNY"),
                remark=idem_marker or data.get("remark"),
                created_at=datetime.now(),
            )
            ctx.add(order)
            ctx.flush()

            for item_data in items_data:
                product_id = item_data.get("product_id")
                product = (
                    ctx.query(Product).filter(Product.id == product_id).first()
                    if product_id
                    else None
                )
                quantity = _to_float(item_data.get("quantity", 0))
                unit_price = _to_float(item_data.get("unit_price", 0))
                amount = quantity * unit_price
                total_amount += amount
                ctx.add(
                    SalesOrderItem(
                        order_id=order.id,
                        product_id=product_id,
                        product_name=(product.name if product else item_data.get("product_name")),
                        specification=item_data.get("specification"),
                        quantity=Decimal(str(quantity)),
                        unit=item_data.get("unit", "个"),
                        unit_price=Decimal(str(unit_price)),
                        amount=Decimal(str(amount)),
                        ordered_quantity=Decimal(str(quantity)),
                        delivered_quantity=Decimal("0"),
                        returned_quantity=Decimal("0"),
                        invoiced_quantity=Decimal("0"),
                        status="pending",
                        remark=item_data.get("remark"),
                        created_at=datetime.now(),
                    )
                )

            order.total_amount = Decimal(str(total_amount))
            # 调用方会话 autoflush=False：必须先 flush 全部明细与合计，refresh 才不回读为 0
            ctx.flush()
            if owned:
                ctx.commit()
            ctx.refresh(order)
            return {
                "success": True,
                "message": f"报价单已创建: {order.order_no}",
                "data": order.to_dict(),
            }

    # ── 生命周期迁移（委托 SalesLifecycleService）──────────────

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
        """确认销售订单 → 委托 SalesLifecycleService.confirm。

        可选 ``db``：调用方持有的会话，提供时构造 ``SalesLifecycleService`` 绑定该
        精确对象且不打开 ``get_db()``，也绝不 commit/rollback/close；缺省时自开会话。
        """
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

    # ── 履行（委托 FulfillmentService）──────────────────────────

    def deliver(
        self,
        order_id: int,
        item_id: int,
        quantity: float,
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
            quantity,
            warehouse_id=warehouse_id,
            product_id=product_id,
            batch_no=batch_no,
            location_id=location_id,
            operator=operator,
            remark=remark,
            idempotency_key=idempotency_key,
            db=db,
        )

    # ── 开票 / 贷项通知单（委托 invoicing_service）─────────────

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
        self,
        order_id: int,
        *,
        journal_date: Any = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """贷项通知单 → 委托 invoicing_service.credit_note。"""
        return credit_note(
            order_id,
            journal_date=journal_date,
            description=description,
        )

    # ── 收款 / 退款（委托 snake_case payment_service）──────────

    def payment(
        self,
        order_id: int,
        amount: Any = None,
        *,
        partner_id: int | None = None,
        partner_name: str | None = None,
        reference: str | None = None,
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
            journal_date=journal_date,
            db=db,
        )

    def refund(
        self,
        allocation_id: int,
        *,
        reference: str | None = None,
        journal_date: Any = None,
    ) -> dict[str, Any]:
        """收款退款/冲销 → 委托 payment_service.refund。"""
        return refund(
            allocation_id=allocation_id,
            reference=reference,
            journal_date=journal_date,
        )

    # ── 组合闭环：销售→履行→开票→收款（W1-10，真实原子执行器）────

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

    # ── 闭环内部：结构/算数校验、实体解析、单事务编排 ──────────────

    @staticmethod
    def _closed_loop_validate_structure(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict) or not payload:
            return {
                "success": False,
                "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                "message": "缺少闭合载荷 payload",
            }
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return {
                "success": False,
                "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                "message": "闭合载荷缺少非空 idempotency_key",
            }
        for section in ("order", "fulfillment", "invoice", "payment_allocation"):
            sec = payload.get(section)
            if not isinstance(sec, dict) or not sec:
                return {
                    "success": False,
                    "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                    "message": f"闭合载荷缺少 dict 区块: {section}",
                }
        return None

    @staticmethod
    def _closed_loop_contains_tenant_id(value: Any) -> bool:
        if isinstance(value, dict):
            if "tenant_id" in value:
                return True
            return any(SalesAppService._closed_loop_contains_tenant_id(v) for v in value.values())
        if isinstance(value, list):
            return any(SalesAppService._closed_loop_contains_tenant_id(v) for v in value)
        return False

    def _closed_loop_reject_tenant_id(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self._closed_loop_contains_tenant_id(payload):
            return {
                "success": False,
                "error_code": "TENANT_ID_REJECTED",
                "message": "闭合载荷不允许调用方指定 tenant_id（零持久化）",
                "failed_step": "validation",
            }
        return None

    def _closed_loop_validate_arithmetic(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        order = payload["order"]
        items = order.get("items")
        if not isinstance(items, list) or not items:
            return self._closed_loop_err("order.items 缺失或为空")
        eps = Decimal("0.01")
        total = Decimal("0")
        total_qty = Decimal("0")
        units = set()
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                return self._closed_loop_err(f"order.items[{idx}] 非 dict")
            qty = self._closed_loop_dec(item.get("quantity"))
            price = self._closed_loop_dec(item.get("unit_price"))
            line_total = self._closed_loop_dec(item.get("line_total"))
            if qty is None or price is None or line_total is None:
                return self._closed_loop_err(f"order.items[{idx}] 数量/单价/合计非法")
            if qty <= 0 or price <= 0:
                return self._closed_loop_err(f"order.items[{idx}] 数量或单价必须为正")
            unit = item.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                return self._closed_loop_err(f"order.items[{idx}] 单位缺失")
            units.add(unit)
            if abs(line_total - (qty * price)) > eps:
                return self._closed_loop_err(f"order.items[{idx}] line_total 与 数量*单价 不一致")
            total += line_total
            total_qty += qty
            if not item.get("product_id") and not (
                item.get("product_name") and item.get("product_resolution")
            ):
                return self._closed_loop_err(f"order.items[{idx}] 缺少产品实体/解析方式")
        order_total = self._closed_loop_dec(order.get("total_amount"))
        if order_total is None:
            return self._closed_loop_err("order.total_amount 非法")
        if abs(order_total - total) > eps:
            return self._closed_loop_err("order.total_amount 与明细合计不一致")
        if not order.get("customer_id") and not (
            order.get("customer_name") and order.get("customer_resolution")
        ):
            return self._closed_loop_err("order 缺少客户实体/解析方式")
        currency = order.get("currency")
        if not isinstance(currency, str) or not currency.strip():
            return self._closed_loop_err("order.currency 缺失")

        fulfillment = payload["fulfillment"]
        f_req = fulfillment.get("requested")
        if not isinstance(f_req, bool):
            return self._closed_loop_err("fulfillment.requested 必须为 bool")
        # 复合契约 quote -> confirm -> deliver 使履行成为必需：requested 必须为 True。
        if f_req is not True:
            return self._closed_loop_err("fulfillment.requested 必须为 True（履行是契约必需）")
        f_qty = self._closed_loop_dec(fulfillment.get("quantity"))
        if f_qty is None:
            return self._closed_loop_err("fulfillment.quantity 非法")
        if f_qty <= 0:
            return self._closed_loop_err("fulfillment.quantity 必须为正")
        # 履行数量必须与订购总量（各明细数量之和）一致，绝不可与货币合计比较
        if abs(f_qty - total_qty) > eps:
            return self._closed_loop_err("fulfillment.quantity 与订购总量不一致")
        f_unit = fulfillment.get("unit")
        if f_unit not in units:
            return self._closed_loop_err("fulfillment.unit 与明细单位不一致")

        invoice = payload["invoice"]
        inv_req = invoice.get("requested")
        if not isinstance(inv_req, bool):
            return self._closed_loop_err("invoice.requested 必须为 bool")
        if inv_req:
            inv_amt = self._closed_loop_dec(invoice.get("amount"))
            if inv_amt is None:
                return self._closed_loop_err("invoice.amount 非法")
            if inv_amt <= 0:
                return self._closed_loop_err("invoice.amount 必须为正")
            if abs(inv_amt - order_total) > eps:
                return self._closed_loop_err("invoice.amount 与订单总额不一致")
            if invoice.get("currency") != currency:
                return self._closed_loop_err("invoice.currency 与订单币种不一致")

        pa = payload["payment_allocation"]
        pa_req = pa.get("requested")
        if not isinstance(pa_req, bool):
            return self._closed_loop_err("payment_allocation.requested 必须为 bool")
        if pa_req:
            pay_amt = self._closed_loop_dec(pa.get("amount"))
            if pay_amt is None:
                return self._closed_loop_err("payment_allocation.amount 非法")
            if pay_amt <= 0:
                return self._closed_loop_err("payment_allocation.amount 必须为正")
            if abs(pay_amt - order_total) > eps:
                return self._closed_loop_err("payment_allocation.amount 与订单总额不一致")
            if pa.get("currency") != currency:
                return self._closed_loop_err("payment_allocation.currency 与订单币种不一致")
        # 矛盾组合：不开票却要求收款分配 → 拒绝（履行/开票/收款顺序契约）。
        if inv_req is False and pa_req is True:
            return self._closed_loop_err(
                "invoice.requested=False 与 payment_allocation.requested=True 矛盾"
            )
        return None

    @staticmethod
    def _closed_loop_err(message: str) -> dict[str, Any]:
        return {
            "success": False,
            "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
            "message": message,
            "failed_step": "validation",
        }

    @staticmethod
    def _closed_loop_dec(value: Any) -> Decimal | None:
        """安全地将载荷数值转为**有限** ``Decimal``。

        reject Python bool / None / NaN / Infinity / -Infinity，并捕获
        ``decimal.InvalidOperation``（含 ``TypeError/ValueError``），以确保任何
        畸形数值都返回结构化失败而非逃逸异常。
        """
        if isinstance(value, bool) or value is None:
            return None
        try:
            dec = Decimal(str(value))
        except (TypeError, ValueError, InvalidOperation):
            return None
        if not dec.is_finite():
            return None
        return dec

    @staticmethod
    def _closed_loop_coerce_id(value: Any, step: str, label: str) -> int:
        """安全地把实体 id 转为 int；畸形 id（非数字字符串等）→ 结构化失败而非逃逸。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ClosedLoopExecutionError(step, f"{label} 非法: {value!r}") from None

    @staticmethod
    def _closed_loop_order_no(idempotency_key: str, tenant_id: int) -> str:
        digest = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()[:16]
        return f"CL{int(tenant_id)}-{digest}"

    def _closed_loop_run(
        self,
        db,
        payload: dict[str, Any],
        tenant_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        order = payload["order"]
        fulfillment = payload["fulfillment"]
        invoice = payload["invoice"]
        pa = payload["payment_allocation"]

        customer = self._closed_loop_resolve_customer(db, order, tenant_id)
        products = self._closed_loop_resolve_products(db, order, tenant_id)
        warehouse = self._closed_loop_resolve_warehouse(db, fulfillment, tenant_id)

        # 复合幂等指纹：对解析后的完整业务载荷做 SHA-256 规范编码，用于逐字段级重放一致性。
        fingerprint = self._closed_loop_composite_fingerprint(
            customer, products, warehouse, order, fulfillment, invoice, pa
        )

        order_no = self._closed_loop_order_no(idempotency_key, tenant_id)
        quote_data = {
            "customer_id": customer["id"],
            "items": [
                {
                    "product_id": p["product_id"],
                    "quantity": float(p["quantity"]),
                    "unit_price": float(p["unit_price"]),
                    "unit": p["unit"],
                    "product_name": p["product_name"],
                }
                for p in products
            ],
            "order_no": order_no,
            "idempotency_key": idempotency_key,
            "currency": order.get("currency", "CNY"),
        }
        quote_res = self.quote(quote_data, db=db)
        if not quote_res.get("success"):
            raise ClosedLoopExecutionError("quote", quote_res.get("message", "报价创建失败"))
        replayed = bool(quote_res.get("idempotent"))
        order_id = int(quote_res["data"]["id"])
        order_no = quote_res["data"]["order_no"]

        if replayed:
            # 任一后续 confirm/deliver/invoice/payment 之前：校验完整复合载荷指纹一致。
            self._closed_loop_verify_idempotent_fingerprint(db, order_id, fingerprint)
        else:
            # 首建：在同一外层事务内持久化复合指纹（命名空间化，不破坏顶层 idempotency 标记）。
            self._closed_loop_persist_fingerprint(db, order_id, fingerprint)

        confirm_res = self.confirm(order_id, db=db)
        if not confirm_res.get("success"):
            raise ClosedLoopExecutionError(
                "confirm", confirm_res.get("message", "确认销售订单失败")
            )

        order_items = (
            db.query(SalesOrderItem)
            .filter(SalesOrderItem.order_id == order_id)
            .order_by(SalesOrderItem.id.asc())
            .all()
        )
        item_ids = [oi.id for oi in order_items]
        fulfillment_results = []
        for idx, oi in enumerate(order_items):
            deliver_key = f"{idempotency_key}:line:{idx}"
            deliver_res = self.deliver(
                order_id,
                oi.id,
                float(oi.quantity),
                warehouse_id=warehouse["id"],
                product_id=oi.product_id,
                idempotency_key=deliver_key,
                db=db,
            )
            if not deliver_res.get("success"):
                raise ClosedLoopExecutionError("deliver", deliver_res.get("message", "交付失败"))
            fulfillment_results.append(deliver_res)

        invoice_entry_id = None
        if invoice.get("requested"):
            invoice_res = self.invoice(order_id, amount=float(order["total_amount"]), db=db)
            if not invoice_res.get("success"):
                raise ClosedLoopExecutionError("invoice", invoice_res.get("message", "开票失败"))
            invoice_entry_id = invoice_res.get("entry_id") or (
                (invoice_res.get("data") or {}).get("id")
            )

        payment_allocation_id = None
        if pa.get("requested"):
            payment_res = self.payment(order_id, amount=float(order["total_amount"]), db=db)
            if not payment_res.get("success"):
                raise ClosedLoopExecutionError("payment", payment_res.get("message", "收款失败"))
            payment_allocation_id = (payment_res.get("data") or {}).get("id")

        order_obj = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if order_obj is None:
            raise ClosedLoopExecutionError("postconditions", "订单后置条件读取失败")
        return {
            "success": True,
            "idempotency_key": idempotency_key,
            "replayed": replayed,
            "data": {
                "order_id": order_id,
                "order_no": order_no,
                "item_ids": item_ids,
                "fulfillment": fulfillment_results,
                "invoice_entry_id": invoice_entry_id,
                "payment_allocation_id": payment_allocation_id,
                "postconditions": {
                    "state": order_obj.state,
                    "fulfillment": order_obj.fulfillment_state(),
                    "invoice_status": order_obj.invoice_status,
                    "payment_state": order_obj.payment_state,
                    "total_amount": (
                        float(order_obj.total_amount) if order_obj.total_amount is not None else 0.0
                    ),
                    "paid_amount": (
                        float(order_obj.paid_amount) if order_obj.paid_amount is not None else 0.0
                    ),
                },
            },
        }

    @staticmethod
    def _closed_loop_canon_dec(value: Any) -> str:
        """把数值规范化为无指数的定点字符串，保证指纹跨调用稳定。"""
        dec = SalesAppService._closed_loop_dec(value)
        if dec is None:
            return "none"
        return format(dec, "f")

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
        """对解析后的完整复合业务载荷做冲突安全的 SHA-256 规范编码。

        覆盖：解析后的客户 ID/名称、产品 ID/名称/顺序/数量/单位/单价/行合计、
        订单币种/总额、解析后的仓库 ID、履行 requested/quantity/unit、
        开票 requested/amount/currency、收款分配 requested/amount/currency。
        """
        canonical = {
            "customer_id": customer["id"],
            "customer_name": customer["name"],
            "currency": order.get("currency"),
            "total_amount": SalesAppService._closed_loop_canon_dec(order.get("total_amount")),
            "items": [
                {
                    "product_id": p["product_id"],
                    "product_name": p["product_name"],
                    "quantity": SalesAppService._closed_loop_canon_dec(p["quantity"]),
                    "unit": p["unit"],
                    "unit_price": SalesAppService._closed_loop_canon_dec(p["unit_price"]),
                    "line_total": SalesAppService._closed_loop_canon_dec(
                        Decimal(str(p["quantity"])) * Decimal(str(p["unit_price"]))
                    ),
                }
                for p in products
            ],
            "warehouse_id": warehouse["id"],
            "fulfillment": {
                "requested": fulfillment.get("requested"),
                "quantity": SalesAppService._closed_loop_canon_dec(fulfillment.get("quantity")),
                "unit": fulfillment.get("unit"),
            },
            "invoice": {
                "requested": invoice.get("requested"),
                "amount": SalesAppService._closed_loop_canon_dec(invoice.get("amount")),
                "currency": invoice.get("currency"),
            },
            "payment_allocation": {
                "requested": pa.get("requested"),
                "amount": SalesAppService._closed_loop_canon_dec(pa.get("amount")),
                "currency": pa.get("currency"),
            },
        }
        canonical_str = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _closed_loop_extract_fingerprint(remark: str | None) -> str | None:
        """从既有 remark 字段中提取命名空间化的复合幂等指纹。"""
        if not remark:
            return None
        prefix = f"{_CLOSED_LOOP_FP_PREFIX}:"
        for part in remark.split("\n"):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix) :]
        return None

    def _closed_loop_verify_idempotent_fingerprint(
        self, db, order_id: int, fingerprint: str
    ) -> None:
        """同租户同 ``idempotency_key`` 但完整复合载荷指纹不一致 → fail-closed。

        在任一后续 confirm/deliver/invoice/payment 之前校验；不一致则抛出
        ``ClosedLoopExecutionError(step="idempotency")`` 触发外层事务整体回滚，
        绝不静默复用既有单，也不执行任何后续拥有方副作用。
        """
        order_obj = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if order_obj is None:
            raise ClosedLoopExecutionError("idempotency", "幂等订单读取失败")
        persisted = self._closed_loop_extract_fingerprint(order_obj.remark)
        if persisted is None or persisted != fingerprint:
            raise ClosedLoopExecutionError(
                "idempotency",
                "同 idempotency_key 但完整复合业务载荷与既有订单不一致，拒绝执行",
            )

    def _closed_loop_persist_fingerprint(self, db, order_id: int, fingerprint: str) -> None:
        """在同一外层事务内把复合指纹命名空间化写入既有 remark 字段。

        保留既有顶层 ``idempotency:sales_quote:{key}`` 标记不动，仅追加指纹标记，
        使 quote() 的幂等查询（前缀匹配）与复合重放校验都能兼容工作。
        """
        order_obj = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if order_obj is None:
            raise ClosedLoopExecutionError("idempotency", "幂等订单写入失败")
        fp_marker = f"{_CLOSED_LOOP_FP_PREFIX}:{fingerprint}"
        base = order_obj.remark or ""
        if fp_marker in base:
            return
        order_obj.remark = f"{base}\n{fp_marker}" if base else fp_marker

    def _closed_loop_resolve_customer(
        self, db, order: dict[str, Any], tenant_id: int
    ) -> dict[str, Any]:
        cid = order.get("customer_id")
        if cid is not None:
            # 显式 current-tenant 校验：即便全局 tenant filter 生效，仍显式限定租户。
            cid_int = self._closed_loop_coerce_id(cid, "resolve_customer", "customer_id")
            customer = (
                db.query(Customer)
                .filter(Customer.id == cid_int, Customer.tenant_id == tenant_id)
                .first()
            )
            if customer is None:
                raise ClosedLoopExecutionError(
                    "resolve_customer", f"当前租户下客户不存在: id={cid}"
                )
            return {"id": customer.id, "name": customer.customer_name}
        cname = order.get("customer_name")
        resolution = order.get("customer_resolution")
        if resolution != "current_tenant_exact_name":
            raise ClosedLoopExecutionError(
                "resolve_customer", f"不支持的客户解析方式: {resolution}"
            )
        matches = (
            db.query(Customer)
            .filter(Customer.customer_name == cname, Customer.tenant_id == tenant_id)
            .count()
        )
        if matches != 1:
            raise ClosedLoopExecutionError(
                "resolve_customer", f"客户名匹配数为 {matches}（应为恰好 1）: {cname}"
            )
        customer = (
            db.query(Customer)
            .filter(Customer.customer_name == cname, Customer.tenant_id == tenant_id)
            .first()
        )
        return {"id": customer.id, "name": customer.customer_name}

    def _closed_loop_resolve_products(
        self, db, order: dict[str, Any], tenant_id: int
    ) -> list[dict[str, Any]]:
        resolved = []
        for idx, item in enumerate(order["items"]):
            pid = item.get("product_id")
            if pid is not None:
                pid_int = self._closed_loop_coerce_id(pid, "resolve_product", "product_id")
                product = (
                    db.query(Product)
                    .filter(Product.id == pid_int, Product.tenant_id == tenant_id)
                    .first()
                )
                if product is None:
                    raise ClosedLoopExecutionError(
                        "resolve_product", f"当前租户下产品不存在: id={pid}"
                    )
            else:
                pname = item.get("product_name")
                resolution = item.get("product_resolution")
                if resolution != "current_tenant_exact_name":
                    raise ClosedLoopExecutionError(
                        "resolve_product", f"不支持的产品解析方式: {resolution}"
                    )
                matches = (
                    db.query(Product)
                    .filter(Product.name == pname, Product.tenant_id == tenant_id)
                    .count()
                )
                if matches != 1:
                    raise ClosedLoopExecutionError(
                        "resolve_product",
                        f"产品名匹配数为 {matches}（应为恰好 1）: {pname}",
                    )
                product = (
                    db.query(Product)
                    .filter(Product.name == pname, Product.tenant_id == tenant_id)
                    .first()
                )
            unit = item.get("unit")
            if product.unit and product.unit != unit:
                raise ClosedLoopExecutionError(
                    "resolve_product",
                    f"产品单位不匹配: 产品={product.unit} vs 载荷={unit}",
                )
            resolved.append(
                {
                    "product_id": product.id,
                    "unit": unit,
                    "quantity": Decimal(str(item["quantity"])),
                    "unit_price": Decimal(str(item["unit_price"])),
                    "product_name": product.name,
                }
            )
        return resolved

    def _closed_loop_resolve_warehouse(
        self, db, fulfillment: dict[str, Any], tenant_id: int
    ) -> dict[str, Any]:
        wid = fulfillment.get("warehouse_id")
        if wid is not None:
            wid_int = self._closed_loop_coerce_id(wid, "resolve_warehouse", "warehouse_id")
            wh = (
                db.query(Warehouse)
                .filter(Warehouse.id == wid_int, Warehouse.tenant_id == tenant_id)
                .first()
            )
            if wh is None:
                raise ClosedLoopExecutionError(
                    "resolve_warehouse", f"当前租户下仓库不存在: id={wid}"
                )
            return {"id": wh.id, "code": wh.code}
        resolution = fulfillment.get("warehouse_resolution")
        if resolution != "current_tenant_default":
            raise ClosedLoopExecutionError(
                "resolve_warehouse", f"不支持的仓库解析方式: {resolution}"
            )
        wh = (
            db.query(Warehouse)
            .filter(Warehouse.status == "active", Warehouse.tenant_id == tenant_id)
            .order_by(Warehouse.id.asc())
            .first()
        )
        if wh is None:
            raise ClosedLoopExecutionError("resolve_warehouse", "当前租户下无可用仓库")
        return {"id": wh.id, "code": wh.code}

    # ── 工具内部 ───────────────────────────────────────────────

    @staticmethod
    def _generate_order_no() -> str:
        return f"SO{datetime.now().strftime('%Y%m%d%H%M%S')}"


__all__ = ["SalesAppService", "SALES_ORDER_STATUS_FLOW"]
