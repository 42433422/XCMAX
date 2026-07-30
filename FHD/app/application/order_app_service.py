"""订单应用服务 — 域事件样板闭环（非全域落地）。

仅覆盖「创建订单成功 → ``get_order_domain().emit_order_created``」一条样板路径，
用于证明 Application 成功提交后真 emit；不代表订单域已全面事件驱动。
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 样板路径：内存订单投影（成功提交后的可查询状态，非生产持久化）
_SAMPLE_ORDERS: dict[str, dict[str, Any]] = {}


def get_sample_order(order_id: str) -> dict[str, Any] | None:
    """查询样板路径写入的订单投影（仅测试 / 样板断言用）。"""
    record = _SAMPLE_ORDERS.get(order_id)
    return dict(record) if record else None


def clear_sample_orders() -> None:
    """清空样板订单投影（单测隔离）。"""
    _SAMPLE_ORDERS.clear()


class OrderAppService:
    """订单应用服务（样板：create_order 成功路径 emit）。"""

    def create_order(
        self,
        *,
        customer_id: str,
        items: list[dict[str, Any]] | None = None,
        total_amount: Decimal | float | str | None = None,
    ) -> dict[str, Any]:
        """创建订单用例（样板闭环入口）。

        成功提交本地投影后调用 ``get_order_domain().emit_order_created``。
        """
        customer_id = (customer_id or "").strip()
        if not customer_id:
            return {"success": False, "message": "customer_id 不能为空"}

        order_items = list(items or [])
        if total_amount is None:
            amount = Decimal("0")
            for item in order_items:
                qty = Decimal(str(item.get("quantity", 0) or 0))
                price = Decimal(str(item.get("unit_price", 0) or 0))
                amount += qty * price
        else:
            amount = Decimal(str(total_amount))

        order_id = f"ord-{uuid.uuid4().hex[:12]}"
        record = {
            "order_id": order_id,
            "customer_id": customer_id,
            "items": order_items,
            "total_amount": str(amount),
            "status": "created",
        }
        # 样板「提交」：写入可查询内存投影（代替真实 DB commit）
        _SAMPLE_ORDERS[order_id] = record

        try:
            from app.neuro_bus.domains.order_domain import get_order_domain

            # 样板路径：业务成功后真 emit（全域其它用例尚未接入）
            emitted = get_order_domain().emit_order_created(
                order_id=order_id,
                customer_id=customer_id,
                items=order_items,
                total_amount=amount,
            )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("样板路径 emit order.created 失败: %s", exc)
            emitted = False

        return {
            "success": True,
            "message": "订单创建成功（样板路径）",
            "order_id": order_id,
            "data": dict(record),
            "emitted": bool(emitted),
        }


_order_app_service: OrderAppService | None = None


def get_order_app_service() -> OrderAppService:
    global _order_app_service
    if _order_app_service is None:
        _order_app_service = OrderAppService()
    return _order_app_service
