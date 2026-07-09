from __future__ import annotations

import logging
import re
from typing import Any

from .types import WorkflowNode

logger = logging.getLogger(__name__)


_DB_WRITE_KEYWORDS = frozenset(
    {
        "新增",
        "添加",
        "创建",
        "写入",
        "加入数据库",
        "添加到数据库",
        "保存到数据库",
        "入库",
    }
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
