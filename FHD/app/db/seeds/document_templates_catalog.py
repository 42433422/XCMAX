"""开箱模板目录：文件名 / template_key / 业务类型（Excel 通用表 + 发货单/价格表）。"""

from __future__ import annotations

from typing import Any

# 与 scripts/dev/generate_initial_document_templates.py 生成物对齐
GENERIC_EXCEL_SEED_SPECS: list[dict[str, Any]] = [
    {
        "filename": "通用_出货明细.xlsx",
        "template_key": "SEED_ORDERS_DEFAULT",
        "template_name": "通用出货明细表",
        "template_type": "出货明细",
        "business_scope": "orders",
        "category": "excel",
        "fields": [
            {"label": "产品型号"},
            {"label": "产品名称"},
            {"label": "数量"},
            {"label": "单价"},
            {"label": "金额"},
        ],
    },
    {
        "filename": "通用_出货记录.xlsx",
        "template_key": "SEED_SHIPMENT_RECORDS_DEFAULT",
        "template_name": "通用出货记录表",
        "template_type": "出货记录",
        "business_scope": "shipmentRecords",
        "category": "excel",
        "fields": [
            {"label": "购买单位"},
            {"label": "产品名称"},
            {"label": "型号"},
            {"label": "数量"},
            {"label": "单价"},
            {"label": "金额"},
        ],
    },
    {
        "filename": "通用_产品目录.xlsx",
        "template_key": "SEED_PRODUCTS_DEFAULT",
        "template_name": "通用产品目录表",
        "template_type": "产品目录",
        "business_scope": "products",
        "category": "excel",
        "fields": [
            {"label": "产品型号"},
            {"label": "产品名称"},
            {"label": "规格"},
            {"label": "单价"},
        ],
    },
    {
        "filename": "通用_原材料.xlsx",
        "template_key": "SEED_MATERIALS_DEFAULT",
        "template_name": "通用原材料表",
        "template_type": "原材料",
        "business_scope": "materials",
        "category": "excel",
        "fields": [
            {"label": "原材料编码"},
            {"label": "名称"},
            {"label": "分类"},
            {"label": "规格"},
            {"label": "单位"},
            {"label": "库存数量"},
            {"label": "单价"},
            {"label": "供应商"},
        ],
    },
    {
        "filename": "通用_客户.xlsx",
        "template_key": "SEED_CUSTOMERS_DEFAULT",
        "template_name": "通用客户表",
        "template_type": "客户",
        "business_scope": "customers",
        "category": "excel",
        "fields": [
            {"label": "客户名称"},
            {"label": "联系人"},
            {"label": "电话"},
            {"label": "地址"},
        ],
    },
    {
        "filename": "通用_汇总统计.xlsx",
        "template_key": "SEED_SHIPMENT_SUMMARY_DEFAULT",
        "template_name": "通用汇总统计表",
        "template_type": "汇总统计",
        "business_scope": "shipmentSummary",
        "category": "excel",
        "fields": [
            {"label": "金额"},
            {"label": "金额合计"},
            {"label": "金额总计"},
        ],
    },
    {
        "filename": "通用_销售报表.xlsx",
        "template_key": "SEED_SALES_REPORT_DEFAULT",
        "template_name": "通用销售报表",
        "template_type": "销售报表",
        "business_scope": "salesReport",
        "category": "excel",
        "fields": [
            {"label": "销售金额"},
            {"label": "实收款"},
            {"label": "下欠款金额"},
        ],
    },
    {
        "filename": "通用_考勤记录.xlsx",
        "template_key": "SEED_ATTENDANCE_DEFAULT",
        "template_name": "通用考勤记录表",
        "template_type": "考勤记录",
        "business_scope": "shipmentRecords",
        "category": "excel",
        "fields": [
            {"label": "购买单位"},
            {"label": "产品名称"},
            {"label": "型号"},
            {"label": "数量"},
            {"label": "单价"},
            {"label": "金额"},
        ],
    },
]

CORE_DOCUMENT_SEED_SPECS: list[dict[str, Any]] = [
    {
        "filename": "发货单模板.xlsx",
        "template_key": "SEED_SHIPMENT_DEFAULT",
        "template_name": "演示发货单模板",
        "template_type": "发货单",
        "business_scope": "",
        "category": "excel",
        "fields": [
            {"label": "购买单位"},
            {"label": "产品型号"},
            {"label": "产品名称"},
            {"label": "数量"},
            {"label": "规格"},
            {"label": "单价"},
            {"label": "金额"},
        ],
        "runtime_subdir": "templates",
    },
    {
        "filename": "price_list_default.docx",
        "template_key": "SEED_PRICE_LIST_DEFAULT",
        "template_name": "演示产品价格表",
        "template_type": "价格表",
        "business_scope": "",
        "category": "word",
        "fields": [
            {"label": "客户名称"},
            {"label": "型号"},
            {"label": "名称"},
            {"label": "规格"},
            {"label": "单价"},
        ],
        "runtime_subdir": "424/document_templates",
    },
]

__all__ = [
    "GENERIC_EXCEL_SEED_SPECS",
    "CORE_DOCUMENT_SEED_SPECS",
]
