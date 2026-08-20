# mypy: disable-error-code="no-any-return, valid-type"
"""Static workflow registry chunk."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.tools.workflow")


def _base_registry_chunk_02():
    return [
        {
            "type": "function",
            "function": {
                "name": "delete_customer",
                "description": "删除客户（购买单位）。高危操作，必须传 confirm=true 才会执行。若客户关联了出货记录，默认会拒绝；可传 force=true 强制删除。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer", "description": "客户 ID"},
                        "force": {"type": "boolean", "description": "是否强制删除（忽略关联检查）"},
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行删除。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["customer_id"],
                },
            },
            "risk_level": "high",
        },
        {
            "type": "function",
            "function": {
                "name": "list_customers",
                "description": "查询客户（购买单位）列表，可按关键字搜索。只读操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filters": {
                            "type": "object",
                            "properties": {
                                "keyword": {"type": "string"},
                                "page": {"type": "integer", "description": "页码，默认 1"},
                                "per_page": {"type": "integer", "description": "每页条数，默认 20"},
                            },
                        },
                        "limit": {
                            "type": "integer",
                            "description": "等价于 per_page；若未提供 per_page 则用此值",
                        },
                    },
                },
            },
            "risk_level": "low",
        },
        {
            "type": "function",
            "function": {
                "name": "configure_report",
                "description": "新建或更新报表配置（报表类型、日期范围、分组维度、图表类型等）。写操作，必须传 confirm=true 才会执行。现有报表类型：sales / inventory / inventory_transactions / purchase / dashboard。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "report_type": {
                            "type": "string",
                            "enum": [
                                "sales",
                                "inventory",
                                "inventory_transactions",
                                "purchase",
                                "dashboard",
                            ],
                            "description": "报表类型",
                        },
                        "config": {
                            "type": "object",
                            "description": "配置内容，可包含 name / date_range / group_by / chart_type / filters 等",
                            "properties": {
                                "name": {"type": "string", "description": "配置名称"},
                                "date_range": {
                                    "type": "object",
                                    "properties": {
                                        "start_date": {"type": "string"},
                                        "end_date": {"type": "string"},
                                    },
                                },
                                "group_by": {
                                    "type": "string",
                                    "enum": [
                                        "product",
                                        "customer",
                                        "supplier",
                                        "category",
                                        "warehouse",
                                        "month",
                                        "week",
                                        "day",
                                    ],
                                },
                                "chart_type": {
                                    "type": "string",
                                    "enum": ["bar", "line", "pie", "table", "scatter"],
                                },
                                "filters": {"type": "object"},
                            },
                        },
                        "config_id": {
                            "type": "string",
                            "description": "可选：若提供则更新现有配置，否则新建",
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行写入。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["report_type", "config"],
                },
            },
            "risk_level": "medium",
        },
        {
            "type": "function",
            "function": {
                "name": "list_report_configs",
                "description": "列出所有报表配置，可按 report_type 过滤。只读操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string", "description": "可选：按报表类型过滤"}
                    },
                },
            },
            "risk_level": "low",
        },
        {
            "type": "function",
            "function": {
                "name": "create_role",
                "description": "创建自定义角色并指定权限列表。写操作，必须传 confirm=true 才会执行。权限 code 须先通过 list_permissions 查询获得。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "角色名称"},
                        "permissions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "权限 code 列表",
                        },
                        "description": {"type": "string", "description": "角色描述"},
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行创建。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["name", "permissions"],
                },
            },
            "risk_level": "high",
        },
        {
            "type": "function",
            "function": {
                "name": "update_role",
                "description": "更新角色描述和权限列表。系统角色只允许修改描述。写操作，必须传 confirm=true。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "integer", "description": "角色 ID"},
                        "description": {"type": "string", "description": "新描述"},
                        "permissions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "新权限 code 列表",
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行更新。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["role_id"],
                },
            },
            "risk_level": "medium",
        },
        {
            "type": "function",
            "function": {
                "name": "delete_role",
                "description": "删除自定义角色（系统角色不可删除）。高危操作，必须传 confirm=true 才会执行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "integer", "description": "角色 ID"},
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行删除。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["role_id"],
                },
            },
            "risk_level": "high",
        },
        {
            "type": "function",
            "function": {
                "name": "assign_role",
                "description": "将用户分配到指定角色（按角色名称修改 User.role 字段）。写操作，必须传 confirm=true 才会执行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "integer", "description": "用户 ID"},
                        "role": {"type": "string", "description": "角色名称"},
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行分配。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["user_id", "role"],
                },
            },
            "risk_level": "high",
        },
        {
            "type": "function",
            "function": {
                "name": "list_roles",
                "description": "列出所有角色及其权限列表。只读操作。",
                "parameters": {
                    "type": "object",
                    "properties": {"tenant_id": {"type": "string", "description": "可选：租户 ID"}},
                },
            },
            "risk_level": "low",
        },
        *_facade().business_db_tool_specs(),
    ]
