"""MCP resources exposing the AIOPEN system map (read-only)."""

from __future__ import annotations

import json
from typing import Any

from app.infrastructure.aiopen.principal_context import current_execution_context

from .catalog_builder import entity_schema, find_operation, get_catalog

CATALOG_URI = "xcmax://catalog/operations"
OPERATION_TEMPLATE = "xcmax://catalog/operation/{operation_id}"
SCHEMA_TEMPLATE = "xcmax://catalog/schema/{entity}"

_JSON = "application/json"


def list_resources(app: Any) -> list[dict[str, Any]]:
    catalog = get_catalog(app, current_execution_context())
    return [
        {
            "uri": CATALOG_URI,
            "name": "operation_catalog",
            "title": "AIOPEN 能力目录",
            "description": f"运行时生成的全部可开放 operation（{catalog.get('count', 0)} 条）。",
            "mimeType": _JSON,
        }
    ]


def list_resource_templates() -> list[dict[str, Any]]:
    return [
        {
            "uriTemplate": OPERATION_TEMPLATE,
            "name": "operation_card",
            "title": "Operation 语义卡片",
            "description": "单个 operation 的方法、路径、风险、scope 与语义 overlay。",
            "mimeType": _JSON,
        },
        {
            "uriTemplate": SCHEMA_TEMPLATE,
            "name": "entity_schema",
            "title": "实体字段字典",
            "description": "从应用 OpenAPI components.schemas 读取的实体字段定义。",
            "mimeType": _JSON,
        },
    ]


def _contents(uri: str, payload: Any) -> dict[str, Any]:
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": _JSON,
                "text": json.dumps(payload, ensure_ascii=False, default=str),
            }
        ]
    }


def read_resource(app: Any, uri: str) -> dict[str, Any]:
    """读取资源；未知或缺失时抛 ``ValueError``（由协议层转 JSON-RPC 错误）。"""
    target = str(uri or "").strip()
    if target == CATALOG_URI:
        catalog = get_catalog(app, current_execution_context())
        return _contents(
            target,
            {
                "count": catalog.get("count", 0),
                "excluded_prefixes": catalog.get("excluded_prefixes", []),
                "operations": catalog.get("operations", []),
            },
        )
    prefix = "xcmax://catalog/"
    if not target.startswith(prefix):
        raise ValueError(f"未知资源：{target}")
    kind, _, value = target[len(prefix) :].partition("/")
    if not value:
        raise ValueError(f"资源缺少标识：{target}")
    if kind == "operation":
        entry = find_operation(get_catalog(app, current_execution_context()), value)
        if entry is None:
            raise ValueError(f"目录中不存在 operation：{value}")
        return _contents(target, entry)
    if kind == "schema":
        payload = entity_schema(app, value)
        if payload is None:
            raise ValueError(f"OpenAPI 中不存在实体：{value}")
        return _contents(target, payload)
    raise ValueError(f"未知资源类型：{kind}")
