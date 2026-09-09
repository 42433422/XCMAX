"""Extract explicit, labelled product creation without inventing customers."""

from __future__ import annotations

import re

from .types import WorkflowNode


def direct_product_create_node(message: str) -> WorkflowNode | None:
    text = str(message or "").strip()
    if not re.match(r"^(?:请帮我|帮我|请)?\s*(?:新增|添加)\s*(?:一个)?产品", text):
        return None
    if any(word in text for word in ("客户", "购买单位", "然后", "并且", "删除", "修改")):
        return None
    model = re.search(r"型号\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9._-]*)", text)
    if model is None:
        return None
    params: dict[str, object] = {
        "name_or_model": model.group(1).upper(),
        "model_number": model.group(1).upper(),
    }
    price = re.search(r"(?:单价|价格)\s*[:：]?\s*(-?\d+(?:\.\d+)?)", text)
    if price:
        params["price"] = float(price.group(1))
    unit = re.search(r"计量单位\s*[:：]?\s*([^\s，,。；;]+)", text)
    if unit:
        params["unit"] = unit.group(1)
    # Do not silently discard additional fields or follow-up actions.
    remainder = text
    spans = [match.span() for match in (model, price, unit) if match is not None]
    for start, end in sorted(spans, reverse=True):
        remainder = remainder[:start] + remainder[end:]
    remainder = re.sub(r"^(?:请帮我|帮我|请)?\s*(?:新增|添加)\s*(?:一个)?产品", "", remainder)
    if remainder.strip(" \t\n，,。；;：:"):
        return None
    return WorkflowNode(
        node_id="create_product",
        tool_id="products",
        action="create",
        params=params,
        risk="medium",
        idempotent=False,
        description="创建产品",
    )
