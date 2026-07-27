"""Deterministic multi-region workbook parser for linked customer/product data."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any

from app.application.etl.llm_assist import advise_workbook_regions
from app.application.etl.parser_structure import clean_cell_text, semantic_key
from app.application.etl.parser_types import ParsedDataset, ParsedRow

_FINANCE_RE = re.compile(r"(回款|付款|收款|对账|欠款|余额|账龄|明细账)", re.I)
_CATALOG_RE = re.compile(r"(报价|价格|价目|色漆编号|色号|样品|目录)", re.I)
_DELIVERY_RE = re.compile(r"(送货|发货|出货|delivery)", re.I)
_TOTAL_RE = re.compile(r"^(合计|总计|小计|汇总)(?:\s|[:：]|$)", re.I)
_NON_PRODUCT_RE = re.compile(
    r"^(运费|物流费|配送费|快递费|装卸费|服务费|折扣|优惠|税费)$",
    re.I,
)
_BUYER_LABEL_RE = re.compile(
    r"(?:(?:购货单位|购买单位|采购单位)(?:（[^）]*）|\([^)]*\))?"
    r"|(?:客户(?:名称)?|买方|buyer|bill\s*to|sold\s*to))"
    r"\s*[:：]\s*(.+?)(?=\s+(?:联系人|电话|手机|日期|订单|单号|编号|20\d{2})|$)",
    re.I,
)
_CONTACT_RE = re.compile(
    r"(?:联系人|经手人)\s*[:：]\s*(.+?)(?=\s+(?:电话|手机|日期|订单|单号|编号|20\d{2})|$)",
    re.I,
)
_PHONE_RE = re.compile(r"(?:电话|手机|联系方式)\s*[:：]\s*([+\d][\d\s-]{5,})", re.I)
_ORDER_RE = re.compile(
    r"(?:订单编号|订单号|单号|order\s*(?:no|number)?)\s*[:：#]?\s*([A-Za-z0-9][\w./-]*)",
    re.I,
)
_DATE_RE = re.compile(r"((?:19|20)\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?)")


def _field_for_header(value: Any) -> str:
    key = semantic_key(value)
    if not key:
        return ""
    if any(token in key for token in ("产品型号", "货品型号", "商品型号", "model", "sku")):
        return "model_number"
    if key in {"型号", "编号", "产品编号", "货号", "物料号", "partcode"}:
        return "model_number"
    if any(token in key for token in ("产品名称", "货品名称", "商品名称", "goodstitle")):
        return "name"
    if key in {"品名", "名称", "产品", "货品"}:
        return "name"
    if "数量kg" in key or "总重量" in key or "重量kg" in key:
        return "quantity_kg"
    if any(token in key for token in ("数量件", "数量桶", "件数", "桶数", "pcscount")):
        return "quantity_tins"
    if key == "数量":
        return "quantity_tins"
    if key.startswith("规格") or key in {"净重", "每桶kg", "netkgeach"}:
        return "specification"
    if any(token in key for token in ("单价", "价格", "现金价", "售价", "unitfee")):
        return "price"
    if any(token in key for token in ("金额", "价税合计", "linesum")):
        return "amount"
    if key in {"备注", "说明", "remark", "description"}:
        return "description"
    return ""


def _header_candidate(values: tuple[Any, ...] | list[Any]) -> dict[str, Any] | None:
    by_field: dict[str, int] = {}
    source_by_col: dict[int, str] = {}
    for index, value in enumerate(values, start=1):
        text = clean_cell_text(value)
        if not text:
            continue
        field = _field_for_header(text)
        if field and field not in by_field:
            by_field[field] = index
            source_by_col[index] = text[:160]
    identities = sum(field in by_field for field in ("model_number", "name"))
    commerce = sum(
        field in by_field
        for field in ("quantity_tins", "quantity_kg", "specification", "price", "amount")
    )
    if not (identities >= 1 and commerce >= 1) and not identities >= 2:
        return None
    if "name" not in by_field and "model_number" not in by_field:
        return None
    first_col = min(source_by_col)
    last_col = max(source_by_col)
    return {
        "by_field": by_field,
        "source_by_col": source_by_col,
        "first_col": first_col,
        "last_col": last_col,
        "headers": [source_by_col[col] for col in sorted(source_by_col)],
        "identity_count": identities,
        "commerce_count": commerce,
    }


def _joined_row(values: tuple[Any, ...] | list[Any], *, max_col: int = 30) -> str:
    return " ".join(text for value in list(values)[:max_col] if (text := clean_cell_text(value)))[
        :2000
    ]


def _extract_meta(
    context_rows: list[tuple[int, tuple[Any, ...]]],
    *,
    max_col: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "customer_name": "",
        "contact_person": "",
        "contact_phone": "",
        "order_number": "",
        "order_date": "",
        "evidence_rows": [],
    }
    for row_number, values in reversed(context_rows[-5:]):
        text = _joined_row(values, max_col=max_col)
        if not text:
            continue
        matched = False
        if not result["customer_name"] and (match := _BUYER_LABEL_RE.search(text)):
            result["customer_name"] = clean_cell_text(match.group(1))[:160]
            matched = True
        if not result["contact_person"] and (match := _CONTACT_RE.search(text)):
            result["contact_person"] = clean_cell_text(match.group(1))[:160]
            matched = True
        if not result["contact_phone"] and (match := _PHONE_RE.search(text)):
            result["contact_phone"] = re.sub(r"\s+", "", match.group(1))[:80]
            matched = True
        if not result["order_number"] and (match := _ORDER_RE.search(text)):
            result["order_number"] = clean_cell_text(match.group(1))[:160]
            matched = True
        if not result["order_date"] and (match := _DATE_RE.search(text)):
            result["order_date"] = clean_cell_text(match.group(1))[:80]
            matched = True
        if matched or _DELIVERY_RE.search(text):
            result["evidence_rows"].append({"row": row_number, "text": text[:800]})
    result["evidence_rows"].reverse()
    return result


def _region_role(
    *,
    sheet_name: str,
    context_rows: list[tuple[int, tuple[Any, ...]]],
    meta: dict[str, Any],
    header: dict[str, Any],
) -> str:
    context = " ".join(
        _joined_row(values, max_col=int(header["last_col"])) for _row, values in context_rows[-4:]
    )
    combined = f"{sheet_name} {context}"
    if _FINANCE_RE.search(combined):
        return "finance"
    if meta.get("customer_name") and (
        _DELIVERY_RE.search(combined) or header["commerce_count"] >= 2
    ):
        return "delivery_note"
    if _CATALOG_RE.search(combined):
        return "product_catalog"
    if _DELIVERY_RE.search(combined):
        return "shipment_ledger"
    return "ignore"


def _is_total_row(values: tuple[Any, ...] | list[Any], *, max_col: int) -> bool:
    cells = [clean_cell_text(value) for value in list(values)[:max_col] if clean_cell_text(value)]
    if not cells:
        return False
    first = semantic_key(cells[0])
    return first in {"合计", "总计", "小计", "汇总"} or bool(_TOTAL_RE.match(" ".join(cells[:2])))


def _value_at(values: tuple[Any, ...] | list[Any], column: int | None) -> Any:
    if not column or column < 1 or column > len(values):
        return None
    return values[column - 1]


def _has_measure(values: tuple[Any, ...] | list[Any], mapping: dict[str, int]) -> bool:
    for field in ("quantity_tins", "quantity_kg", "specification", "price", "amount"):
        value = _value_at(values, mapping.get(field))
        if value not in (None, ""):
            return True
    return False


def _unique_source_headers(source_by_col: dict[int, str]) -> dict[int, str]:
    seen: dict[str, int] = {}
    result: dict[int, str] = {}
    for column in sorted(source_by_col):
        base = source_by_col[column]
        seen[base] = seen.get(base, 0) + 1
        result[column] = base if seen[base] == 1 else f"{base}_{seen[base]}"
    return result


def parse_customer_product_regions(path: Path, *, max_rows: int) -> ParsedDataset | None:
    """Parse explicit buyer + product-table regions without treating the whole sheet as one table."""
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    parsed_rows: list[ParsedRow] = []
    all_headers: list[str] = []
    regions: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    skipped_sheets: list[dict[str, Any]] = []
    excluded_charge_rows: list[str] = []
    imported_by_sheet: dict[str, int] = {}
    try:
        for worksheet in workbook.worksheets:
            recent: deque[tuple[int, tuple[Any, ...]]] = deque(maxlen=5)
            active: dict[str, Any] | None = None
            sheet_candidates = 0
            for row_number, raw_values in enumerate(
                worksheet.iter_rows(values_only=True),
                start=1,
            ):
                values = tuple(raw_values)
                candidate = _header_candidate(values)
                if candidate is not None:
                    active = None
                    sheet_candidates += 1
                    context_rows = list(recent)
                    meta = _extract_meta(
                        context_rows,
                        max_col=int(candidate["last_col"]),
                    )
                    role = _region_role(
                        sheet_name=worksheet.title,
                        context_rows=context_rows,
                        meta=meta,
                        header=candidate,
                    )
                    region_id = (
                        f"{worksheet.title}!R{row_number}"
                        f"C{candidate['first_col']}:{candidate['last_col']}"
                    )
                    probe = {
                        "region_id": region_id,
                        "sheet": worksheet.title,
                        "header_row": row_number,
                        "headers": list(candidate["headers"]),
                        "context_rows": [
                            {
                                "row": number,
                                "text": _joined_row(
                                    row,
                                    max_col=int(candidate["last_col"]),
                                ),
                            }
                            for number, row in context_rows[-5:]
                            if _joined_row(
                                row,
                                max_col=int(candidate["last_col"]),
                            )
                        ],
                        "deterministic_role": role,
                        "explicit_customer": str(meta.get("customer_name") or ""),
                    }
                    probes.append(probe)
                    region = {
                        "id": region_id,
                        "sheet": worksheet.title,
                        "role": role,
                        "header_row": row_number,
                        "first_column": candidate["first_col"],
                        "last_column": candidate["last_col"],
                        "headers": list(candidate["headers"]),
                        "customer_name": str(meta.get("customer_name") or ""),
                        "contact_person": str(meta.get("contact_person") or ""),
                        "order_number": str(meta.get("order_number") or ""),
                        "order_date": str(meta.get("order_date") or ""),
                        "evidence_rows": list(meta.get("evidence_rows") or []),
                        "row_count": 0,
                        "status": "selected" if role == "delivery_note" else "excluded",
                    }
                    regions.append(region)
                    if role == "delivery_note" and meta.get("customer_name"):
                        active = {
                            "region": region,
                            "meta": meta,
                            "mapping": dict(candidate["by_field"]),
                            "source_by_col": _unique_source_headers(
                                dict(candidate["source_by_col"])
                            ),
                            "max_col": candidate["last_col"],
                        }
                    recent.append((row_number, values))
                    continue

                if active is not None:
                    if _is_total_row(values, max_col=int(active["max_col"])):
                        active = None
                        recent.append((row_number, values))
                        continue
                    mapping = active["mapping"]
                    name = clean_cell_text(_value_at(values, mapping.get("name")))
                    model = clean_cell_text(_value_at(values, mapping.get("model_number")))
                    if (name or model) and _has_measure(values, mapping):
                        business_name = name or model
                        if _NON_PRODUCT_RE.fullmatch(business_name):
                            excluded_charge_rows.append(f"{worksheet.title}:{row_number}")
                        else:
                            source_values: dict[str, Any] = {
                                "customer_name": active["meta"]["customer_name"],
                            }
                            if active["meta"].get("contact_person"):
                                source_values["contact_person"] = active["meta"]["contact_person"]
                            if active["meta"].get("contact_phone"):
                                source_values["contact_phone"] = active["meta"]["contact_phone"]
                            original_fragment: dict[str, Any] = {}
                            columns: dict[str, int] = {}
                            for field, column in mapping.items():
                                value = _value_at(values, column)
                                if value not in (None, ""):
                                    source_values[field] = value
                                    original_fragment[
                                        active["source_by_col"].get(column, field)
                                    ] = value
                                    columns[field] = column
                            if len(parsed_rows) >= max_rows:
                                from app.application.etl.errors import EtlError

                                raise EtlError(
                                    "ETL_ROW_LIMIT_EXCEEDED",
                                    f"文件超过 {max_rows} 行限制",
                                    status_code=413,
                                )
                            for header in source_values:
                                if header not in all_headers:
                                    all_headers.append(header)
                            region = active["region"]
                            parsed_rows.append(
                                ParsedRow(
                                    sheet=worksheet.title,
                                    row_number=row_number,
                                    values=source_values,
                                    provenance={
                                        "sheet": worksheet.title,
                                        "row": row_number,
                                        "source_kind": "delivery_note_region",
                                        "region_id": region["id"],
                                        "header_rows": {
                                            "start": region["header_row"],
                                            "end": region["header_row"],
                                        },
                                        "table_position": {
                                            "row": row_number,
                                            "first_column": region["first_column"],
                                            "last_column": region["last_column"],
                                        },
                                        "meta_evidence": list(
                                            active["meta"].get("evidence_rows") or []
                                        ),
                                        "external_order_no": active["meta"].get("order_number"),
                                        "order_date": active["meta"].get("order_date"),
                                        "original_fragment": original_fragment,
                                        "columns": columns,
                                    },
                                )
                            )
                            region["row_count"] += 1
                            imported_by_sheet[worksheet.title] = (
                                imported_by_sheet.get(worksheet.title, 0) + 1
                            )
                recent.append((row_number, values))
            if not imported_by_sheet.get(worksheet.title):
                skipped_sheets.append(
                    {
                        "name": worksheet.title,
                        "reason": (
                            "non_target_regions"
                            if sheet_candidates
                            else "no_explicit_customer_product_region"
                        ),
                    }
                )
    finally:
        workbook.close()

    if not parsed_rows:
        return None

    llm = advise_workbook_regions(probes)
    llm_by_region = {
        str(item.get("region_id") or ""): item
        for item in list(llm.data.get("regions") or [])
        if isinstance(item, dict)
    }
    for region in regions:
        suggestion = llm_by_region.get(region["id"])
        if suggestion:
            region["llm_suggestion"] = suggestion

    selected = [region for region in regions if region["status"] == "selected"]
    excluded = [region for region in regions if region["status"] == "excluded"]
    warnings: list[dict[str, Any]] = [
        {
            "code": "ETL_MULTI_REGION_WORKBOOK_PLANNED",
            "message": (
                f"已从混合工作簿识别 {len(selected)} 个客户产品业务区块，"
                f"排除 {len(excluded)} 个其他业务区块。"
            ),
            "selected_regions": len(selected),
            "excluded_regions": len(excluded),
        }
    ]
    if excluded_charge_rows:
        warnings.append(
            {
                "code": "ETL_NON_PRODUCT_CHARGES_SKIPPED",
                "message": f"已跳过 {len(excluded_charge_rows)} 行运费等非产品费用。",
                "count": len(excluded_charge_rows),
                "rows": excluded_charge_rows[:50],
            }
        )
    return ParsedDataset(
        headers=all_headers,
        rows=parsed_rows,
        source_features={
            "kind": "workbook_regions",
            "structure_detection": "deterministic_regions_v1",
            "region_summary": {
                "candidates": len(regions),
                "selected": len(selected),
                "excluded": len(excluded),
                "business_rows": len(parsed_rows),
                "customers": sorted(
                    {
                        str(region.get("customer_name") or "")
                        for region in selected
                        if region.get("customer_name")
                    }
                ),
            },
            "regions": regions,
            "skipped_sheets": skipped_sheets,
            "headers": all_headers,
            "llm_structure": {
                **llm.public_metadata(),
                "suggestion_count": len(llm_by_region),
            },
        },
        warnings=warnings,
    )


__all__ = ["parse_customer_product_regions"]
