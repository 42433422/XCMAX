"""Business database tool contracts and workflow dispatch."""

from __future__ import annotations

from typing import Any


def business_db_tool_specs() -> list[dict[str, Any]]:
    """Return the chat-facing business database tool contracts."""
    entities = ["customers", "products", "materials", "shipment_records"]
    return [
        {
            "type": "function",
            "function": {
                "name": "business_db_read",
                "description": "查询业务数据（客户/购买单位、产品、原材料、出货记录）。entity 指定对象类型，可用 keyword 按名称/型号/单号过滤。只读操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "enum": entities,
                            "description": "要查询的业务对象：customers客户、products产品、materials原材料、shipment_records出货记录",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "可选：按名称/型号/单号等关键字过滤",
                        },
                        "query": {
                            "type": "string",
                            "description": "可选：查询条件描述（同 keyword）",
                        },
                    },
                    "required": ["entity"],
                },
            },
            "risk_level": "low",
        },
        {
            "type": "function",
            "function": {
                "name": "business_db_write",
                "description": "新建/更新/删除业务数据（客户、产品、原材料、出货记录）。entity 指定对象，operation 指定操作，payload 为具体字段。写操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "enum": entities,
                            "description": "业务对象：customers客户、products产品、materials原材料、shipment_records出货记录",
                        },
                        "operation": {
                            "type": "string",
                            "enum": [
                                "create",
                                "ensure_exists",
                                "upsert",
                                "update",
                                "delete",
                            ],
                            "description": "create新建、update更新、delete删除、ensure_exists/upsert不存在则创建存在则返回；不支持无目标批量删除",
                        },
                        "payload": {
                            "type": "object",
                            "description": (
                                "业务字段。create 直接传业务字段；update/delete 可传 id，或传 selector 精确定位，"
                                "update 的修改内容放 changes/fields。customers 可按 customer_name，products 优先按 "
                                "model_number，materials 优先按 material_code，shipment_records 仅按 id。"
                                "products 的 unit/measure_unit 表示计量单位；旧 unit_name 仅兼容常见计量单位。"
                            ),
                        },
                    },
                    "required": ["entity", "operation", "payload"],
                },
            },
            "risk_level": "medium",
        },
    ]


def try_execute_business_db_tool(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Route chat-facing business database aliases through the registered service."""
    actions = {
        "business_db_read": "read",
        "business_db_write": "write",
    }
    action = actions.get(name)
    if action is None:
        return None

    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    return execute_registered_workflow_tool("business_db", action, args)
