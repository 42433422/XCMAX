"""Public business workflow tool definitions, in their registered order."""

from __future__ import annotations

from app.application.tools.workflow_tools.contracts import Payload
from app.application.tools.workflow_tools.registry import tool_spec


def business_tool_specs() -> list[Payload]:
    return [
        tool_spec(
            "delete_order",
            "删除单条订单（出货记录）。高危操作，必须传 confirm=true 才会真正执行。若未传 confirm，返回预览信息等待用户二次确认。",
            {
                "order_number": {
                    "type": "string",
                    "description": "订单 ID（出货记录主键，与 /api/shipment/orders/{order_number} "
                    "同语义）",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行删除。必须显式传 true 才会执行",
                },
            },
            ["order_number"],
            risk_level="high",
        ),
        tool_spec(
            "update_order",
            "更新订单（出货记录）字段，如购买单位、产品名、型号、数量、单价、金额、状态等。写操作，必须传 confirm=true 才会执行。",
            {
                "order_number": {"type": "string", "description": "订单 ID（出货记录主键）"},
                "fields": {
                    "type": "object",
                    "description": "待更新字段。支持 unit_name / product_name / model_number / "
                    "quantity_kg / quantity_tins / tin_spec / unit_price / "
                    "amount / status / date",
                    "properties": {
                        "unit_name": {"type": "string"},
                        "product_name": {"type": "string"},
                        "model_number": {"type": "string"},
                        "quantity_kg": {"type": "number"},
                        "quantity_tins": {"type": "integer"},
                        "tin_spec": {"type": "string"},
                        "unit_price": {"type": "number"},
                        "amount": {"type": "number"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "printed", "completed", "cancelled"],
                        },
                        "date": {"type": "string", "description": "ISO 日期字符串"},
                    },
                },
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行更新。必须显式传 true 才会执行",
                },
            },
            ["order_number", "fields"],
            risk_level="medium",
        ),
        tool_spec(
            "list_orders",
            "查询订单（出货记录）列表。支持按购买单位、关键字过滤，返回最近记录。只读操作。",
            {
                "filters": {
                    "type": "object",
                    "description": "过滤条件",
                    "properties": {
                        "unit_name": {"type": "string", "description": "购买单位名"},
                        "keyword": {"type": "string", "description": "搜索关键字"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                },
                "limit": {"type": "integer", "description": "返回条数上限，默认 20，最大 200"},
            },
            risk_level="low",
        ),
        tool_spec(
            "update_customer",
            "更新客户（购买单位）信息：客户名称、联系人、电话、地址。写操作，必须传 confirm=true 才会执行。",
            {
                "customer_id": {"type": "integer", "description": "客户 ID"},
                "fields": {
                    "type": "object",
                    "description": "待更新字段。支持 customer_name / contact_person / contact_phone / "
                    "contact_address",
                    "properties": {
                        "customer_name": {"type": "string"},
                        "contact_person": {"type": "string"},
                        "contact_phone": {"type": "string"},
                        "contact_address": {"type": "string"},
                    },
                },
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行更新。必须显式传 true 才会执行",
                },
            },
            ["customer_id", "fields"],
            risk_level="medium",
        ),
        tool_spec(
            "delete_customer",
            "删除客户（购买单位）。高危操作，必须传 confirm=true 才会执行。若客户关联了出货记录，默认会拒绝；可传 force=true 强制删除。",
            {
                "customer_id": {"type": "integer", "description": "客户 ID"},
                "force": {"type": "boolean", "description": "是否强制删除（忽略关联检查）"},
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行删除。必须显式传 true 才会执行",
                },
            },
            ["customer_id"],
            risk_level="high",
        ),
        tool_spec(
            "list_customers",
            "查询客户（购买单位）列表，可按关键字搜索。只读操作。",
            {
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
            risk_level="low",
        ),
        tool_spec(
            "configure_report",
            "新建或更新报表配置（报表类型、日期范围、分组维度、图表类型等）。写操作，必须传 confirm=true 才会执行。现有报表类型：sales / inventory / inventory_transactions / purchase / dashboard。",
            {
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
                    "description": "配置内容，可包含 name / date_range / group_by / chart_type / "
                    "filters 等",
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
            ["report_type", "config"],
            risk_level="medium",
        ),
        tool_spec(
            "list_report_configs",
            "列出所有报表配置，可按 report_type 过滤。只读操作。",
            {"report_type": {"type": "string", "description": "可选：按报表类型过滤"}},
            risk_level="low",
        ),
        tool_spec(
            "create_role",
            "创建自定义角色并指定权限列表。写操作，必须传 confirm=true 才会执行。权限 code 须先通过 list_permissions 查询获得。",
            {
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
            ["name", "permissions"],
            risk_level="high",
        ),
        tool_spec(
            "update_role",
            "更新角色描述和权限列表。系统角色只允许修改描述。写操作，必须传 confirm=true。",
            {
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
            ["role_id"],
            risk_level="medium",
        ),
        tool_spec(
            "delete_role",
            "删除自定义角色（系统角色不可删除）。高危操作，必须传 confirm=true 才会执行。",
            {
                "role_id": {"type": "integer", "description": "角色 ID"},
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行删除。必须显式传 true 才会执行",
                },
            },
            ["role_id"],
            risk_level="high",
        ),
        tool_spec(
            "assign_role",
            "将用户分配到指定角色（按角色名称修改 User.role 字段）。写操作，必须传 confirm=true 才会执行。",
            {
                "user_id": {"type": "integer", "description": "用户 ID"},
                "role": {"type": "string", "description": "角色名称"},
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行分配。必须显式传 true 才会执行",
                },
            },
            ["user_id", "role"],
            risk_level="high",
        ),
        tool_spec(
            "list_roles",
            "列出所有角色及其权限列表。只读操作。",
            {"tenant_id": {"type": "string", "description": "可选：租户 ID"}},
            risk_level="low",
        ),
    ]
