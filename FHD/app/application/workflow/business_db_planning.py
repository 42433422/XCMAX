"""Parse bounded business-database requests into structured workflow nodes."""

from __future__ import annotations

import re
from typing import Any

from app.application.workflow.types import WorkflowNode
from app.domain.conversation.services.chat_tool_intent import (
    attach_explicit_tenant_id as _attach_explicit_tenant_id,
)
from app.domain.conversation.services.chat_tool_intent import (
    looks_like_raw_sql as _looks_like_raw_sql,
)


def _clean_db_slot_value(value: str) -> str:
    text = str(value or "").strip(" \t\r\n，,。；;：:")
    for token in (
        "到数据库",
        "写入数据库",
        "加入数据库",
        "添加到数据库",
        "保存到数据库",
        "入库",
        "数据库",
    ):
        text = text.replace(token, "")
    if text in {"原材料", "物料"}:
        return text
    text = re.sub(
        "^(新增|添加|创建|写入|保存|修改|更新|删除|移除|客户|单位|购买单位|产品|商品|原材料|物料|发货单)\\s*",
        "",
        text,
    )
    text = re.sub("\\s*(客户|单位|购买单位|产品|商品|原材料|物料|发货单)$", "", text)
    return text.strip(" \t\r\n，,。；;：:")


def _extract_named_slot(message: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.I)
        if match:
            value = match.group(1)
            if (value[:1], value[-1:]) in (("「", "」"), ("“", "”"), ('"', '"'), ("'", "'")):
                return value[1:-1].strip()
            value = _clean_db_slot_value(value)
            if value:
                return value
    quoted = re.search("[「“\\\"']([^」”\\\"']+)[」”\\\"']", message)
    if quoted:
        return quoted.group(1).strip()
    return ""


def _infer_business_db_entity(message: str) -> str:
    if any(k in message for k in ("出货", "发货", "发货单")):
        return "shipment_records"
    if any(k in message for k in ("原材料", "物料")):
        return "materials"
    if any(k in message for k in ("产品", "商品")):
        return "products"
    if any(k in message for k in ("客户", "单位", "购买单位")):
        return "customers"
    return "products"


def _infer_business_db_operation(message: str) -> str:
    lower = str(message or "").lower()
    if any(k in message for k in ("删除", "移除")) or any(k in lower for k in ("delete", "remove")):
        return "delete"
    if any(k in message for k in ("修改", "更新", "改为", "改成")) or "update" in lower:
        return "update"
    return "create"


def _extract_business_db_id(message: str) -> int | None:
    match = re.search(
        "(?:记录|客户|产品|原材料|物料|发货单|订单)?\\s*(?:id|ID|编号)\\s*[:：#]?\\s*(\\d+)",
        message,
    )
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _extract_marked_value(message: str, labels: tuple[str, ...], *, clean: bool = True) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    negation = r"(?:(?:不要|无需|不用|不|别)\s*(?:填(?:写)?|提供|设置|录入|留(?:下)?|修改|更改)|不要|无需|不用)"
    message = re.sub(
        rf"{negation}\s*(?:{label_pattern})|(?:{label_pattern})\s*{negation}",
        "",
        message,
        flags=re.I,
    )
    quoted = re.search(
        rf"""(?:{label_pattern})\s*[:：是为]?\s*(?:「([^」]*)」|“([^”]*)”|"([^"]*)"|'([^']*)')""",
        message,
        flags=re.I,
    )
    if quoted:
        return next(value for value in quoted.groups() if value is not None).strip()
    match = re.search(
        f"""(?:{label_pattern})\\s*[:：是为]?\\s*[「“\\"']?([^，,。；;\\n]+?)[」”\\"']?(?=\\s+(?:联系人|电话|地址|型号|规格|单价|价格|数量|库存|单位|状态|客户|产品|原材料|物料|发货单|ID|id)\\s*[:：是为]?|[，,。；;]|$)""",
        message,
        flags=re.I,
    )
    value = match.group(1) if match else ""
    return _clean_db_slot_value(value) if clean else value.strip(" \t\r\n「」“”\"'")


def _extract_number(message: str, labels: tuple[str, ...]) -> float | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(f"(?:{label_pattern})\\s*[:：是为]?\\s*(-?\\d+(?:\\.\\d+)?)", message, re.I)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_shipment_tins(message: str) -> float | None:
    tins = _extract_number(message, ("桶数",))
    if tins is not None:
        return tins
    match = re.search(
        r"数量\s*[:：是为]?\s*(-?\d+(?:\.\d+)?)\s*(公斤|千克|kg|斤|吨|g)?",
        message,
        re.I,
    )
    if match and not match.group(2):
        return float(match.group(1))
    return None


def _selector_for_business_db_message(entity: str, message: str) -> dict[str, Any]:
    numeric_id = _extract_business_db_id(message)
    if numeric_id:
        return {"id": numeric_id}
    if entity == "customers":
        name = _extract_marked_value(message, ("客户", "购买单位"))
        return {"customer_name": name} if name else {}
    if entity == "products":
        model = _extract_marked_value(message, ("型号", "model"))
        if model:
            return {"model_number": model.upper()}
        name = _extract_marked_value(message, ("产品", "商品"))
        return {"product_name": name} if name else {}
    if entity == "materials":
        code = _extract_marked_value(message, ("物料编码", "原材料编码", "material_code"))
        if code:
            return {"material_code": code}
        name = _extract_marked_value(message, ("原材料", "物料"))
        return {"material_name": name} if name else {}
    return {}


def _changes_for_business_db_message(entity: str, message: str) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if entity == "customers":
        person = _extract_marked_value(message, ("联系人",))
        phone = _extract_marked_value(message, ("联系电话", "电话"))
        address = _extract_marked_value(message, ("联系地址", "地址"))
        if person:
            changes["contact_person"] = person
        if phone:
            changes["contact_phone"] = phone
        if address:
            changes["contact_address"] = address
    elif entity == "products":
        spec = _extract_marked_value(message, ("规格",))
        price = _extract_number(message, ("单价", "价格"))
        quantity = _extract_number(message, ("数量", "库存"))
        unit = _extract_marked_value(message, ("计量单位",))
        if spec:
            changes["specification"] = spec
        if price is not None:
            changes["price"] = price
        if quantity is not None:
            changes["quantity"] = int(quantity)
        if unit:
            changes["unit"] = unit
    elif entity == "materials":
        price = _extract_number(message, ("单价", "价格"))
        quantity = _extract_number(message, ("数量", "库存"))
        spec = _extract_marked_value(message, ("规格",))
        if price is not None:
            changes["unit_price"] = price
        if quantity is not None:
            changes["quantity"] = quantity
        if spec:
            changes["specification"] = spec
    elif entity == "shipment_records":
        tins = _extract_shipment_tins(message)
        status = _extract_marked_value(message, ("状态",))
        price = _extract_number(message, ("单价", "价格"))
        if tins is not None:
            changes["quantity_tins"] = int(tins)
        if status:
            changes["status"] = status
        if price is not None:
            changes["unit_price"] = price
    return changes


def _extract_business_db_write_node(message: str) -> WorkflowNode | None:
    # 双保险：原始 SQL 形态绝不产出写节点（主闸在 plan()/looks_like_business_db_write）。
    if _looks_like_raw_sql(message):
        return None
    entity = _infer_business_db_entity(message)
    operation = _infer_business_db_operation(message)
    if operation in {"update", "delete"}:
        selector = _selector_for_business_db_message(entity, message)
        if not selector:
            return None
        payload: dict[str, Any] = {"selector": selector}
        if operation == "update":
            changes = _changes_for_business_db_message(entity, message)
            if not changes:
                return None
            payload["changes"] = changes
        return WorkflowNode(
            node_id=f"{operation}_business_{entity.rstrip('s')}",
            tool_id="business_db",
            action="write",
            params={
                "entity": entity,
                "operation": operation,
                "payload": _attach_explicit_tenant_id(payload, message),
            },
            risk="high" if operation == "delete" else "medium",
            description=f"{operation} {entity}",
            idempotent=False,
        )
    if entity == "customers":
        unit_name = _extract_marked_value(
            message, ("客户名称", "客户名", "购买单位名称", "单位名称", "名称")
        )
        if not unit_name:
            unit_name = _extract_named_slot(
                message,
                (
                    "(?:客户(?!名称|名)|单位(?!名称)|购买单位(?!名称))\\s*[:：是为]?\\s*([^\\s，,。；;]+)",
                    "(?:新增|添加|创建|写入|保存)\\s*([^\\s，,。；;]+)\\s*(?:客户|单位)",
                ),
            )
        if not unit_name:
            return None
        payload = {"unit_name": unit_name, "customer_name": unit_name}
        payload.update(_changes_for_business_db_message(entity, message))
        return WorkflowNode(
            node_id="write_business_customer",
            tool_id="business_db",
            action="write",
            params={
                "entity": "customers",
                "operation": "upsert",
                "payload": _attach_explicit_tenant_id(payload, message),
            },
            risk="medium",
            description=f"写入客户 {unit_name}",
            idempotent=True,
        )
    if entity == "products":
        product_name = _extract_marked_value(
            message, ("产品名称", "商品名称", "产品名", "商品名", "名称")
        )
        if not product_name:
            product_name = _extract_named_slot(
                message,
                (
                    "(?:产品(?!名称|名)|商品(?!名称|名))\\s*[:：是为]?\\s*([^\\s，,。；;]+)",
                    "(?:新增|添加|创建|写入|保存)\\s*([^\\s，,。；;]+)\\s*(?:产品|商品)",
                ),
            )
        if not product_name:
            return None
        model_match = re.search("(?:型号|model)\\s*[:：]?\\s*([A-Za-z0-9._-]+)", message, re.I)
        product_payload: dict[str, Any] = {
            "name_or_model": product_name,
            "product_name": product_name,
        }
        unit = _extract_marked_value(message, ("计量单位",))
        price = _extract_number(message, ("单价", "价格"))
        specification = _extract_marked_value(message, ("规格",))
        if unit:
            product_payload["unit"] = unit
        if price is not None:
            product_payload["price"] = price
        if specification:
            product_payload["specification"] = specification
        if model_match:
            product_payload["model_number"] = model_match.group(1).strip().upper()
        return WorkflowNode(
            node_id="write_business_product",
            tool_id="business_db",
            action="write",
            params={
                "entity": "products",
                "operation": "create",
                "payload": _attach_explicit_tenant_id(product_payload, message),
            },
            risk="medium",
            description=f"写入产品 {product_name}",
            idempotent=False,
        )
    if entity == "materials":
        name = _extract_marked_value(
            message, ("原材料名称", "物料名称", "原材料名", "物料名", "名称")
        )
        if not name:
            name = _extract_marked_value(message, ("原材料", "物料"))
        if not name:
            return None
        payload = {"name": name}
        code = _extract_marked_value(message, ("物料编码", "原材料编码", "material_code"))
        unit = _extract_marked_value(message, ("计量单位",))
        quantity = _extract_number(message, ("数量", "库存"))
        price = _extract_number(message, ("单价", "价格"))
        if code:
            payload["material_code"] = code
        if unit:
            payload["unit"] = unit
        if quantity is not None:
            payload["quantity"] = quantity
        if price is not None:
            payload["unit_price"] = price
        return WorkflowNode(
            node_id="write_business_material",
            tool_id="business_db",
            action="write",
            params={
                "entity": "materials",
                "operation": "create",
                "payload": _attach_explicit_tenant_id(payload, message),
            },
            risk="medium",
            description=f"写入原材料 {name}",
            idempotent=False,
        )
    if entity == "shipment_records":
        unit_name = _extract_marked_value(
            message, ("客户名称", "单位名称", "购买单位", "客户", "单位"), clean=False
        )
        product_name = _extract_marked_value(
            message, ("产品名称", "商品名称", "产品名", "商品名"), clean=False
        ) or _extract_marked_value(message, ("产品", "商品"), clean=False)
        tins = _extract_shipment_tins(message)
        if not unit_name or not product_name or tins is None:
            return None
        item: dict[str, Any] = {
            "product_name": product_name,
            "name": product_name,
            "quantity_tins": int(tins),
        }
        model = _extract_marked_value(message, ("型号", "model"))
        spec = _extract_number(message, ("桶规格", "规格"))
        price = _extract_number(message, ("单价", "价格"))
        if model:
            item["model_number"] = model.upper()
        if spec is not None:
            item["tin_spec"] = spec
        if price is not None:
            item["unit_price"] = price
        return WorkflowNode(
            node_id="write_business_shipment_record",
            tool_id="business_db",
            action="write",
            params={
                "entity": "shipment_records",
                "operation": "create",
                "payload": _attach_explicit_tenant_id(
                    {"unit_name": unit_name, "products": [item]}, message
                ),
            },
            risk="medium",
            description=f"为 {unit_name} 创建 {product_name} 出货记录",
            idempotent=False,
        )
    return None


def _extract_business_db_read_keyword(message: str, entity: str) -> str:
    quoted = re.search("[「“\\\"']([^」”\\\"']+)[」”\\\"']", message)
    if quoted:
        return _clean_db_slot_value(quoted.group(1))
    if entity == "products":
        slot = _extract_named_slot(
            message,
            (
                "(?:产品|商品|型号|model)\\s*[:：的]?\\s*([A-Za-z0-9._-]+|[^\\s，,。；;]+)",
                "(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:产品|商品)?\\s*([A-Za-z0-9._-]+)",
            ),
        )
        if slot:
            return slot
        model = re.search("\\b[A-Za-z0-9][A-Za-z0-9._-]{1,}\\b", message)
        if model:
            return model.group(0).strip()
    if entity == "customers":
        slot = _extract_named_slot(
            message,
            (
                "(?:客户|单位|购买单位)\\s*[:：的]?\\s*([^\\s，,。；;]+)",
                "(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:客户|单位)?\\s*([^\\s，,。；;]+)",
            ),
        )
        if slot:
            return slot
    if entity == "materials":
        slot = _extract_named_slot(
            message,
            (
                "(?:原材料|物料|材料)\\s*[:：的]?\\s*([^\\s，,。；;]+)",
                "(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:原材料|物料|材料)?\\s*([^\\s，,。；;]+)",
            ),
        )
        if slot:
            return slot
    cleaned = str(message or "").strip()
    for token in (
        "查询数据库",
        "读取数据库",
        "查数据库",
        "读数据库",
        "数据库",
        "database",
        "查库",
        "读库",
        "查询",
        "读取",
        "查",
        "读",
        "产品",
        "商品",
        "客户",
        "单位",
        "购买单位",
        "原材料",
        "物料",
        "材料",
    ):
        cleaned = cleaned.replace(token, " ")
    cleaned = re.sub("\\s+", " ", cleaned).strip(" \t\r\n，,。；;：:")
    return cleaned or str(message or "").strip()
