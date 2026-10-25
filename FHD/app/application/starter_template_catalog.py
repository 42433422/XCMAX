"""Built-in starter templates exposed without mutating tenant-owned template data."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _field(key: str, label: str, *, required: bool = False) -> dict[str, Any]:
    return {"key": key, "label": label, "required": required, "editable": True}


STARTER_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "seed:customer-ledger",
        "name": "客户资料初始化表",
        "template_type": "客户",
        "category": "excel",
        "fields": [
            _field("customer_code", "客户编码", required=True),
            _field("customer_name", "客户名称", required=True),
            _field("contact", "联系人"),
            _field("phone", "联系电话"),
            _field("address", "地址"),
        ],
    },
    {
        "id": "seed:product-ledger",
        "name": "产品资料初始化表",
        "template_type": "产品",
        "category": "excel",
        "fields": [
            _field("product_code", "产品编码", required=True),
            _field("product_name", "产品名称", required=True),
            _field("specification", "规格型号"),
            _field("unit", "单位"),
            _field("unit_price", "单价"),
        ],
    },
    {
        "id": "seed:sales-order",
        "name": "销售订单标准表",
        "template_type": "销售订单",
        "category": "excel",
        "fields": [
            _field("order_no", "订单号", required=True),
            _field("customer_name", "客户名称", required=True),
            _field("product_name", "产品名称", required=True),
            _field("quantity", "数量", required=True),
            _field("delivery_date", "交付日期"),
        ],
    },
    {
        "id": "seed:shipment",
        "name": "出货记录初始化表",
        "template_type": "出货记录",
        "category": "excel",
        "fields": [
            _field("shipment_no", "出货单号", required=True),
            _field("shipment_date", "出货日期", required=True),
            _field("customer_name", "客户名称", required=True),
            _field("product_name", "产品名称", required=True),
            _field("quantity", "出货数量", required=True),
        ],
    },
    {
        "id": "seed:inventory",
        "name": "库存盘点表",
        "template_type": "库存盘点",
        "category": "excel",
        "fields": [
            _field("material_code", "物料编码", required=True),
            _field("material_name", "物料名称", required=True),
            _field("book_quantity", "账面数量"),
            _field("actual_quantity", "实盘数量"),
            _field("difference", "盘点差异"),
        ],
    },
    {
        "id": "seed:purchase-request",
        "name": "采购申请表",
        "template_type": "采购申请",
        "category": "excel",
        "fields": [
            _field("request_no", "申请单号", required=True),
            _field("material_name", "物料名称", required=True),
            _field("quantity", "申请数量", required=True),
            _field("required_date", "需求日期"),
            _field("applicant", "申请人"),
        ],
    },
    {
        "id": "seed:quotation",
        "name": "客户报价单",
        "template_type": "报价单",
        "category": "excel",
        "fields": [
            _field("quotation_no", "报价单号", required=True),
            _field("customer_name", "客户名称", required=True),
            _field("product_name", "产品名称", required=True),
            _field("unit_price", "报价单价", required=True),
            _field("valid_until", "有效期至"),
        ],
    },
    {
        "id": "seed:reconciliation",
        "name": "客户对账单",
        "template_type": "对账单",
        "category": "excel",
        "fields": [
            _field("period", "对账期间", required=True),
            _field("customer_name", "客户名称", required=True),
            _field("document_no", "单据编号"),
            _field("receivable", "应收金额"),
            _field("received", "已收金额"),
        ],
    },
    {
        "id": "seed:sales-contract",
        "name": "销售合同（通用）",
        "template_type": "Word",
        "category": "word",
        "fields": [
            _field("contract_no", "合同编号", required=True),
            _field("party_a", "甲方", required=True),
            _field("party_b", "乙方", required=True),
            _field("contract_amount", "合同金额"),
            _field("sign_date", "签订日期"),
        ],
    },
    {
        "id": "seed:work-report",
        "name": "工作报告（通用）",
        "template_type": "Word",
        "category": "word",
        "fields": [
            _field("title", "报告标题", required=True),
            _field("author", "编制人"),
            _field("period", "报告周期"),
            _field("summary", "工作摘要"),
            _field("next_plan", "下一步计划"),
        ],
    },
]


def merge_starter_templates(
    templates: list[dict[str, Any]] | None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    existing = list(templates or [])
    existing_ids = {str(row.get("id") or "") for row in existing if isinstance(row, dict)}
    requested = str(category or "all").strip().lower()
    for raw in STARTER_TEMPLATES:
        if raw["id"] in existing_ids:
            continue
        if requested not in {"", "all"} and requested not in {
            str(raw.get("category") or "").lower(),
            str(raw.get("template_type") or "").lower(),
        }:
            continue
        row = deepcopy(raw)
        row.update(
            {
                "source": "builtin_seed",
                "starter": True,
                "read_only": True,
                "is_active": 1,
                "exists": False,
                "file_path": None,
                "preview_capable": True,
                "preview_data": {"columns": row.get("fields") or [], "rows": []},
            }
        )
        existing.append(row)
    return existing
