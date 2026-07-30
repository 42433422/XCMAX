"""Evidence-bound document understanding for structured business workbooks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from app.application.etl.document_routing import (
    DOCUMENT_TARGETS as _DOCUMENT_TARGETS,
)
from app.application.etl.document_routing import (
    build_document_routes,
    build_sheet_inventory,
)
from app.application.etl.llm_assist import advise_document_understanding
from app.application.etl.parser_structure import header_match_score, semantic_key
from app.application.etl.workbook_evidence import (
    build_workbook_evidence,
    public_evidence_summary,
)

_TARGET_DOCUMENTS = {
    "purchase_orders": "purchase_order",
    "shipment_records": "delivery_note",
    "attendance": "attendance",
    "customers": "customer_directory",
    "products": "product_catalog",
    "customer_products": "product_catalog",
}

_HEADER_ROLE_HINTS = {
    "document_number": (
        "单号",
        "订单号",
        "采购单号",
        "编号",
        "no",
        "number",
        "do no",
        "invoice no",
        "po ref",
        "pl no",
    ),
    "date": ("日期", "下单日期", "开票日期", "date", "invoice date", "do date"),
    "supplier": (
        "供应商",
        "供方",
        "供货商",
        "seller",
        "supplier",
        "shipper",
        "vendor",
    ),
    "customer": (
        "客户",
        "购货单位",
        "采购单位",
        "买方",
        "buyer",
        "customer",
        "to",
        "bill to",
        "consignee",
    ),
    "currency": ("币种", "货币", "currency"),
    "contact": ("联系人", "经办人", "contact"),
}

_COLUMN_ROLE_HINTS = {
    "product_name": (
        "产品名称",
        "商品名称",
        "货品名称",
        "品名",
        "产品",
        "description",
        "part no / description",
        "contents",
        "item description",
    ),
    "product_model": ("产品型号", "型号", "规格型号", "model", "sku", "part no", "item no"),
    "specification": ("规格", "规格kg", "specification", "size"),
    "quantity": ("数量", "采购数量", "件数", "桶数", "qty", "quantity"),
    "unit": ("单位", "计量单位", "unit"),
    "unit_price": ("单价", "价格", "报价", "price", "unit price"),
    "amount": ("金额", "价税合计", "小计", "amount", "total"),
    "employee_name": ("姓名", "员工姓名", "name"),
    "department": ("部门", "department"),
    "attendance_date": ("考勤日期", "date"),
}

_DOCUMENT_MARKERS = {
    "purchase_order": ("采购订单", "采购单号", "purchase order"),
    "delivery_note": (
        "送货单",
        "发货单",
        "出货单",
        "delivery note",
        "delivery order",
    ),
    "quotation": ("报价单", "询价单", "quotation", "quote"),
    "invoice": ("发票", "invoice", "价税合计"),
    "packing_list": ("装箱单", "包装清单", "packing list", "packplan", "箱号"),
    "attendance": ("考勤", "打卡", "attendance"),
}

_INLINE_HEADER_PATTERNS = {
    "document_number": re.compile(
        r"(?:invoice\s*no|d/?o\s*no|delivery\s*order\s*no|po\s*ref|"
        r"quotation\s*no|订单号|采购单号|单号|编号|no\.)\s*[:：.]?\s*"
        r"([A-Z0-9][A-Z0-9_./-]{2,})",
        re.I,
    ),
    "date": re.compile(
        r"(?:invoice\s*date|d/?o\s*date|date|日期)\s*[:：]?\s*"
        r"((?:19|20)\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?)",
        re.I,
    ),
    "customer": re.compile(
        r"(?:bill\s*to|consignee|buyer|customer|购货单位|采购单位|客户|买方|to)"
        r"\s*[:：]\s*(.+?)(?=\s+(?:shipper|seller|supplier|incoterms|date|po)\s*[:：]|[·\n]|$)",
        re.I,
    ),
    "supplier": re.compile(
        r"(?:shipper|seller|supplier|vendor|供应商|供货商|供方)"
        r"\s*[:：]\s*(.+?)(?=\s+(?:consignee|buyer|customer|date|po)\s*[:：]|[·\n]|$)",
        re.I,
    ),
}


def _best_role(label: Any, role_hints: dict[str, tuple[str, ...]]) -> str:
    label_key = semantic_key(label)
    if label_key.isascii() and len(label_key) <= 2:
        for role, hints in role_hints.items():
            if any(semantic_key(hint) == label_key for hint in hints):
                return role
        return ""
    scored = [
        (
            header_match_score(
                str(label or ""),
                tuple(
                    hint
                    for hint in hints
                    if (
                        not semantic_key(hint).isascii()
                        or len(semantic_key(hint)) > 2
                        or semantic_key(hint) == label_key
                    )
                ),
            ),
            role,
        )
        for role, hints in role_hints.items()
    ]
    score, role = max(scored, default=(0.0, ""))
    return role if score >= 0.75 else ""


def _candidate_context(
    evidence: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    sheet = str(candidate.get("sheet") or "")
    header_end = int(candidate.get("header_end_row") or 0)
    cells: list[dict[str, Any]] = []
    for sheet_evidence in evidence.get("sheets") or []:
        if str(sheet_evidence.get("name") or "") != sheet:
            continue
        for row in sheet_evidence.get("rows") or []:
            if int(row.get("row") or 0) <= header_end:
                cells.extend(row.get("cells") or [])
        break
    values = [sheet, *(candidate.get("headers") or [])]
    values.extend(
        item.get("label")
        for item in evidence.get("key_value_candidates") or []
        if str(item.get("sheet") or "") == sheet
    )
    values.extend(cell.get("text") for cell in cells)
    return " ".join(str(value or "").strip().lower() for value in values), cells


def _fallback_document_type(
    evidence: dict[str, Any],
    candidate: dict[str, Any],
    hinted_target_type: str,
    hint_confidence: float,
) -> tuple[str, float, list[str]]:
    context, _ = _candidate_context(evidence, candidate)
    header_roles = {
        _best_role(header, _COLUMN_ROLE_HINTS) for header in candidate.get("headers") or []
    }
    header_roles.discard("")
    has_product = bool({"product_name", "product_model"} & header_roles)
    has_quantity = "quantity" in header_roles
    has_price = bool({"unit_price", "amount"} & header_roles)

    if any(marker in context for marker in _DOCUMENT_MARKERS["delivery_note"]):
        if has_product and has_quantity:
            return "delivery_note", 0.96, ["delivery_marker", "product_quantity_table"]
    if any(marker in context for marker in _DOCUMENT_MARKERS["purchase_order"]):
        if has_product and has_quantity and has_price:
            return "purchase_order", 0.97, ["purchase_marker", "priced_product_table"]
    if any(marker in context for marker in _DOCUMENT_MARKERS["invoice"]):
        if has_product and has_price:
            return "invoice", 0.94, ["invoice_marker", "priced_product_table"]
    if any(marker in context for marker in _DOCUMENT_MARKERS["quotation"]):
        if has_product and has_price:
            return "quotation", 0.93, ["quotation_marker", "priced_product_table"]
    if any(marker in context for marker in _DOCUMENT_MARKERS["packing_list"]):
        if has_product or has_quantity:
            return "packing_list", 0.92, ["packing_marker", "line_item_table"]
    if any(marker in context for marker in _DOCUMENT_MARKERS["attendance"]):
        if {"employee_name", "attendance_date"} & header_roles:
            return "attendance", 0.94, ["attendance_marker", "employee_table"]
    if "employee_name" in header_roles and "department" in header_roles:
        return "attendance", 0.84, ["employee_department_table"]
    hinted_document = _TARGET_DOCUMENTS.get(hinted_target_type)
    if hinted_document and hint_confidence >= 0.6:
        return hinted_document, hint_confidence, ["target_detection_hint"]
    return (
        "generic_table",
        max(0.35, float(candidate.get("confidence") or 0.0)),
        ["insufficient_semantic_evidence"],
    )


def _title_cells(
    evidence: dict[str, Any],
    candidate: dict[str, Any],
    document_type: str,
) -> list[dict[str, Any]]:
    _, cells = _candidate_context(evidence, candidate)
    markers = _DOCUMENT_MARKERS.get(document_type, ())
    matched = [
        {
            "cell_id": str(cell.get("id") or ""),
            "coordinate": str(cell.get("coordinate") or ""),
            "value": cell.get("value"),
        }
        for cell in cells
        if any(marker in str(cell.get("text") or "").lower() for marker in markers)
    ]
    return matched[:8]


def _derived_header_fields(
    evidence: dict[str, Any],
    candidate: dict[str, Any],
    existing_roles: set[str],
) -> list[dict[str, Any]]:
    _, cells = _candidate_context(evidence, candidate)
    derived: list[dict[str, Any]] = []
    for cell in cells:
        text = str(cell.get("text") or "").strip()
        if not text:
            continue
        for role, pattern in _INLINE_HEADER_PATTERNS.items():
            if role in existing_roles:
                continue
            match = pattern.search(text)
            if not match:
                continue
            derived.append(
                {
                    "role": role,
                    "label": match.group(0)[:160],
                    "value": match.group(1).strip()[:300],
                    "label_cell_id": cell.get("id"),
                    "value_cell_id": cell.get("id"),
                    "label_coordinate": cell.get("coordinate"),
                    "value_coordinate": cell.get("coordinate"),
                    "reason": "deterministic_inline_header_pattern",
                }
            )
            existing_roles.add(role)
        if "document_number" not in existing_roles:
            standalone = re.search(r"\b(?:PL|PI|PK|DO|PO)-[A-Z0-9][A-Z0-9./-]{2,}\b", text, re.I)
            if standalone:
                derived.append(
                    {
                        "role": "document_number",
                        "label": standalone.group(0),
                        "value": standalone.group(0),
                        "label_cell_id": cell.get("id"),
                        "value_cell_id": cell.get("id"),
                        "label_coordinate": cell.get("coordinate"),
                        "value_coordinate": cell.get("coordinate"),
                        "reason": "deterministic_standalone_document_number",
                    }
                )
                existing_roles.add("document_number")
    return derived


def _fallback_plan(
    evidence: dict[str, Any],
    hinted_target_type: str,
    *,
    hint_confidence: float,
    degradation_code: str = "",
) -> dict[str, Any]:
    cell_index = evidence.get("cell_index") or {}
    documents: list[dict[str, Any]] = []
    candidates = evidence.get("table_candidates") or []
    for index, candidate in enumerate(candidates, start=1):
        sheet = str(candidate.get("sheet") or "")
        document_type, semantic_confidence, classification_reasons = _fallback_document_type(
            evidence,
            candidate,
            hinted_target_type,
            hint_confidence,
        )
        header_fields = []
        for item in evidence.get("key_value_candidates") or []:
            if item.get("sheet") != sheet:
                continue
            role = _best_role(item.get("label"), _HEADER_ROLE_HINTS)
            if not role:
                continue
            header_fields.append(
                {
                    "role": role,
                    "label": str(item.get("label") or "")[:160],
                    "value": item.get("value"),
                    "label_cell_id": item.get("label_cell_id"),
                    "value_cell_id": item.get("value_cell_id"),
                    "label_coordinate": (
                        cell_index.get(str(item.get("label_cell_id") or ""), {}).get("coordinate")
                    ),
                    "value_coordinate": (
                        cell_index.get(str(item.get("value_cell_id") or ""), {}).get("coordinate")
                    ),
                    "reason": "deterministic_key_value_candidate",
                }
            )
        header_fields.extend(
            _derived_header_fields(
                evidence,
                candidate,
                {str(item.get("role") or "") for item in header_fields},
            )
        )
        header_row = int(candidate.get("header_end_row") or 0)
        columns = []
        for column, header in enumerate(candidate.get("headers") or [], start=1):
            role = _best_role(header, _COLUMN_ROLE_HINTS)
            evidence_id = f"s{next((s['index'] for s in evidence.get('sheets') or [] if s.get('name') == sheet), 0)}:r{header_row}:c{column}"
            columns.append(
                {
                    "column": column,
                    "role": role or "other",
                    "header": str(header or "")[:160],
                    "header_cell_id": evidence_id if evidence_id in cell_index else "",
                    "header_coordinate": cell_index.get(evidence_id, {}).get("coordinate"),
                    "reason": "deterministic_table_candidate",
                }
            )
        documents.append(
            {
                "document_id": f"document-{index}",
                "document_type": document_type,
                "sheet": sheet,
                "title_cells": _title_cells(evidence, candidate, document_type),
                "header_fields": header_fields,
                "tables": [
                    {
                        "header_start_row": int(candidate.get("header_start_row") or header_row),
                        "header_end_row": header_row,
                        "data_start_row": int(candidate.get("data_start_row") or header_row + 1),
                        "data_end_row": int(candidate.get("data_end_row") or header_row + 1),
                        "first_column": int(candidate.get("first_column") or 1),
                        "last_column": int(candidate.get("last_column") or len(columns)),
                        "columns": columns,
                    }
                ],
                "total_amount_cell_id": "",
                "total_amount_coordinate": "",
                "total_amount": None,
                "confidence": max(
                    semantic_confidence,
                    float(candidate.get("confidence") or 0.0),
                ),
                "classification_reasons": classification_reasons,
                "requires_review": True,
                "issues": [
                    {
                        "code": "ETL_DOCUMENT_LLM_REVIEW_REQUIRED",
                        "message": {
                            "ETL_LLM_OUTPUT_INVALID": (
                                "LLM 已返回结果，但结构化输出未通过校验；"
                                "当前使用确定性候选，必须人工确认。"
                            ),
                            "ETL_LLM_QUOTA_EXHAUSTED": (
                                "LLM 额度不足，当前结构来自确定性降级候选，必须人工确认。"
                            ),
                        }.get(
                            degradation_code,
                            "LLM 不可用，当前结构来自确定性降级候选，必须人工确认。",
                        ),
                    }
                ],
            }
        )
    return {
        "file_structure": "one_per_sheet" if len(documents) > 1 else "single_document",
        "summary": "确定性结构候选，等待人工确认",
        "documents": documents,
    }


def _recommended_target(documents: list[dict[str, Any]], hinted_target_type: str) -> str:
    targets = {
        _DOCUMENT_TARGETS.get(str(document.get("document_type") or ""), "export_xlsx")
        for document in documents
        if str(document.get("document_type") or "") != "ignore"
    }
    if len(targets) == 1:
        target = next(iter(targets))
        if target == "products" and hinted_target_type == "customer_products":
            return "customer_products"
        return target
    if not targets:
        return hinted_target_type or "export_xlsx"
    return "export_xlsx"


def understand_workbook(
    path: str | Path,
    *,
    hinted_target_type: str,
    hint_confidence: float = 1.0,
    progress_callback: Callable[[int, int], None] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence or build_workbook_evidence(path)
    llm_result = advise_document_understanding(
        evidence,
        progress_callback=progress_callback,
    )
    plan = dict(llm_result.data or {})
    source = "llm"
    if not llm_result.used_llm or not plan.get("documents"):
        plan = _fallback_plan(
            evidence,
            hinted_target_type,
            hint_confidence=hint_confidence,
            degradation_code=llm_result.degradation_code,
        )
        source = "deterministic_fallback"
    elif llm_result.degraded:
        fallback = _fallback_plan(
            evidence,
            hinted_target_type,
            hint_confidence=hint_confidence,
            degradation_code=llm_result.degradation_code,
        )
        covered_sheets = {
            str(document.get("sheet") or "")
            for document in plan.get("documents") or []
            if isinstance(document, dict)
        }
        fallback_documents = [
            document
            for document in fallback.get("documents") or []
            if isinstance(document, dict)
            and str(document.get("sheet") or "") not in covered_sheets
        ]
        plan["documents"] = [
            *list(plan.get("documents") or []),
            *fallback_documents,
        ]
        plan["file_structure"] = "mixed_workbook"
        plan["summary"] = (
            f"{plan.get('summary') or '部分工作表已由模型识别'}；"
            f"{len(fallback_documents)} 个工作表使用确定性待确认候选。"
        )
        source = "hybrid"
    if source != "deterministic_fallback":
        covered_sheets = {
            str(document.get("sheet") or "")
            for document in plan.get("documents") or []
            if isinstance(document, dict)
        }
        fallback = _fallback_plan(
            evidence,
            hinted_target_type,
            hint_confidence=hint_confidence,
            degradation_code=llm_result.degradation_code,
        )
        fallback_by_sheet = {
            str(document.get("sheet") or ""): document
            for document in fallback.get("documents") or []
            if isinstance(document, dict)
        }
        missing_documents = []
        for sheet_index, sheet in enumerate(evidence.get("sheets") or [], start=1):
            sheet_name = str(sheet.get("name") or "")
            if not sheet_name or sheet_name in covered_sheets:
                continue
            has_cells = any(
                bool(row.get("cells"))
                for row in sheet.get("rows") or []
                if isinstance(row, dict)
            )
            if not has_cells:
                continue
            candidate = fallback_by_sheet.get(sheet_name)
            if candidate is None:
                candidate = {
                    "document_id": f"missing-sheet-{sheet_index}",
                    "document_type": "generic_table",
                    "sheet": sheet_name,
                    "title_cells": [],
                    "header_fields": [],
                    "tables": [],
                    "total_amount_cell_id": "",
                    "total_amount_coordinate": "",
                    "total_amount": None,
                    "confidence": 0.0,
                    "requires_review": True,
                    "issues": [
                        {
                            "code": "ETL_DOCUMENT_SHEET_UNCLASSIFIED",
                            "message": "模型未覆盖该工作表，已建立独立待确认路由。",
                        }
                    ],
                }
            else:
                candidate = {
                    **candidate,
                    "document_id": (
                        f"missing-sheet-{sheet_index}:"
                        f"{candidate.get('document_id') or sheet_name}"
                    )[:120],
                }
            missing_documents.append(candidate)
            covered_sheets.add(sheet_name)
        if missing_documents:
            plan["documents"] = [
                *list(plan.get("documents") or []),
                *missing_documents,
            ]
            plan["file_structure"] = "mixed_workbook"
            plan["summary"] = (
                f"{plan.get('summary') or '工作表识别完成'}；"
                f"补齐 {len(missing_documents)} 个模型遗漏的非空工作表。"
            )
            source = "hybrid"
    documents = list(plan.get("documents") or [])
    plan_hash = hashlib.sha256(
        json.dumps(
            {
                "evidence_hash": evidence.get("evidence_hash"),
                "file_structure": plan.get("file_structure"),
                "documents": documents,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    requires_review = (
        bool(evidence.get("truncated"))
        or source != "llm"
        or any(bool(document.get("requires_review")) for document in documents)
    )
    sheet_inventory = build_sheet_inventory(evidence, documents)
    result = {
        "version": 1,
        "source": source,
        "file_structure": str(plan.get("file_structure") or "unknown"),
        "summary": str(plan.get("summary") or "")[:1000],
        "recommended_target_type": _recommended_target(documents, hinted_target_type),
        "document_count": len(documents),
        "documents": documents,
        "sheet_inventory": sheet_inventory,
        "requires_confirmation": True,
        "requires_review": requires_review,
        "plan_hash": plan_hash,
        "evidence": public_evidence_summary(evidence),
        "llm": {
            **llm_result.public_metadata(),
            "semantic_primary": True,
            "write_authority": False,
        },
    }
    result["document_routes"] = build_document_routes(
        result,
        hinted_target_type=hinted_target_type,
    )
    return result


__all__ = ["understand_workbook"]
