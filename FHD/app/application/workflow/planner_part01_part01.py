# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


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
    text = _facade().re.sub(
        "^(新增|添加|创建|写入|保存|修改|更新|删除|移除|客户|单位|购买单位|产品|商品|原材料|物料|发货单)\\s*",
        "",
        text,
    )
    text = _facade().re.sub("\\s*(客户|单位|购买单位|产品|商品|原材料|物料|发货单)$", "", text)
    return text.strip(" \t\r\n，,。；;：:")


def _extract_named_slot(message: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = _facade().re.search(pattern, message, flags=_facade().re.I)
        if match:
            value = _facade()._clean_db_slot_value(match.group(1))
            if value:
                return value
    quoted = _facade().re.search("[「“\\\"']([^」”\\\"']+)[」”\\\"']", message)
    if quoted:
        return _facade()._clean_db_slot_value(quoted.group(1))
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
    match = _facade().re.search(
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


def _extract_marked_value(message: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(_facade().re.escape(label) for label in labels)
    match = _facade().re.search(
        f"""(?:{label_pattern})\\s*[:：是为]?\\s*[「“\\"']?([^，,。；;\\n]+?)[」”\\"']?(?=\\s+(?:联系人|电话|地址|型号|规格|单价|价格|数量|库存|单位|状态|客户|产品|原材料|物料|发货单|ID|id)\\s*[:：是为]?|[，,。；;]|$)""",
        message,
        flags=_facade().re.I,
    )
    return _facade()._clean_db_slot_value(match.group(1)) if match else ""


def _extract_number(message: str, labels: tuple[str, ...]) -> float | None:
    label_pattern = "|".join(_facade().re.escape(label) for label in labels)
    match = _facade().re.search(
        f"(?:{label_pattern})\\s*[:：是为]?\\s*(-?\\d+(?:\\.\\d+)?)", message, _facade().re.I
    )
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _selector_for_business_db_message(entity: str, message: str) -> dict[str, _facade().Any]:
    numeric_id = _facade()._extract_business_db_id(message)
    if numeric_id:
        return {"id": numeric_id}
    if entity == "customers":
        name = _facade()._extract_marked_value(message, ("客户", "购买单位"))
        return {"customer_name": name} if name else {}
    if entity == "products":
        model = _facade()._extract_marked_value(message, ("型号", "model"))
        if model:
            return {"model_number": model.upper()}
        name = _facade()._extract_marked_value(message, ("产品", "商品"))
        return {"product_name": name} if name else {}
    if entity == "materials":
        code = _facade()._extract_marked_value(message, ("物料编码", "原材料编码", "material_code"))
        if code:
            return {"material_code": code}
        name = _facade()._extract_marked_value(message, ("原材料", "物料"))
        return {"material_name": name} if name else {}
    return {}


def _changes_for_business_db_message(entity: str, message: str) -> dict[str, _facade().Any]:
    changes: dict[str, _facade().Any] = {}
    if entity == "customers":
        person = _facade()._extract_marked_value(message, ("联系人",))
        phone = _facade()._extract_marked_value(message, ("联系电话", "电话"))
        address = _facade()._extract_marked_value(message, ("联系地址", "地址"))
        if person:
            changes["contact_person"] = person
        if phone:
            changes["contact_phone"] = phone
        if address:
            changes["contact_address"] = address
    elif entity == "products":
        spec = _facade()._extract_marked_value(message, ("规格",))
        price = _facade()._extract_number(message, ("单价", "价格"))
        quantity = _facade()._extract_number(message, ("数量", "库存"))
        unit = _facade()._extract_marked_value(message, ("计量单位",))
        if spec:
            changes["specification"] = spec
        if price is not None:
            changes["price"] = price
        if quantity is not None:
            changes["quantity"] = int(quantity)
        if unit:
            changes["unit"] = unit
    elif entity == "materials":
        price = _facade()._extract_number(message, ("单价", "价格"))
        quantity = _facade()._extract_number(message, ("数量", "库存"))
        spec = _facade()._extract_marked_value(message, ("规格",))
        if price is not None:
            changes["unit_price"] = price
        if quantity is not None:
            changes["quantity"] = quantity
        if spec:
            changes["specification"] = spec
    elif entity == "shipment_records":
        tins = _facade()._extract_number(message, ("桶数", "数量"))
        status = _facade()._extract_marked_value(message, ("状态",))
        price = _facade()._extract_number(message, ("单价", "价格"))
        if tins is not None:
            changes["quantity_tins"] = int(tins)
        if status:
            changes["status"] = status
        if price is not None:
            changes["unit_price"] = price
    return changes


def _extract_business_db_write_node(message: str) -> _facade().WorkflowNode | None:
    entity = _facade()._infer_business_db_entity(message)
    operation = _facade()._infer_business_db_operation(message)
    if operation in {"update", "delete"}:
        selector = _facade()._selector_for_business_db_message(entity, message)
        if not selector:
            return None
        payload: dict[str, _facade().Any] = {"selector": selector}
        if operation == "update":
            changes = _facade()._changes_for_business_db_message(entity, message)
            if not changes:
                return None
            payload["changes"] = changes
        return _facade().WorkflowNode(
            node_id=f"{operation}_business_{entity.rstrip('s')}",
            tool_id="business_db",
            action="write",
            params={
                "entity": entity,
                "operation": operation,
                "payload": _facade()._attach_explicit_tenant_id(payload, message),
            },
            risk="high" if operation == "delete" else "medium",
            description=f"{operation} {entity}",
            idempotent=False,
        )
    if entity == "customers":
        unit_name = _facade()._extract_marked_value(
            message, ("客户名称", "客户名", "购买单位名称", "单位名称", "名称")
        )
        if not unit_name:
            unit_name = _facade()._extract_named_slot(
                message,
                (
                    "(?:客户(?!名称|名)|单位(?!名称)|购买单位(?!名称))\\s*[:：是为]?\\s*([^\\s，,。；;]+)",
                    "(?:新增|添加|创建|写入|保存)\\s*([^\\s，,。；;]+)\\s*(?:客户|单位)",
                ),
            )
        if not unit_name:
            return None
        payload = {"unit_name": unit_name, "customer_name": unit_name}
        payload.update(_facade()._changes_for_business_db_message(entity, message))
        return _facade().WorkflowNode(
            node_id="write_business_customer",
            tool_id="business_db",
            action="write",
            params={
                "entity": "customers",
                "operation": "upsert",
                "payload": _facade()._attach_explicit_tenant_id(payload, message),
            },
            risk="medium",
            description=f"写入客户 {unit_name}",
            idempotent=True,
        )
    if entity == "products":
        product_name = _facade()._extract_marked_value(
            message, ("产品名称", "商品名称", "产品名", "商品名", "名称")
        )
        if not product_name:
            product_name = _facade()._extract_named_slot(
                message,
                (
                    "(?:产品(?!名称|名)|商品(?!名称|名))\\s*[:：是为]?\\s*([^\\s，,。；;]+)",
                    "(?:新增|添加|创建|写入|保存)\\s*([^\\s，,。；;]+)\\s*(?:产品|商品)",
                ),
            )
        if not product_name:
            return None
        model_match = _facade().re.search(
            "(?:型号|model)\\s*[:：]?\\s*([A-Za-z0-9._-]+)", message, _facade().re.I
        )
        product_payload: dict[str, _facade().Any] = {
            "name_or_model": product_name,
            "product_name": product_name,
        }
        unit = _facade()._extract_marked_value(message, ("计量单位",))
        price = _facade()._extract_number(message, ("单价", "价格"))
        specification = _facade()._extract_marked_value(message, ("规格",))
        if unit:
            product_payload["unit"] = unit
        if price is not None:
            product_payload["price"] = price
        if specification:
            product_payload["specification"] = specification
        if model_match:
            product_payload["model_number"] = model_match.group(1).strip().upper()
        return _facade().WorkflowNode(
            node_id="write_business_product",
            tool_id="business_db",
            action="write",
            params={
                "entity": "products",
                "operation": "create",
                "payload": _facade()._attach_explicit_tenant_id(product_payload, message),
            },
            risk="medium",
            description=f"写入产品 {product_name}",
            idempotent=False,
        )
    if entity == "materials":
        name = _facade()._extract_marked_value(
            message, ("原材料名称", "物料名称", "原材料名", "物料名", "名称")
        )
        if not name:
            name = _facade()._extract_marked_value(message, ("原材料", "物料"))
        if not name:
            return None
        payload = {"name": name}
        code = _facade()._extract_marked_value(message, ("物料编码", "原材料编码", "material_code"))
        unit = _facade()._extract_marked_value(message, ("计量单位",))
        quantity = _facade()._extract_number(message, ("数量", "库存"))
        price = _facade()._extract_number(message, ("单价", "价格"))
        if code:
            payload["material_code"] = code
        if unit:
            payload["unit"] = unit
        if quantity is not None:
            payload["quantity"] = quantity
        if price is not None:
            payload["unit_price"] = price
        return _facade().WorkflowNode(
            node_id="write_business_material",
            tool_id="business_db",
            action="write",
            params={
                "entity": "materials",
                "operation": "create",
                "payload": _facade()._attach_explicit_tenant_id(payload, message),
            },
            risk="medium",
            description=f"写入原材料 {name}",
            idempotent=False,
        )
    if entity == "shipment_records":
        unit_name = _facade()._extract_marked_value(message, ("客户", "购买单位"))
        product_name = _facade()._extract_marked_value(message, ("产品", "商品"))
        tins = _facade()._extract_number(message, ("桶数", "数量"))
        if not unit_name or not product_name or tins is None:
            return None
        item: dict[str, _facade().Any] = {
            "product_name": product_name,
            "name": product_name,
            "quantity_tins": int(tins),
        }
        model = _facade()._extract_marked_value(message, ("型号", "model"))
        spec = _facade()._extract_number(message, ("桶规格", "规格"))
        price = _facade()._extract_number(message, ("单价", "价格"))
        if model:
            item["model_number"] = model.upper()
        if spec is not None:
            item["tin_spec"] = spec
        if price is not None:
            item["unit_price"] = price
        return _facade().WorkflowNode(
            node_id="write_business_shipment_record",
            tool_id="business_db",
            action="write",
            params={
                "entity": "shipment_records",
                "operation": "create",
                "payload": _facade()._attach_explicit_tenant_id(
                    {"unit_name": unit_name, "products": [item]}, message
                ),
            },
            risk="medium",
            description=f"为 {unit_name} 创建 {product_name} 出货记录",
            idempotent=False,
        )
    return None
