"""Deterministic extraction of role values from compact document headers."""

from __future__ import annotations

import re
from typing import Any

HEADER_ROLE_LABELS = {
    "document_number": "订单号",
    "date": "日期",
    "supplier": "供应商",
    "customer": "客户",
    "currency": "币种",
    "contact": "联系人",
    "address": "地址",
    "phone": "电话",
    "tax_number": "税号",
    "total_amount": "合计",
    "remark": "备注",
}

_NEXT_FIELD = (
    r"联系人|经办人|日期|订单(?:编号|号)|单据编号|单号|"
    r"币种|货币|电话|手机|地址|税号|纳税人识别号|备注"
)


def _match_value(pattern: str, candidates: list[str]) -> str:
    for candidate in candidates:
        match = re.search(pattern, candidate, re.I)
        if match:
            return str(match.group(1) or "").strip(" \t,，;；")
    return ""


def _normalized_date(candidates: list[str]) -> str:
    for candidate in candidates:
        match = re.search(
            r"((?:19|20)\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?",
            candidate,
        )
        if match:
            return (
                f"{int(match.group(1)):04d}-"
                f"{int(match.group(2)):02d}-"
                f"{int(match.group(3)):02d}"
            )
    return ""


def normalize_header_role_value(
    role: Any,
    value: Any,
    *,
    label: Any = "",
) -> Any:
    """Extract one semantic field without trusting an LLM-authored substring."""

    role_text = str(role or "").strip()
    raw_value = str(value or "").strip()
    raw_label = str(label or "").strip()
    candidates = [item for item in (raw_label, raw_value) if item]
    if not candidates:
        return value

    if role_text == "date":
        return _normalized_date(candidates) or value

    patterns = {
        "document_number": (
            r"(?:订单(?:编号|号)|采购单号|送货单号|报价单号|发票(?:号码|号)|"
            r"单据编号|单号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9._/-]*)"
        ),
        "customer": (
            rf"(?:购货单位(?:[（(][^）)]*[）)])?|购买单位|采购单位|"
            rf"客户(?:名称)?|买方)\s*[:：]?\s*(.+?)(?=\s*(?:{_NEXT_FIELD}|"
            rf"(?:19|20)\d{{2}}\s*年)|$)"
        ),
        "supplier": (
            rf"(?:供应商(?:名称)?|供方|供货商|卖方|销售单位"
            rf"(?:[（(][^）)]*[）)])?)\s*[:：]?\s*(.+?)"
            rf"(?=\s*(?:{_NEXT_FIELD}|(?:19|20)\d{{2}}\s*年)|$)"
        ),
        "contact": (
            rf"(?:联系人|经办人)\s*[:：]?\s*(.+?)(?=\s*(?:{_NEXT_FIELD}|"
            rf"(?:19|20)\d{{2}}\s*年)|$)"
        ),
        "currency": r"(?:币种|货币)\s*[:：]?\s*([A-Z]{3}|人民币|美元|欧元|日元|港币)",
        "phone": r"(?:电话|手机|联系电话)\s*[:：]?\s*([+0-9()（） -]{6,})",
        "tax_number": r"(?:税号|纳税人识别号)\s*[:：]?\s*([A-Z0-9-]{8,})",
    }
    pattern = patterns.get(role_text)
    if pattern:
        extracted = _match_value(pattern, candidates)
        if extracted:
            return extracted

    if role_text in {"", "other"} and raw_label and raw_label == raw_value:
        for separator in ("：", ":"):
            if separator in raw_value:
                return raw_value.split(separator, 1)[1].strip()
    return value


__all__ = ["HEADER_ROLE_LABELS", "normalize_header_role_value"]
