"""Preserve named quotation inputs and leave absent commercial terms unanswered."""

from typing import Any

from app.application.workflow.types import WorkflowNode
from app.domain.services.conversation.chat_tool_intent import is_negated_action_request

_MAX_PLANNER_TEXT_CHARS = 4096
_FIELD_LABELS = {
    "客户名称": "customer_name",
    "客户": "customer_name",
    "购买单位": "customer_name",
    "产品名称": "product_name",
    "产品": "product_name",
    "商品名称": "product_name",
    "商品": "product_name",
    "型号": "model_number",
    "数量": "quantity",
    "单价": "unit_price",
    "总金额": "total_amount",
}
_SEPARATORS = "：:，,；;\n"
_FIELD_SEPARATORS = "，,；;\n。！!"


def _strip_polite(text: str) -> str:
    text = text.strip()
    for prefix in ("请", "帮我"):
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text


def _number(text: str, *, max_fraction: int | None = None) -> float | None:
    value = text.strip()
    if value.endswith(("件", "个", "元")):
        value = value[:-1]
    if not value:
        return None
    whole, dot, fraction = value.partition(".")
    if not whole or not all("0" <= char <= "9" for char in whole):
        return None
    if dot and (not fraction or not all("0" <= char <= "9" for char in fraction)):
        return None
    if max_fraction is not None and len(fraction) > max_fraction:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _labeled_order(message: str) -> tuple[bool, dict[str, Any]]:
    text = _strip_polite(message)
    verb = next((item for item in ("创建", "新建", "新增") if text.startswith(item)), None)
    if not verb:
        return False, {}
    text = text[len(verb) :].lstrip()
    if text.startswith(("一张", "一个")):
        text = text[2:].lstrip()
    title = "销售订单"
    if not text.startswith(title):
        return False, {}
    remainder = text[len(title) :]
    if remainder and remainder[0] not in _SEPARATORS:
        return False, {}
    remainder = remainder.lstrip(_SEPARATORS).lstrip()
    fields: dict[str, Any] = {}
    # Split only on the grammar's explicit field separators; every pass consumes
    # input, so adversarial text remains linear in the 4096-character bound.
    pieces = []
    current = []
    for char in remainder:
        if char in _FIELD_SEPARATORS:
            if current:
                pieces.append("".join(current).strip())
                current = []
        else:
            current.append(char)
    if current:
        pieces.append("".join(current).strip())
    for piece in pieces:
        if piece.startswith("请先展示销售订单执行计划") or piece.startswith(
            "先展示销售订单执行计划"
        ):
            continue
        if piece.startswith("提交人工审批后再执行"):
            continue
        label = next(
            (
                name
                for name in sorted(_FIELD_LABELS, key=len, reverse=True)
                if piece.startswith(name)
            ),
            None,
        )
        if not label:
            continue
        value = piece[len(label) :].lstrip(" :：").strip().strip("「」“”\"'")
        key = _FIELD_LABELS[label]
        if not value:
            continue
        if key in ("quantity", "unit_price", "total_amount"):
            number = _number(value)
            if number is not None and key != "total_amount":
                fields[key] = number
        else:
            fields[key] = value
    return True, fields


def _direct_request(
    message: str, *, order: bool
) -> tuple[str, str, str, str | None, str | None] | None:
    text = _strip_polite(message)
    if order:
        if not text.startswith("给客户"):
            return None
        text = text[len("给客户") :]
        split = "下订单"
        action = "create_order"
    else:
        if not text.startswith("给"):
            return None
        text = text[len("给") :]
        split = "的产品"
        action = "quote"
    customer, marker, rest = text.partition(split)
    if not marker or not customer.strip():
        return None
    if order:
        if not rest.startswith(("，", ",")):
            return None
        rest = rest[1:].lstrip()
        if not rest.startswith("产品"):
            return None
        rest = rest[len("产品") :].lstrip()
    else:
        rest = rest.lstrip()
    delimiter = "报" if not order else None
    index = (
        rest.find(delimiter)
        if delimiter
        else min(
            (position for position in (rest.find("，"), rest.find(",")) if position >= 0),
            default=-1,
        )
    )
    if index <= 0:
        return None
    model = rest[:index].strip()
    if (
        not model
        or not (model[0].isascii() and model[0].isalnum())
        or not all(c.isascii() and (c.isalnum() or c in "._-") for c in model)
    ):
        return None
    tail = rest[index:]
    if not order:
        if not tail.startswith(("报价", "报个价")):
            return None
        tail = tail[3:] if tail.startswith("报个价") else tail[2:]
    else:
        tail = tail[1:]
    quantity = price = None
    tail = (
        tail.strip()
        .removesuffix("。")
        .removesuffix("！")
        .removesuffix("!")
        .strip()
        .lstrip("，,")
        .strip()
    )
    if tail:
        for part in tail.replace("，", ",").split(","):
            part = part.strip()
            if part.startswith("数量"):
                quantity = _number(part[len("数量") :])
                if quantity is None:
                    return None
            elif part.startswith("单价"):
                price = _number(part[len("单价") :])
                if price is None:
                    return None
            else:
                return None
    return action, customer.strip(), model, quantity, price


def sales_quote_node(
    message: str, registry: dict[str, Any], *, single_request: bool = False
) -> WorkflowNode | None:
    if len(message) > _MAX_PLANNER_TEXT_CHARS:
        return None
    if "sales" not in registry or is_negated_action_request(message):
        return None
    order_offset = min(
        (message.find(prefix) for prefix in ("创建", "新建", "新增") if message.find(prefix) >= 0),
        default=-1,
    )
    if order_offset >= 0:
        order_text = message[order_offset:]
        recognized, fields = _labeled_order(order_text)
        if not recognized:
            return None
        if single_request:
            if message[:order_offset].strip() or any(
                token in order_text for token in ("然后", "同时", "再导出", "再删除")
            ):
                return None
            if "。" in order_text and not any(
                token in order_text
                for token in ("请先展示销售订单执行计划", "提交人工审批后再执行")
            ):
                return None
        item = {
            key: fields[key]
            for key in ("model_number", "product_name", "quantity", "unit_price")
            if key in fields
        }
        return WorkflowNode(
            node_id="sales_create_order",
            tool_id="sales",
            action="create_order",
            params={
                "customer_name": fields.get("customer_name", ""),
                "items": [item] if item else [],
            },
            risk="medium",
            idempotent=False,
            description="创建并确认销售订单",
        )
    request = _direct_request(message, order=False) or _direct_request(message, order=True)
    if request is None:
        return None
    action, customer, model, quantity, price = request
    item: dict[str, Any] = {"model_number": model}
    if quantity is not None:
        item["quantity"] = quantity
    if price is not None:
        item["unit_price"] = price
    return WorkflowNode(
        node_id=f"sales_{action}",
        tool_id="sales",
        action=action,
        params={"customer_name": customer, "items": [item]},
        risk="medium",
        idempotent=False,
        description=f"为{customer}创建{model}报价单"
        if action == "quote"
        else f"为{customer}创建并确认{model}销售订单",
    )
