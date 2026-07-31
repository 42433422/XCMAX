"""Evidence-bound document understanding for structured business workbooks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from app.application.etl.document_fallback import _fallback_plan
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
            if isinstance(document, dict) and str(document.get("sheet") or "") not in covered_sheets
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
                bool(row.get("cells")) for row in sheet.get("rows") or [] if isinstance(row, dict)
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
                        f"missing-sheet-{sheet_index}:{candidate.get('document_id') or sheet_name}"
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
