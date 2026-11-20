"""Inputs for sales queries, report exports, and workbook verification."""

from __future__ import annotations

from typing import Any

_SALES_FILTERS = {
    "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD，包含当天"},
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
        "properties": {**_SALES_FILTERS, "group_by": {"type": "string"}},
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
