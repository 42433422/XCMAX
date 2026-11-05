"""Buyer and order metadata extracted independently from line items."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.application.shipment_etl_profile import (
    ShipmentEtlProfile,
)

from .layout import _joined_row

_CORP_SUFFIX_ONLY = frozenset(
    {
        "ltd",
        "ltd.",
        "limited",
        "inc",
        "inc.",
        "llc",
        "pte",
        "pte.",
        "co",
        "co.",
        "corp",
        "corp.",
        "gmbh",
        "公司",
        "有限公司",
        "股份有限公司",
    }
)

_BUYER_CELL_LABEL = re.compile(
    "^(?:to|bill\\s*to|sold\\s*to|ship\\s*to|consignee|customer|buyer|购货单位|客户名称|客户|采购单位|收货单位|收货方|买方)\\s*[:：]?$",
    re.IGNORECASE,
)

_BUYER_INLINE = re.compile(
    "(?is)(?:bill\\s*to|sold\\s*to|ship\\s*to|(?<![a-z])to|(?<![a-z])buyer|(?<![a-z])customer|购货单位|客户名称|客户|采购单位)\\s*[:：]\\s*([^\\n·|]+?)(?=\\s*(?:·|\\||Incoterms|Payment|Tel|Phone|地址|电话)|$)"
)

_ATTN_CELL_LABEL = re.compile("^(?:attn|attention|联系人)\\s*[:：]?$", re.IGNORECASE)

_ORDER_INLINE = re.compile(
    "(?is)^(?:do\\s*no|invoice\\s*no|buyer\\s*po|po\\s*ref|订单号|订单编号|单号)\\s*[:：]?\\s*([A-Za-z0-9\\-_/]+)"
)


def _unit_name_looks_truncated(unit: str) -> bool:
    text = str(unit or "").strip()
    if not text:
        return True
    if text.lower() in _CORP_SUFFIX_ONLY:
        return True
    if " " not in text and re.fullmatch("[A-Za-z.]{1,6}", text):
        return True
    return False


def _extract_adjacent_buyer_meta(ws, header_row: int) -> dict[str, str]:
    """英文 DO/PI 常见：标签在 A 列、公司名在同行右侧单元格。"""
    from app.application.shipment_excel_etl_llm import unit_name_is_weak

    out = {"unit_name": "", "contact_person": "", "order_number": ""}
    max_col = min(int(getattr(ws, "max_column", 1) or 1), 16)
    scan_to = max(2, min(int(header_row or 2), 30))
    for row in range(1, scan_to):
        for col in range(1, max_col + 1):
            raw = str(ws.cell(row, col).value or "").strip()
            if not raw:
                continue
            inline = _BUYER_INLINE.search(raw)
            if inline and (not out["unit_name"]):
                candidate = inline.group(1).strip().split("\n")[0].strip(" ：:\u3000")
                candidate = re.sub("\\s*\\([^)]*\\)\\s*$", "", candidate).strip()
                if len(candidate) >= 2 and (not unit_name_is_weak(candidate)):
                    out["unit_name"] = candidate
                    continue
            if _BUYER_CELL_LABEL.match(raw) and (not out["unit_name"]):
                for c2 in range(col + 1, min(col + 5, max_col + 1)):
                    val = str(ws.cell(row, c2).value or "").strip()
                    if not val or _BUYER_CELL_LABEL.match(val):
                        continue
                    candidate = val.split("\n")[0].strip()
                    candidate = re.sub("\\s*\\([^)]*\\)\\s*$", "", candidate).strip()
                    if candidate and (not unit_name_is_weak(candidate)):
                        out["unit_name"] = candidate
                    break
                continue
            if _ATTN_CELL_LABEL.match(raw) and (not out["contact_person"]):
                for c2 in range(col + 1, min(col + 4, max_col + 1)):
                    val = str(ws.cell(row, c2).value or "").strip()
                    if val:
                        out["contact_person"] = val.split("\n")[0].strip()
                        break
                continue
            order_m = _ORDER_INLINE.match(raw)
            if order_m and (not out["order_number"]):
                out["order_number"] = order_m.group(1).strip()
    return out


def _parse_buyer_meta(
    ws,
    header_row: int,
    profile: ShipmentEtlProfile,
    *,
    adjacent_buyer: Callable[[Any, int], dict[str, str]],
) -> dict[str, str]:
    meta = {
        "unit_name": "",
        "contact_person": "",
        "order_date": "",
        "order_number": "",
        "title": "",
    }
    mp = profile.meta_patterns
    for row in range(1, header_row):
        text = _joined_row(ws, row)
        if not text:
            continue
        if not meta["title"] and mp.title.search(text):
            meta["title"] = text.strip()
        buyer = mp.buyer.search(text.replace("\u3000", " "))
        if buyer and (not meta["unit_name"]):
            candidate = buyer.group(1).strip(" ：:\u3000")
            candidate = re.sub("\\s*\\([^)]*\\)\\s*$", "", candidate).strip()
            if candidate and (not _unit_name_looks_truncated(candidate)):
                meta["unit_name"] = candidate
        contact = mp.contact.search(text)
        if contact and (not meta["contact_person"]):
            meta["contact_person"] = contact.group(1).strip(" ：:\u3000")
        date_m = mp.date.search(text)
        if date_m and (not meta["order_date"]):
            meta["order_date"] = date_m.group(1).replace(" ", "")
        order_m = mp.order_no.search(text)
        if order_m and (not meta["order_number"]):
            meta["order_number"] = order_m.group(1).strip()
    if not meta["unit_name"]:
        label = mp.buyer_label
        for row in range(1, header_row):
            text = _joined_row(ws, row)
            if label not in text:
                continue
            after = mp.buyer_split.split(text, maxsplit=1)
            if len(after) > 1:
                chunk = mp.buyer_stop.split(after[1], maxsplit=1)[0]
                meta["unit_name"] = chunk.strip(" ：:\u3000")
                break
    adjacent = adjacent_buyer(ws, header_row)
    from app.application.shipment_excel_etl_llm import unit_name_is_weak

    if adjacent.get("unit_name"):
        meta["unit_name"] = adjacent["unit_name"]
    if not meta["contact_person"] and adjacent.get("contact_person"):
        meta["contact_person"] = adjacent["contact_person"]
    if not meta["order_number"] and adjacent.get("order_number"):
        meta["order_number"] = adjacent["order_number"]
    if meta["unit_name"]:
        meta["unit_name"] = re.sub("\\s*\\([^)]*\\)\\s*$", "", meta["unit_name"]).strip()
        meta["unit_name"] = re.split(
            "(?i)\\s{2,}|\\s+(?:Incoterms|Payment|Tel|Phone|地址|电话)\\b",
            meta["unit_name"],
            maxsplit=1,
        )[0].strip()
    if meta["unit_name"] and (
        _unit_name_looks_truncated(meta["unit_name"]) or unit_name_is_weak(meta["unit_name"])
    ):
        meta["unit_name"] = ""
    return meta


def _merge_meta(
    base: dict[str, str], overlay: dict[str, str], *, prefer_overlay: bool = False
) -> dict[str, str]:
    out = dict(base)
    for key in ("unit_name", "contact_person", "order_date", "order_number", "title"):
        val = str((overlay or {}).get(key) or "").strip()
        if not val:
            continue
        if prefer_overlay or not str(out.get(key) or "").strip():
            out[key] = val
    return out
