"""
收款分配 / 退款 / 冲销模块（W1-05）

吸收 Odoo 18 ``account.payment`` 能力：调用通用平衡记账 API
``app.services.accounting_services.create_journal_entry`` 生成
``借库存现金(1001) / 贷应收账款(1122)`` 的收款凭证，并写入
``receivable_allocations`` 分配（unpaid / partial / paid / refunded）。

- 累计收款不超应收（超收被拒）；
- 同单同金额重复收款幂等（不重复生成凭证）；
- 全额 → paid；
- refund/reversal 生成反向凭证，原分配更新为 refunded，并新建冲销分配
  （``reversed_of_id`` 关联原始分配）承载反向凭证。

金额比较全部使用 ``Decimal`` 避免浮点误差；凭证与分配均在 ``with get_db()``
上下文内执笔，由该上下文在成功退出时统一提交、异常时回滚（服务内不显式
``commit``/``rollback``），与 W1-04 ``create_journal_entry(db=...)`` 一致。
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from app.db.models import ReceivableAllocation, SalesOrder
from app.db.models.receivable_allocation import (
    RECEIVABLE_STATUS_PAID,
    RECEIVABLE_STATUS_PARTIAL,
    RECEIVABLE_STATUS_REFUNDED,
    RECEIVABLE_STATUS_UNPAID,
)
from app.db.session import get_db
from app.services.accounting_services import create_journal_entry

# 收款凭证科目（Odoo 默认科目 code）
CASH_ACCOUNT_CODE = "1001"
RECEIVABLE_ACCOUNT_CODE = "1122"

# 金额比较容差（Decimal，避免浮点误差）
_MONEY_EPSILON = Decimal("0.005")


def _to_decimal(value: Any) -> Decimal:
    """任意金额输入安全转为 Decimal（None → 0）。"""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _compute_status(paid: Decimal, receivable: Decimal) -> str:
    """根据累计收款与应收计算付款状态。"""
    if paid + _MONEY_EPSILON >= receivable:
        return RECEIVABLE_STATUS_PAID
    if paid > 0:
        return RECEIVABLE_STATUS_PARTIAL
    return RECEIVABLE_STATUS_UNPAID


def _existing_allocations(db, sales_order_id: int) -> list[ReceivableAllocation]:
    """订单当前生效（未退款）的收款分配。"""
    return cast(
        "list[ReceivableAllocation]",
        db.query(ReceivableAllocation)
        .filter(
            ReceivableAllocation.sales_order_id == int(sales_order_id),
            ReceivableAllocation.status != RECEIVABLE_STATUS_REFUNDED,
        )
        .all(),
    )


def _sum_allocated(allocations: list[ReceivableAllocation]) -> Decimal:
    return sum((_to_decimal(a.allocated_amount) for a in allocations), Decimal("0"))


def payment(
    *,
    sales_order_id: int,
    amount: Any,
    partner_id: int | None = None,
    partner_name: str | None = None,
    reference: str | None = None,
    journal_date: date | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """登记一笔收款。

    调用 ``create_journal_entry`` 过账 ``借现金1001 / 贷应收1122``，并写入
    ``ReceivableAllocation``。超收被拒；同单同金额幂等；全额 → paid。
    可选 ``db``：调用方持有的会话，提供时使用该精确对象且**不**调用 ``get_db()``，
    也**不** commit/rollback/close（由调用方负责）；缺省时沿用 ``get_db()`` 自带事务。
    """
    amount_dec = _to_decimal(amount)
    if amount_dec <= 0:
        return {"success": False, "message": "收款金额必须大于 0"}

    owned = db is None
    cm = nullcontext(db) if not owned else get_db()
    with cm as ctx:
        order = ctx.query(SalesOrder).filter(SalesOrder.id == int(sales_order_id)).first()
        if order is None:
            return {"success": False, "message": f"销售订单不存在: sales_order_id={sales_order_id}"}

        receivable = _to_decimal(order.total_amount)
        existing = _existing_allocations(ctx, sales_order_id)
        current_allocated = _sum_allocated(existing)

        # 同单同金额幂等：已存在未退款且金额一致 → 直接返回，不重复记账
        for alloc in existing:
            if _to_decimal(alloc.allocated_amount) == amount_dec:
                return {
                    "success": True,
                    "idempotent": True,
                    "message": "该订单已存在相同金额的收款分配，幂等返回",
                    "data": alloc.to_dict(),
                }

        # 累计收款不超应收（超收被拒）
        new_total = current_allocated + amount_dec
        if new_total > receivable + _MONEY_EPSILON:
            return {
                "success": False,
                "message": (
                    f"累计收款超应收被拒: 应收 ¥{receivable}，"
                    f"已收 ¥{current_allocated}，本次 ¥{amount_dec}"
                ),
            }

        entry_result = create_journal_entry(
            {
                "journal_date": journal_date or date.today(),
                "description": f"收款-订单{sales_order_id}"
                + (f"-{reference}" if reference else ""),
                "reference_type": "payment",
                "reference_id": int(sales_order_id),
                "lines": [
                    {
                        "account_code": CASH_ACCOUNT_CODE,
                        "account_name": "库存现金",
                        "debit": amount_dec,
                        "credit": 0,
                    },
                    {
                        "account_code": RECEIVABLE_ACCOUNT_CODE,
                        "account_name": "应收账款",
                        "debit": 0,
                        "credit": amount_dec,
                        "partner_id": partner_id,
                        "partner_name": partner_name,
                    },
                ],
            },
            db=ctx,  # 与分配在同一事务内执笔（不自行提交/回滚）
        )
        if not entry_result.get("success"):
            return entry_result

        entry_data = entry_result.get("data") or {}
        entry_id = entry_data.get("id")
        line_id = _find_line_id(entry_data, RECEIVABLE_ACCOUNT_CODE)

        status = _compute_status(new_total, receivable)
        alloc = ReceivableAllocation(
            sales_order_id=int(sales_order_id),
            journal_entry_id=entry_id,
            line_id=line_id,
            amount=amount_dec,
            allocated_amount=amount_dec,
            status=status,
            reference_type="payment",
            reference_id=int(sales_order_id),
            allocated_at=datetime.now(),
        )
        ctx.add(alloc)
        order.paid_amount = new_total
        order.payment_state = status
        # 事务由调用方（get_db 或外部持有者）在外层提交；此处仅 flush 获取 id 并刷新
        ctx.flush()
        ctx.refresh(alloc)

        return {
            "success": True,
            "message": (f"收款成功 ¥{amount_dec}，累计 ¥{new_total}，状态 {status}"),
            "data": alloc.to_dict(),
        }


def refund(
    *,
    allocation_id: int,
    reference: str | None = None,
    journal_date: date | None = None,
) -> dict[str, Any]:
    """收款退款/冲销。

    对该收款分配生成反向凭证（借应收1122 / 贷现金1001），并将分配更新为 refunded。
    """
    with get_db() as db:
        alloc = (
            db.query(ReceivableAllocation)
            .filter(ReceivableAllocation.id == int(allocation_id))
            .first()
        )
        if alloc is None:
            return {"success": False, "message": f"收款分配不存在: allocation_id={allocation_id}"}
        if alloc.status == RECEIVABLE_STATUS_REFUNDED:
            return {
                "success": True,
                "idempotent": True,
                "message": "该收款分配已退款/冲销，幂等返回",
                "data": alloc.to_dict(),
            }

        amount_dec = _to_decimal(alloc.allocated_amount)

        entry_result = create_journal_entry(
            {
                "journal_date": journal_date or date.today(),
                "description": f"收款退款/冲销-分配{allocation_id}"
                + (f"-{reference}" if reference else ""),
                "reference_type": "refund",
                "reference_id": int(allocation_id),
                "lines": [
                    {
                        "account_code": RECEIVABLE_ACCOUNT_CODE,
                        "account_name": "应收账款",
                        "debit": amount_dec,
                        "credit": 0,
                    },
                    {
                        "account_code": CASH_ACCOUNT_CODE,
                        "account_name": "库存现金",
                        "debit": 0,
                        "credit": amount_dec,
                    },
                ],
            },
            db=db,  # 与分配更新在同一 ``with get_db()`` 事务内执笔（不自行提交/回滚）
        )
        if not entry_result.get("success"):
            return entry_result

        alloc.status = RECEIVABLE_STATUS_REFUNDED
        alloc.allocated_at = datetime.now()
        entry_data = entry_result.get("data") or {}
        entry_id = entry_data.get("id")
        line_id = _find_line_id(entry_data, RECEIVABLE_ACCOUNT_CODE)
        # 冲销分配：reversed_of_id 关联原始分配，并承载反向凭证
        reversal = ReceivableAllocation(
            sales_order_id=alloc.sales_order_id,
            journal_entry_id=entry_id,
            line_id=line_id,
            amount=amount_dec,
            allocated_amount=amount_dec,
            status=RECEIVABLE_STATUS_REFUNDED,
            reference_type="reversal",
            reference_id=int(allocation_id),
            reversed_of_id=int(allocation_id),
            allocated_at=datetime.now(),
        )
        db.add(reversal)
        # 更新订单支付状态与累计已收
        if alloc.sales_order_id is not None:
            _update_order_after_refund(db, alloc)
        # 事务由 ``get_db`` 上下文在成功退出时提交；此处仅 flush 获取 id 并刷新
        db.flush()
        db.refresh(reversal)

        return {
            "success": True,
            "message": f"收款已退款/冲销 ¥{amount_dec}",
            "data": reversal.to_dict(),
        }


def _update_order_after_refund(db, alloc: ReceivableAllocation) -> None:
    """退款后重算订单累计已收与付款状态。"""
    order = db.query(SalesOrder).filter(SalesOrder.id == alloc.sales_order_id).first()
    if order is None:
        return
    # 显式把本次退款分配排除（兼容 autoflush=False 的会话，内存状态未落库）
    if alloc.sales_order_id is None:
        return
    remaining = _sum_allocated(
        [a for a in _existing_allocations(db, alloc.sales_order_id) if a.id != alloc.id]
    )
    order.paid_amount = remaining
    order.payment_state = _compute_status(remaining, _to_decimal(order.total_amount))


def _find_line_id(entry_data: dict[str, Any], account_code: str) -> int | None:
    """在记账凭证返回的明细行中按科目 code 定位分录行 id。"""
    for line in entry_data.get("lines") or []:
        if line.get("account_code") == account_code:
            return cast("int | None", line.get("id"))
    return None


__all__ = ["payment", "refund"]
