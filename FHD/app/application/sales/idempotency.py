"""Composite replay identity and legacy-payment reconciliation within the same transaction."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ReceivableAllocation, SalesOrder
from app.infrastructure.tenant_scope import apply_tenant_filter

from .contracts import ClosedLoopExecutionError
from .validation import canonical_decimal

CLOSED_LOOP_FP_PREFIX = "w1-10-closed-loop-composite"


def closed_loop_order_no(idempotency_key: str, tenant_id: int) -> str:
    digest = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()[:16]
    return f"CL{int(tenant_id)}-{digest}"


def composite_fingerprint(
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
        "total_amount": canonical_decimal(order.get("total_amount")),
        "items": [
            {
                "product_id": p["product_id"],
                "product_name": p["product_name"],
                "quantity": canonical_decimal(p["quantity"]),
                "unit": p["unit"],
                "unit_price": canonical_decimal(p["unit_price"]),
                "line_total": canonical_decimal(
                    Decimal(str(p["quantity"])) * Decimal(str(p["unit_price"]))
                ),
            }
            for p in products
        ],
        "warehouse_id": warehouse["id"],
        "fulfillment": {
            "requested": fulfillment.get("requested"),
            "quantity": canonical_decimal(fulfillment.get("quantity")),
            "unit": fulfillment.get("unit"),
        },
        "invoice": {
            "requested": invoice.get("requested"),
            "amount": canonical_decimal(invoice.get("amount")),
            "currency": invoice.get("currency"),
        },
        "payment_allocation": {
            "requested": pa.get("requested"),
            "amount": canonical_decimal(pa.get("amount")),
            "currency": pa.get("currency"),
        },
    }
    canonical_str = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def extract_fingerprint(remark: str | None) -> str | None:
    """从既有 remark 字段中提取命名空间化的复合幂等指纹。"""
    if not remark:
        return None
    prefix = f"{CLOSED_LOOP_FP_PREFIX}:"
    for part in remark.split("\n"):
        part = part.strip()
        if part.startswith(prefix):
            return part[len(prefix) :]
    return None


def persist_fingerprint(db: Session, order_id: int, fingerprint: str) -> None:
    """在同一外层事务内把复合指纹命名空间化写入既有 remark 字段。

    保留既有顶层 ``idempotency:sales_quote:{key}`` 标记不动，仅追加指纹标记，
    使 quote() 的幂等查询（前缀匹配）与复合重放校验都能兼容工作。
    """
    order_obj = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if order_obj is None:
        raise ClosedLoopExecutionError("idempotency", "幂等订单写入失败")
    fp_marker = f"{CLOSED_LOOP_FP_PREFIX}:{fingerprint}"
    base = order_obj.remark or ""
    if fp_marker in base:
        return
    order_obj.remark = f"{base}\n{fp_marker}" if base else fp_marker


def verify_fingerprint(db: Session, order_id: int, fingerprint: str) -> None:
    """同租户同 ``idempotency_key`` 但完整复合载荷指纹不一致 → fail-closed。

    在任一后续 confirm/deliver/invoice/payment 之前校验；不一致则抛出
    ``ClosedLoopExecutionError(step="idempotency")`` 触发外层事务整体回滚，
    绝不静默复用既有单，也不执行任何后续拥有方副作用。
    """
    order_obj = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if order_obj is None:
        raise ClosedLoopExecutionError("idempotency", "幂等订单读取失败")
    persisted = extract_fingerprint(order_obj.remark)
    if persisted is None or persisted != fingerprint:
        raise ClosedLoopExecutionError(
            "idempotency", "同 idempotency_key 但完整复合业务载荷与既有订单不一致，拒绝执行"
        )


def verify_payment_replay(db: Session, order_id: int, payment_key: str, tenant_id: int) -> None:
    keys = {
        row[0]
        for row in apply_tenant_filter(
            db.query(ReceivableAllocation.request_key), ReceivableAllocation, tenant_id=tenant_id
        ).filter(
            ReceivableAllocation.sales_order_id == order_id,
            ReceivableAllocation.reference_type == "payment",
        )
    }
    if None in keys and payment_key not in keys:
        raise ClosedLoopExecutionError(
            "payment_reconciliation",
            "旧收款缺少请求身份（含已退款记录），须人工核对，禁止自动再次收款",
        )
