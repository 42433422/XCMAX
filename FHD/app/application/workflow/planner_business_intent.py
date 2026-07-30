"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


_UNDERSPECIFIED_REQUESTS = frozenset(
    {
        "随便问问",
        "随便看看",
        "帮我看看",
        "帮忙看看",
        "看一下",
        "看一看",
        "处理一下",
        "弄一下",
        "你来决定",
        "你看着办",
        "都可以",
    }
)

def _requires_clarification_before_execution(
    message: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """Block execution when the user has not supplied an actionable goal."""
    ctx = context or {}
    if any(
        ctx.get(key)
        for key in (
            "excel_analysis",
            "last_excel_analysis_context",
            "artifacts",
            "attachments",
            "uploaded_files",
        )
    ):
        return False

    text = re.sub(r"[\s，,。.!！?？;；:：]+", "", str(message or "")).strip().lower()
    if not text:
        return True
    if text in _UNDERSPECIFIED_REQUESTS:
        return True

    generic_tokens = ("看看", "处理", "弄一下", "随便", "你决定", "看着办")
    executable_tokens = (
        "查",
        "查询",
        "读取",
        "新增",
        "创建",
        "更新",
        "删除",
        "导入",
        "导出",
        "打印",
        "生成",
        "分析",
        "汇总",
        "报表",
        "客户",
        "产品",
        "订单",
        "库存",
        "文件",
        "表格",
        "员工",
    )
    return (
        len(text) <= 12
        and any(token in text for token in generic_tokens)
        and not any(token in text for token in executable_tokens)
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
    text = re.sub(r"^(新增|添加|创建|写入|保存|客户|单位|购买单位|产品|商品)\s*", "", text)
    text = re.sub(r"\s*(客户|单位|购买单位|产品|商品)$", "", text)
    return text.strip(" \t\r\n，,。；;：:")


def _extract_named_slot(message: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.I)
        if match:
            value = _clean_db_slot_value(match.group(1))
            if value:
                return value
    quoted = re.search(r"[「“\"']([^」”\"']+)[」”\"']", message)
    if quoted:
        return _clean_db_slot_value(quoted.group(1))
    return ""


def _looks_like_business_db_write(message: str, lower: str) -> bool:
    if not any(k in message for k in _DB_WRITE_KEYWORDS) and not any(
        k in lower for k in ("add", "create", "insert", "upsert")
    ):
        return False
    return (
        any(k in message for k in ("数据库", "入库", "写库"))
        or "db" in lower
        or "database" in lower
    )


def _infer_business_db_entity(message: str) -> str:
    if any(k in message for k in ("产品", "商品")):
        return "products"
    if any(k in message for k in ("客户", "单位", "购买单位")):
        return "customers"
    if any(k in message for k in ("原材料", "物料")):
        return "materials"
    if any(k in message for k in ("出货", "发货", "发货单")):
        return "shipment_records"
    return "products"


def _explicit_mutation_kind(message: str) -> str:
    text = str(message or "").strip()
    lower = text.lower()
    if any(token in text for token in ("查询已删除", "查看已删除", "读取已删除")):
        return ""
    if re.search(r"(?:删除|移除|删掉|删了)", text) or re.search(r"\b(?:delete|remove)\b", lower):
        return "delete"
    if re.search(r"(?:修改|更新|改为|改成)", text) or re.search(
        r"\b(?:update|modify|rename)\b", lower
    ):
        return "update"
    if any(token in text for token in _DB_WRITE_KEYWORDS) or re.search(
        r"\b(?:add|create|insert|upsert)\b", lower
    ):
        return "create"
    return ""


def _extract_explicit_product_mutation_node(message: str) -> WorkflowNode | None:
    if not any(token in message for token in ("产品", "商品")):
        return None
    id_match = re.search(
        r"(?:产品|商品)\s*(?:ID|id|编号)?\s*[:：]?\s*(\d+)",
        message,
    )
    if not id_match:
        return None
    product_id = int(id_match.group(1))
    mutation = _explicit_mutation_kind(message)
    if mutation == "delete":
        return WorkflowNode(
            node_id=f"delete_product_{product_id}",
            tool_id="products",
            action="delete",
            params={"id": product_id},
            risk="high",
            description=f"删除产品ID {product_id}",
            idempotent=False,
        )
    if mutation == "update":
        name_match = re.search(
            r"(?:名称|名字)\s*(?:修改|更新|改)?\s*(?:为|成|至)\s*([^，,。；;\n]+)",
            message,
            re.I,
        )
        if not name_match:
            return None
        name = name_match.group(1).strip()
        if not name:
            return None
        return WorkflowNode(
            node_id=f"update_product_{product_id}",
            tool_id="products",
            action="update",
            params={"id": product_id, "name": name},
            risk="medium",
            description=f"将产品ID {product_id}的名称修改为「{name}」",
            idempotent=False,
        )
    return None


def _validate_explicit_mutation_alignment(message: str, plan: PlanGraph) -> str | None:
    mutation = _explicit_mutation_kind(message)
    if not mutation:
        return None
    explicit_product_node = _extract_explicit_product_mutation_node(message)
    if explicit_product_node is not None:
        for node in plan.nodes or []:
            if (
                str(node.tool_id or "").strip() == explicit_product_node.tool_id
                and str(node.action or "").strip().lower() == explicit_product_node.action
            ):
                return None
        return (
            f"明确的产品 {mutation} 必须使用 "
            f"{explicit_product_node.tool_id}.{explicit_product_node.action}"
        )
    accepted_actions = {
        "create": {"create", "batch_create", "ensure_exists", "upsert"},
        "update": {"update", "batch_update", "upsert"},
        "delete": {"delete", "batch_delete"},
    }[mutation]
    for node in plan.nodes or []:
        action = str(node.action or "").strip().lower()
        operation = str((node.params or {}).get("operation") or "").strip().lower()
        if action in accepted_actions or operation in accepted_actions:
            return None
    return f"用户明确要求 {mutation}，但计划未包含对应写操作"


def _extract_business_db_write_node(message: str) -> WorkflowNode | None:
    entity = _infer_business_db_entity(message)
    if entity == "customers":
        unit_name = _extract_named_slot(
            message,
            (
                r"(?:客户|单位|购买单位)\s*[:：是为]?\s*([^\s，,。；;]+)",
                r"(?:新增|添加|创建|写入|保存)\s*([^\s，,。；;]+)\s*(?:客户|单位)",
            ),
        )
        if not unit_name:
            return None
        return WorkflowNode(
            node_id="write_business_customer",
            tool_id="business_db",
            action="write",
            params={
                "entity": "customers",
                "operation": "upsert",
                "payload": {"unit_name": unit_name, "customer_name": unit_name},
            },
            risk="medium",
            description=f"写入客户 {unit_name}",
            idempotent=True,
        )

    if entity == "products":
        product_name = _extract_named_slot(
            message,
            (
                r"(?:产品|商品)\s*[:：是为]?\s*([^\s，,。；;]+)",
                r"(?:新增|添加|创建|写入|保存)\s*([^\s，,。；;]+)\s*(?:产品|商品)",
            ),
        )
        unit_name = _extract_named_slot(
            message,
            (
                r"(?:客户|单位|购买单位)\s*[:：是为]?\s*([^\s，,。；;]+)",
                r"(?:给|到|为)\s*([^\s，,。；;]+)\s*(?:客户|单位)?",
            ),
        )
        if not product_name or not unit_name:
            return None
        model_match = re.search(r"(?:型号|model)\s*[:：]?\s*([A-Za-z0-9._-]+)", message, re.I)
        payload: dict[str, Any] = {
            "name_or_model": product_name,
            "product_name": product_name,
            "unit_name": unit_name,
        }
        if model_match:
            payload["model_number"] = model_match.group(1).strip().upper()
        return WorkflowNode(
            node_id="write_business_product",
            tool_id="business_db",
            action="write",
            params={"entity": "products", "operation": "create", "payload": payload},
            risk="medium",
            description=f"写入产品 {product_name}",
            idempotent=False,
        )

    return None


def _extract_business_db_read_keyword(message: str, entity: str) -> str:
    quoted = re.search(r"[「“\"']([^」”\"']+)[」”\"']", message)
    if quoted:
        return _clean_db_slot_value(quoted.group(1))

    if entity == "products":
        model = re.search(
            r"(?:产品|商品)?型号\s*[:：为是的]?\s*([A-Za-z0-9._-]+)",
            message,
            re.I,
        )
        if model:
            return model.group(1).strip()
        slot = _extract_named_slot(
            message,
            (
                r"(?:产品|商品|型号|model)\s*[:：的]?\s*([A-Za-z0-9._-]+|[^\s，,。；;]+)",
                r"(?:查|查询|读取|读)\s*(?:数据库|db|database)?\s*(?:产品|商品)?\s*([A-Za-z0-9._-]+)",
            ),
        )
        if slot:
            return slot
        model = re.search(r"\b[A-Za-z0-9][A-Za-z0-9._-]{1,}\b", message)
        if model:
            return model.group(0).strip()

    if entity == "customers":
        slot = _extract_named_slot(
            message,
            (
                r"(?:客户|单位|购买单位)\s*[:：的]?\s*([^\s，,。；;]+)",
                r"(?:查|查询|读取|读)\s*(?:数据库|db|database)?\s*(?:客户|单位)?\s*([^\s，,。；;]+)",
            ),
        )
        if slot:
            return slot

    if entity == "materials":
        slot = _extract_named_slot(
            message,
            (
                r"(?:原材料|物料|材料)\s*[:：的]?\s*([^\s，,。；;]+)",
                r"(?:查|查询|读取|读)\s*(?:数据库|db|database)?\s*(?:原材料|物料|材料)?\s*([^\s，,。；;]+)",
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
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n，,。；;：:")
    return cleaned or str(message or "").strip()


sync_module_functions(
    target=globals(),
    source_module="app.application.workflow.planner",
    function_names=(
        "_requires_clarification_before_execution",
        "_clean_db_slot_value",
        "_extract_named_slot",
        "_looks_like_business_db_write",
        "_infer_business_db_entity",
        "_explicit_mutation_kind",
        "_extract_explicit_product_mutation_node",
        "_validate_explicit_mutation_alignment",
        "_extract_business_db_write_node",
        "_extract_business_db_read_keyword",
    ),
)
