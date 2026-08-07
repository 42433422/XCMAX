"""
补货建议服务（Inventory replenishment）

吸收 Odoo 18 的补货逻辑（replenishment / reorder rules）：对低于安全库存(min_stock)
的物料，建议补货至 max_stock，并给出建议采购数量与参考供应商。
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.models import Material
from app.db.session import get_db

logger = logging.getLogger(__name__)


def suggest_replenishment(
    threshold: float | None = None,
    per_page: int = 50,
) -> dict[str, Any]:
    """返回需要补货的物料与建议采购量。

    建议采购量 = max_stock - 当前库存（当 max_stock 合理时）；否则至少补到 min_stock。
    """
    with get_db() as db:
        query = db.query(Material).filter(Material.is_active == 1)
        if threshold is not None:
            query = query.filter(Material.quantity <= threshold)
        else:
            query = query.filter(Material.quantity <= Material.min_stock)
        materials = query.order_by(Material.quantity.asc()).limit(int(per_page)).all()

        suggestions = []
        for m in materials:
            current = float(m.quantity or 0.0)
            min_stock = float(m.min_stock or 0.0)
            max_stock = float(m.max_stock or 0.0)
            if max_stock > min_stock:
                suggest_qty = max(max_stock - current, 0.0)
            else:
                suggest_qty = max(min_stock - current, 0.0)
            suggestions.append(
                {
                    "material_id": m.id,
                    "material_code": m.material_code,
                    "name": m.name,
                    "category": m.category,
                    "specification": m.specification,
                    "unit": m.unit,
                    "current_quantity": current,
                    "min_stock": min_stock,
                    "max_stock": max_stock,
                    "suggest_quantity": suggest_qty,
                    "unit_price": float(m.unit_price or 0.0),
                    "suggest_amount": round(suggest_qty * float(m.unit_price or 0.0), 2),
                    "supplier": m.supplier,
                    "warehouse_location": m.warehouse_location,
                }
            )

        return {
            "success": True,
            "data": suggestions,
            "count": len(suggestions),
            "summary": {
                "total_low_stock": len(suggestions),
                "total_suggest_amount": round(
                    sum(s["suggest_amount"] for s in suggestions), 2
                ),
            },
        }


__all__ = ["suggest_replenishment"]