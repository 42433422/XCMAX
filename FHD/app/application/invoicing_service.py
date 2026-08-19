"""
开票/贷项通知单 & 记账服务（ODOO-W1-04）

吸收 Odoo 18 account.move 开票能力：

- ``invoice()``：为销售订单生成平衡凭证
  ``借应收账款(1122, partner) / 贷主营业务收入(6001)``，
  ``reference_type='sale'``、``reference_id=order_id``。
- **invoice status 独立计算**：开票不依赖发货，可先开票后发货。
- ``credit_note()``：生成反向凭证并经 ``reversed_of_id`` 关联原销售凭证。
- **幂等**：重复 ``invoice()`` 不重复生成凭证。

复用 ``app/services/accounting_services.py`` 的通用平衡记账 API
（``create_sale_invoice_entry`` / ``create_credit_note_entry``），不复制记账逻辑。
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from typing import Any, cast

from app.db.models import JournalEntry, SalesOrder
from app.db.session import get_db
from app.infrastructure.tenant_scope import current_tenant_id
from app.services.accounting_services import create_credit_note_entry, create_sale_invoice_entry

__all__ = ["invoice", "credit_note"]


def _find_sale_entry(db, order_id: int) -> JournalEntry | None:
    """查找订单的销售开票凭证（未冲销、非贷项通知单）。

    幂等性按当前租户隔离（同一事务内）；无租户上下文时不加过滤（存量 NULL 租户数据可见）。
    """
    query = db.query(JournalEntry).filter(
        JournalEntry.reference_type == "sale",
        JournalEntry.reference_id == int(order_id),
        JournalEntry.reversed_at.is_(None),
        JournalEntry.is_credit_note == 0,
    )
    tenant_id = current_tenant_id()
    if tenant_id is not None:
        query = query.filter(JournalEntry.tenant_id == tenant_id)
    return cast("JournalEntry | None", query.order_by(JournalEntry.id.asc()).first())


def _get_order(db, order_id: int) -> SalesOrder | None:
    return cast(
        "SalesOrder | None", db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
    )


def invoice(
    order_id: int,
    *,
    partner_id: int | None = None,
    partner_name: str | None = None,
    amount: float | Decimal | None = None,
    journal_date: date | None = None,
    description: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """为销售订单生成开票平衡凭证；重复开票幂等，不重复生成。

    - 凭证：``借应收账款(1122, partner) / 贷主营业务收入(6001)``。
    - ``reference_type='sale'``、``reference_id=order_id``。
    - 未显式传入 partner/amount 时从订单读取（``customer_id`` / ``total_amount``）。
    - 开票状态独立：不校验发货（可先开票后发货）。
    - **原子**：凭证创建与 ``invoice_status`` 更新在**同一调用方事务**内提交，
      任一失败整体回滚，不留半成品业务状态。
    - 可选 ``db``：调用方持有的会话，提供时使用该精确对象且**不**调用 ``get_db()``，
      也**不** commit/rollback/close（由调用方负责）；缺省时沿用 ``get_db()`` 自带事务。
    """
    owned = db is None
    cm = nullcontext(db) if not owned else get_db()
    with cm as ctx:
        existing = _find_sale_entry(ctx, order_id)
        if existing is not None:
            return {
                "success": True,
                "message": f"订单 {order_id} 已开票，跳过重复开票",
                "duplicate": True,
                "entry_id": existing.id,
                "data": existing.to_dict(),
            }

        order = _get_order(ctx, order_id)
        if order is None:
            return {"success": False, "message": f"销售订单不存在: id={order_id}"}

        result = create_sale_invoice_entry(
            order_id,
            partner_id=partner_id if partner_id is not None else order.customer_id,
            partner_name=partner_name if partner_name is not None else order.customer_name,
            amount=amount if amount is not None else (order.total_amount or Decimal("0")),
            journal_date=journal_date,
            description=description,
            db=ctx,
        )
        if result["success"]:
            order.invoice_status = "invoiced"
        # get_db 退出时统一提交；失败整体回滚，凭证与开票状态保持一致
        return result


def credit_note(
    order_id: int,
    *,
    journal_date: date | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """为已开票订单生成贷项通知单反向凭证，经 ``reversed_of_id`` 关联原销售凭证。

    - 订单未开票 → 失败。
    - 成功后更新开票状态为 ``credit_note``；重复生成被 ``create_credit_note_entry`` 拒绝。
    - **原子**：反向凭证、原凭证 ``reversed_at`` 标记与 ``invoice_status`` 更新在
      **同一调用方事务**内提交，任一失败整体回滚。
    """
    with get_db() as db:
        original = _find_sale_entry(db, order_id)
        if original is None:
            return {
                "success": False,
                "message": f"订单 {order_id} 尚未开票，无法生成贷项通知单",
            }

        result = create_credit_note_entry(
            original.id,
            order_id=order_id,
            journal_date=journal_date,
            description=description,
            db=db,
        )
        if result["success"]:
            order = _get_order(db, order_id)
            if order is not None:
                order.invoice_status = "credit_note"
        # get_db 退出时统一提交；失败整体回滚
        return result
