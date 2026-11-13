"""Conservative input-target detection for the ETL Center's automatic mode."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Iterable

from app.application.elt.parsers import KNOWLEDGE_ONLY_SUFFIXES
from app.application.shipment_excel_elt_security import open_elt_input_file

_DELIVERY_RE = re.compile(r"(送货单|发货单|出货单|delivery)", re.I)
_PRODUCT_RE = re.compile(r"(产品名称|商品名称|货品名称|品名)")
_QUANTITY_RE = re.compile(r"(数量|桶数|件数|重量|规格)")
_CUSTOMER_RE = re.compile(r"(购货单位|购买单位|客户名称|客户)")
_ATTENDANCE_RE = re.compile(r"(考勤|上班时间|下班时间|打卡)")
_PURCHASE_RE = re.compile(r"(采购订单|供应商|供货商)")

# 同一文件里既有送货单页又有客户/产品页时，按业务语义优先级打破同分候选。
_TARGET_PRIORITY = {
    "shipment_records": 6,
    "attendance": 5,
    "purchase_orders": 4,
    "customer_products": 3,
    "products": 2,
    "customers": 1,
}


def _compact(text: str) -> str:
    """去掉空白后再匹配：表格标题常用「产 品 名 称」「数 量 / 件」这类字间距。"""
    return re.sub(r"\s+", "", text)


def _joined(values: Iterable[Any]) -> str:
    return " ".join(str(value).strip() for value in values if value not in (None, ""))[:4000]


def _classify(lines: list[str], *, suffix: str) -> dict[str, Any]:
    text = "\n".join(lines)
    compact = _compact(text)
    if _DELIVERY_RE.search(compact) and _PRODUCT_RE.search(compact) and _QUANTITY_RE.search(compact):
        return {
            "target_type": "shipment_records",
            "document_type": "delivery_note_workbook",
            "confidence": 0.98,
            "reason": "delivery_title_and_product_table",
        }
    confirmed_sheets = any(name in text for name in ("每日统计", "打卡时间", "原始记录"))
    attendance_fields = (
        re.search(r"姓名", compact)
        and re.search(r"日期|workDate", text, re.I)
        and re.search(r"工号|userid|考勤组", text, re.I)
        and re.search(r"上班|下班|打卡", compact)
    )
    if confirmed_sheets or attendance_fields:
        return {
            "target_type": "attendance",
            "document_type": "attendance_table",
            "confidence": 0.95 if confirmed_sheets else 0.9,
            "reason": "attendance_sheet_names" if confirmed_sheets else "attendance_headers",
            "confirmed": True,
        }
    if _ATTENDANCE_RE.search(compact):
        return {
            "target_type": "abnormal",
            "document_type": "unconfirmed_template",
            "confidence": 0.4,
            "reason": "unconfirmed_attendance_headers",
            "confirmed": False,
        }
    if _PURCHASE_RE.search(compact) and _PRODUCT_RE.search(compact):
        return {
            "target_type": "purchase_orders",
            "document_type": "purchase_order_table",
            "confidence": 0.86,
            "reason": "purchase_and_product_headers",
        }
    if _CUSTOMER_RE.search(compact) and _PRODUCT_RE.search(compact):
        return {
            "target_type": "customer_products",
            "document_type": "linked_customer_products",
            "confidence": 0.82,
            "reason": "customer_and_product_headers",
        }
    if _CUSTOMER_RE.search(compact):
        return {
            "target_type": "customers",
            "document_type": "customer_table",
            "confidence": 0.74,
            "reason": "customer_headers",
        }
    if _PRODUCT_RE.search(compact):
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


def _pick(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """按置信度优先、业务语义次优选择候选。"""
    return max(
        candidates,
        key=lambda item: (
            float(item.get("confidence") or 0),
            _TARGET_PRIORITY.get(str(item.get("target_type")), 0),
        ),
    )


def detect_elt_target(
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
            open_elt_input_file(source, owner_user_id=owner_user_id) as stream,
            io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="") as handle,
        ):
            for index, row in enumerate(csv.reader(handle)):
                lines.append(_joined(row))
                if index >= 30:
                    break
        return _classify(lines, suffix=ext)
    if ext in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        with open_elt_input_file(source, owner_user_id=owner_user_id) as stream:
            workbook = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
            candidates: list[dict[str, Any]] = []
            workbook_lines: list[str] = []
            try:
                for worksheet in workbook.worksheets[:30]:
                    sheet_lines = [worksheet.title]
                    for index, sheet_row in enumerate(worksheet.iter_rows(values_only=True)):
                        sheet_lines.append(_joined(sheet_row))
                        if index >= 79:
                            break
                    workbook_lines.extend(sheet_lines)
                    candidate = _classify(sheet_lines, suffix=ext)
                    if float(candidate.get("confidence") or 0) > 0:
                        candidate["sheet_name"] = worksheet.title
                        candidates.append(candidate)
            finally:
                workbook.close()
        # 先按工作表独立判定：多工作表文件里真正的业务页往往不是第一页，
        # 合并成一个文本块会被备注/合同文字带偏。
        best = _pick(candidates) if candidates else _classify(workbook_lines, suffix=ext)
        return best
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


__all__ = ["detect_elt_target"]
