"""
补货建议服务（Inventory replenishment）

吸收 Odoo 18 的补货逻辑（replenishment / reorder rules）：对低于安全库存(min_stock)
的产品，建议补货至 max_stock，并给出建议采购数量与参考金额。

W1-06 改造：
- 低库存口径与库存报表一致——按 ``InventoryLedger.available_quantity`` 聚合
  （而非 ``Material.quantity``），并用 ``Product.min_stock/max_stock`` 作为补货阈值。
- 全程 ``Decimal`` 精确运算（可用量/阈值/建议量/单价/金额），不做 float 域累加，
  避免精度残差；``Decimal`` 在 ``Numeric(18,4/6)`` 刻度下规整后返回。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.db.models import InventoryLedger, Product
from app.db.session import get_db

_DEC0 = Decimal("0")
_TWO_PLACES = Decimal("0.01")


def _dec(value: Any) -> Decimal:
    """将任意数值（int/float/str/Decimal）安全转为 Decimal，None 视为 0。

    优先用 ``str()`` 传递以保证刻度精确（避免二进制浮点误差）。
    """
    if value is None:
        return _DEC0
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def suggest_replenishment(
    threshold: float | Decimal | None = None,
    per_page: int = 50,
) -> dict[str, Any]:
    """返回需要补货的产品与建议采购量。

    低库存口径（与库存报表一致）：``min_stock > 0`` 且 ``available_quantity < min_stock``；
    也可通过 ``threshold`` 显式指定"可用量 ≤ threshold"即视为需补货。
    建议采购量 = max_stock - 当前可用量（当 max_stock > min_stock 时）；否则至少补到 min_stock。
    所有数值字段均为 Decimal，金额规整到分。
    """
    threshold_dec: Decimal | None = _dec(threshold) if threshold is not None else None

    with get_db() as db:
        # 按产品聚合可用量（跨仓库/批次），LEFT JOIN 保留无台账记录的产品（可用量为 0）。
        avail_rows = (
            db.query(
                Product.id.label("product_id"),
                func.coalesce(func.sum(InventoryLedger.available_quantity), 0).label("available"),
            )
            .outerjoin(InventoryLedger, InventoryLedger.product_id == Product.id)
            .filter(Product.is_active == 1)
            .group_by(Product.id)
            .all()
        )
        available: dict[int, Decimal] = {int(r.product_id): _dec(r.available) for r in avail_rows}

        products = (
            db.query(Product).filter(Product.is_active == 1).order_by(Product.name.asc()).all()
        )

        suggestions = []
        for p in products:
            current = available.get(int(p.id), _DEC0)
            min_stock = _dec(p.min_stock)
            max_stock = _dec(p.max_stock)

            if threshold_dec is not None:
                if current > threshold_dec:
                    continue
            elif not (min_stock > _DEC0 and current < min_stock):
                continue

            if max_stock > min_stock:
                suggest_qty = max(max_stock - current, _DEC0)
            else:
                suggest_qty = max(min_stock - current, _DEC0)
            unit_price = _dec(p.price)
            suggest_amount = (suggest_qty * unit_price).quantize(_TWO_PLACES)
            suggestions.append(
                {
                    "product_id": int(p.id),
                    "product_code": p.model_number,
                    "name": p.name,
                    "category": p.category,
                    "specification": p.specification,
                    "unit": p.unit,
                    "current_quantity": current,
                    "min_stock": min_stock,
                    "max_stock": max_stock,
                    "suggest_quantity": suggest_qty,
                    "unit_price": unit_price,
                    "suggest_amount": suggest_amount,
                }
            )

        suggestions = suggestions[: int(per_page)]

        return {
            "success": True,
            "data": suggestions,
            "count": len(suggestions),
            "summary": {
                "total_low_stock": len(suggestions),
                "total_suggest_amount": round(sum(s["suggest_amount"] for s in suggestions), 2),
            },
        }


__all__ = ["suggest_replenishment"]
