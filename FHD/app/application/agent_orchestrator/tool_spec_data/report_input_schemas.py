"""Inputs for sales queries, report exports, and workbook verification."""

from __future__ import annotations

from typing import Any

_DATE_BOUNDS = {
    "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD，包含当天"},
}
_REPORT_PERIOD = {
    "type": "string",
    "enum": ["this_month"],
    "description": "用户要求本月或这个月时传 this_month，由宿主计算完整自然月，勿同时传日期",
}

_SALES_FILTERS = {
    **_DATE_BOUNDS,
    "customer_id": {"type": "integer"},
    "customer_name": {"type": "string", "description": "客户完整名称"},
    "status": {"type": "string", "description": "订单状态，已确认用 confirmed"},
    "payment_state": {"type": "string"},
    "min_amount_exclusive": {"type": "number"},
    "region": {"type": "string"},
}

REPORT_INPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("excel_analysis", "statistics"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "expected_row_count": {"type": "integer"},
            "expected_totals": {"type": "object", "additionalProperties": {"type": "number"}},
        },
    },
    ("sales", "execute_closed_loop"): {
        "type": "object",
        "required": ["payload"],
        "properties": {
            "payload": {
                "description": (
                    "销售闭环包含 order、fulfillment、invoice、payment_allocation。"
                    "部分交付按 order.items 顺序在 fulfillment.line_quantities 提供各行正数交付量，"
                    "fulfillment.quantity 为交付总量，invoice 和 payment_allocation 的 requested 均为 false。"
                    "整单交付并开票时，payment_allocation.amount 仅填写明确的实收金额，可低于开票总额。"
                ),
            },
        },
    },
    ("sales", "query"): {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **_SALES_FILTERS,
            "keyword": {"type": "string"},
            "search": {"type": "string"},
            "page": {"type": "integer"},
            "per_page": {"type": "integer"},
        },
    },
    ("reports", "sales_summary"): {
        "type": "object",
        "additionalProperties": False,
        "properties": {**_SALES_FILTERS, "period": _REPORT_PERIOD, "group_by": {"type": "string"}},
    },
    ("finance", "ledger_query"): {
        "type": "object",
        "properties": {
            **{
                name: {**schema, "type": ["string", "null"]}
                for name, schema in _DATE_BOUNDS.items()
            },
            "period": _REPORT_PERIOD,
            "account_id": {"type": ["integer", "string", "null"]},
            "account_code": {"type": ["string", "null"]},
            "status": {"type": ["string", "null"]},
            "page": {"type": "integer"},
            "per_page": {"type": "integer"},
        },
    },
    ("reports", "export"): {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **_SALES_FILTERS,
            "report_type": {"type": "string", "enum": ["sales", "inventory", "purchase"]},
            "group_by": {"type": "string"},
            "filename": {"type": "string"},
            "order_no": {"type": "string", "description": "只导出这一张销售订单"},
            "data": {"type": "array"},
            "warehouse_id": {"type": "integer"},
            "category": {"type": "string"},
            "model_number": {"type": "string"},
        },
    },
}
