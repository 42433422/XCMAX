"""发货单自动审单规则（纯函数，无 I/O）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIN_OCR_CONFIDENCE = 0.55
MIN_LINE_QUANTITY = 0.01
MAX_LINE_AMOUNT = 1_000_000.0


@dataclass(frozen=True)
class AuditDecision:
    decision: str  # auto_approve | manual | ocr_failed
    reason: str


def _items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items") or payload.get("products") or []
    return [i for i in items if isinstance(i, dict)]


def evaluate_shipment_payload(payload: dict[str, Any]) -> AuditDecision:
    """基于结构化发货单字段评估审单结果。"""
    unit = str(payload.get("purchase_unit") or payload.get("unit_name") or "").strip()
    if not unit:
        return AuditDecision("manual", "缺少购货单位")

    items = _items_from_payload(payload)
    if not items:
        return AuditDecision("manual", "缺少产品行项")

    for idx, item in enumerate(items, start=1):
        name = str(item.get("product_name") or item.get("name") or "").strip()
        if not name:
            return AuditDecision("manual", f"第{idx}行缺少产品名称")
        qty = float(item.get("quantity_kg") or item.get("quantity") or 0)
        if qty < MIN_LINE_QUANTITY:
            tins = float(item.get("quantity_tins") or 0)
            if tins < MIN_LINE_QUANTITY:
                return AuditDecision("manual", f"第{idx}行数量无效")
        amount = float(item.get("amount") or item.get("total_price") or 0)
        if amount < 0 or amount > MAX_LINE_AMOUNT:
            return AuditDecision("manual", f"第{idx}行金额异常")

    return AuditDecision("auto_approve", "规则校验通过")


def evaluate_ocr_payload(
    structured: dict[str, Any],
    *,
    ocr_confidence: float | None = None,
    parse_ok: bool = True,
) -> AuditDecision:
    """基于 OCR 结构化结果评估审单结果。"""
    if not parse_ok:
        return AuditDecision("ocr_failed", "OCR 解析失败")

    if ocr_confidence is not None and ocr_confidence < MIN_OCR_CONFIDENCE:
        return AuditDecision("manual", f"OCR 置信度过低 ({ocr_confidence:.2f})")

    if not structured.get("purchase_unit"):
        return AuditDecision("ocr_failed", "OCR 未识别购货单位")

    return evaluate_shipment_payload(
        {
            "purchase_unit": structured.get("purchase_unit"),
            "items": structured.get("products") or [],
        }
    )
