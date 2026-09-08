"""Preserve quantity and unit while deferring missing inbound warehouse selection."""

import math
import re

from app.db.models import Product
from app.db.session import get_db
from app.infrastructure.tenant_scope import current_tenant_id

from .types import WorkflowNode


def inventory_in_node(message: str) -> WorkflowNode | None:
    match = re.fullmatch(
        r"产品\s*([^，,；;\n]+?)\s*入库\s*([0-9]+(?:\.[0-9]+)?)\s*(件|个|桶|箱|公斤|千克|吨)[。\s]*",
        message.strip(),
    )
    if match is None:
        return None
    name, raw_quantity, unit = match.groups()
    quantity = float(raw_quantity)
    if not math.isfinite(quantity) or quantity <= 0:
        return None
    tenant = current_tenant_id()
    if tenant is None:
        raise ValueError("入库产品解析需要租户身份")
    name = name.strip()
    with get_db() as db:
        products = (
            db.query(Product)
            .filter(
                Product.tenant_id == tenant, (Product.name == name) | (Product.model_number == name)
            )
            .limit(2)
            .all()
        )
        params = {"quantity": quantity, "requested_unit": unit}
        if len(products) == 1:
            params["product_id"] = products[0].id
            from app.application.product_measurement import product_measurement_unit

            params["_inventory_unit"] = product_measurement_unit(products[0]) or ""
    return WorkflowNode(
        node_id="inventory_in",
        tool_id="inventory",
        action="stock_in",
        params=params,
        risk="high",
        idempotent=False,
        description=f"产品{name}入库{raw_quantity}{unit}，需确认仓库及库存单位",
    )
