"""Conservative input-target detection for the ETL Center's automatic mode."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Iterable

from app.application.elt.parsers import KNOWLEDGE_ONLY_SUFFIXES
from app.application.shipment_excel_etl_security import open_etl_input_file

_DELIVERY_RE = re.compile(r"(送货单|发货单|出货单|delivery)", re.I)
_PRODUCT_RE = re.compile(r"(产品名称|商品名称|货品名称|品名)")
_QUANTITY_RE = re.compile(r"(数量|桶数|件数|重量|规格)")
_CUSTOMER_RE = re.compile(r"(购货单位|购买单位|客户名称|客户)")
_ATTENDANCE_RE = re.compile(r"(考勤|上班时间|下班时间|打卡)")
_PURCHASE_RE = re.compile(r"(采购订单|供应商|供货商)")


def _joined(values: Iterable[Any]) -> str:
    return " ".join(str(value).strip() for value in values if value not in (None, ""))[:4000]


def _classify(lines: list[str], *, suffix: str) -> dict[str, Any]:
    text = "\n".join(lines)
    if _DELIVERY_RE.search(text) and _PRODUCT_RE.search(text) and _QUANTITY_RE.search(text):
        return {
            "target_type": "shipment_records",
            "document_type": "delivery_note_workbook",
            "confidence": 0.98,
            "reason": "delivery_title_and_product_table",
        }
    confirmed_sheets = any(name in text for name in ("每日统计", "打卡时间", "原始记录"))
    attendance_fields = (
        re.search(r"姓名", text)
        and re.search(r"日期|workDate", text, re.I)
        and re.search(r"工号|userid|考勤组", text, re.I)
        and re.search(r"上班|下班|打卡", text)
    )
    if confirmed_sheets or attendance_fields:
        return {
            "target_type": "attendance",
            "document_type": "attendance_table",
            "confidence": 0.95 if confirmed_sheets else 0.9,
            "reason": "attendance_sheet_names" if confirmed_sheets else "attendance_headers",
            "confirmed": True,
        }
    if _ATTENDANCE_RE.search(text):
        return {
            "target_type": "abnormal",
            "document_type": "unconfirmed_template",
            "confidence": 0.4,
            "reason": "unconfirmed_attendance_headers",
            "confirmed": False,
        }
    if _PURCHASE_RE.search(text) and _PRODUCT_RE.search(text):
        return {
            "target_type": "purchase_orders",
            "document_type": "purchase_order_table",
            "confidence": 0.86,
            "reason": "purchase_and_product_headers",
        }
    if _CUSTOMER_RE.search(text) and _PRODUCT_RE.search(text):
        return {
            "target_type": "customer_products",
            "document_type": "linked_customer_products",
            "confidence": 0.82,
            "reason": "customer_and_product_headers",
        }
    if _CUSTOMER_RE.search(text):
        return {
            "target_type": "customers",
            "document_type": "customer_table",
            "confidence": 0.74,
            "reason": "customer_headers",
        }
    if _PRODUCT_RE.search(text):
        return {
            "target_type": "products",
            "document_type": "product_table",
            "confidence": 0.72,
            "reason": "product_headers",
        }
    return {
        "target_type": "abnormal",
        "document_type": "unconfirmed_template",
        "confidence": 0.0,
        "reason": f"unconfirmed_template:{suffix}",
        "confirmed": False,
    }


def detect_etl_target(
    path: str | Path, *, suffix: str = "", owner_user_id: int | None = None
) -> dict[str, Any]:
    source = Path(path)
    ext = str(suffix or source.suffix).lower()
    if ext in KNOWLEDGE_ONLY_SUFFIXES:
        return {
            "target_type": "knowledge",
            "document_type": "knowledge_document",
            "confidence": 1.0,
            "reason": "knowledge_only_suffix",
        }
    if ext == ".csv":
        lines: list[str] = []
        with (
            open_etl_input_file(source, owner_user_id=owner_user_id) as stream,
            io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="") as handle,
        ):
            for index, row in enumerate(csv.reader(handle)):
                lines.append(_joined(row))
                if index >= 30:
                    break
        return _classify(lines, suffix=ext)
    if ext in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        with open_etl_input_file(source, owner_user_id=owner_user_id) as stream:
            workbook = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
            workbook_lines: list[str] = []
            try:
                for worksheet in workbook.worksheets[:30]:
                    workbook_lines.append(worksheet.title)
                    for index, sheet_row in enumerate(worksheet.iter_rows(values_only=True)):
                        workbook_lines.append(_joined(sheet_row))
                        if index >= 79:
                            break
            finally:
                workbook.close()
        return _classify(workbook_lines, suffix=ext)
    filename = source.name
    if _DELIVERY_RE.search(filename):
        return {
            "target_type": "shipment_records",
            "document_type": "delivery_note_ocr",
            "confidence": 0.68,
            "reason": "delivery_filename",
        }
    return {
        "target_type": "abnormal",
        "document_type": "unconfirmed_template",
        "confidence": 0.0,
        "reason": "manual_review_required",
        "confirmed": False,
    }


__all__ = ["detect_etl_target"]
