"""Route explicit product stock-in requests to the inventory tool, not business_db.write.

「产品 A100 入库 50 件」 uses the verb 入库, which the generic business-database
heuristic also claims（"入库" doubles as DB slang）. Resolving the product and the
single active warehouse at plan time keeps the write on the guarded
``inventory.stock_in`` path; ambiguous or missing targets ask the user first.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import or_

from .types import WorkflowNode

_PRODUCT_RE = re.compile(r"(?:产品|商品)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_QUANTITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:件|个|箱|桶|支|包|瓶|台|套)")
_NEGATION_WORDS = ("不要", "别", "不用", "取消", "删除", "清空")

# 方向词 → (触发正则, 工具 action, 裸数量正则)。入库/出库共用同一套解析与仓库定位逻辑。
_MOVEMENTS: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "stock_in": (re.compile(r"入库|入仓"), re.compile(r"入库\s*[:：]?\s*(\d+(?:\.\d+)?)")),
    "stock_out": (re.compile(r"出库|出仓"), re.compile(r"出库\s*[:：]?\s*(\d+(?:\.\d+)?)")),
}


def _standalone_clarify_node(question: str) -> WorkflowNode:
    """Clarification without a downstream target: resume re-plans from the answer."""
    return WorkflowNode(
        node_id=f"clarify_{uuid.uuid4().hex[:8]}",
        tool_id="clarify",
        action="ask",
        params={"question": question, "answer_key": "confirmed", "target_node_id": ""},
        risk="low",
        idempotent=True,
        description="反问澄清：入库信息不足，待用户补充后再继续",
    )


def _movement_nodes(message: str, action: str) -> list[WorkflowNode]:
    """Full resolvable slots → stock_in/stock_out node; missing/ambiguous → clarify node."""
    text = str(message or "").strip()
    label = "入库" if action == "stock_in" else "出库"
    trigger_re, plain_qty_re = _MOVEMENTS[action]
    # "入库到数据库" 之类仍走受控 business_db 路径，不属于库存动作。
    if not text or "数据库" in text:
        return []
    if not trigger_re.search(text) or any(word in text for word in _NEGATION_WORDS):
        return []
    product = _PRODUCT_RE.search(text)
    quantity = _QUANTITY_RE.search(text) or plain_qty_re.search(text)
    if product is None or quantity is None:
        return [
            _standalone_clarify_node(
                f"请告诉我要{label}的产品（型号或名称）和数量，例如：产品 A100 {label} 50 件。"
            )
        ]
    keyword = product.group(1)
    qty = float(quantity.group(1))
    if qty <= 0:
        return [_standalone_clarify_node(f"{label}数量必须是正数，请重新告诉我产品与数量。")]

    from app.db.session import get_db
    from app.infrastructure.tenant_scope import current_tenant_id

    tenant_id = current_tenant_id()
    if tenant_id is None:
        return []
    from app.db.models import Product, Warehouse

    candidates = {keyword, keyword.upper()}
    with get_db() as db:
        products = (
            db.query(Product)
            .filter(
                Product.tenant_id == tenant_id,
                or_(Product.name.in_(candidates), Product.model_number.in_(candidates)),
            )
            .order_by(Product.id)
            .limit(2)
            .all()
        )
        warehouses = (
            db.query(Warehouse)
            .filter(Warehouse.tenant_id == tenant_id, Warehouse.status == "active")
            .order_by(Warehouse.id)
            .limit(2)
            .all()
        )
        # Detach-safe: the session closes on exit, so capture ids while bound.
        product_ids = [row.id for row in products]
        warehouse_ids = [row.id for row in warehouses]
    if len(product_ids) != 1:
        return [
            _standalone_clarify_node(
                f"产品「{keyword}」{'不存在' if not product_ids else '有多个同名候选'}，"
                f"请确认准确的型号或名称后我再{label}。"
            )
        ]
    if len(warehouse_ids) != 1:
        return [
            _standalone_clarify_node(
                f"{'尚未配置可用仓库，请先创建仓库' if not warehouse_ids else f'当前有多个仓库，请确认{label}自哪一个'}"
                f"后再执行{label}。"
            )
        ]
    return [
        WorkflowNode(
            node_id=action,
            tool_id="inventory",
            action=action,
            params={
                "product_id": product_ids[0],
                "warehouse_id": warehouse_ids[0],
                "quantity": qty,
                "remark": f"AI {label}：{keyword}",
            },
            risk="high",
            idempotent=False,
            description=f"产品 {keyword} {label} {quantity.group(1)}",
        )
    ]


def inventory_stock_in_nodes(message: str) -> list[WorkflowNode]:
    return _movement_nodes(message, "stock_in")


def inventory_stock_out_nodes(message: str) -> list[WorkflowNode]:
    return _movement_nodes(message, "stock_out")
