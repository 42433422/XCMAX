"""Attach auditable OCR evidence to parsed ETL rows."""

from __future__ import annotations

from typing import Any

from app.application.etl.parser_structure import clean_cell_text
from app.application.etl.parser_types import ParsedDataset

OCR_REVIEW_CONFIDENCE = 0.8


def _normalized_confidence(evidence: dict[str, Any]) -> float | None:
    raw = evidence.get("confidence", evidence.get("score"))
    confidence = float(raw) if isinstance(raw, (int, float)) else None
    if confidence is not None and confidence > 1:
        confidence /= 100
    return confidence


def enrich_ocr_provenance(
    dataset: ParsedDataset,
    result: dict[str, Any],
    *,
    source_suffix: str,
) -> ParsedDataset:
    dataset.source_features.update(
        {
            "kind": "ocr",
            "source_suffix": source_suffix,
            "ocr_block_count": int(result.get("block_count") or 0),
            "ocr_meta_lines": list(result.get("meta_lines") or []),
            "ocr_page_count": len(result.get("pages") or []),
        }
    )
    page_by_sheet = {str(page.get("sheet_name") or ""): page for page in result.get("pages") or []}
    for item in dataset.rows:
        page = page_by_sheet.get(item.sheet, {})
        evidence_by_cell = {
            (
                int(cell.get("workbook_row") or 0),
                int(cell.get("workbook_column") or 0),
            ): cell
            for cell in page.get("grid_cells") or []
            if cell.get("workbook_row") and cell.get("workbook_column")
        }
        columns = item.provenance.get("columns") or {}
        cell_evidence: dict[str, Any] = {}
        low_confidence_fields: list[str] = []
        confidences: list[float] = []
        for field_name, value in item.values.items():
            text = str(value or "").strip()
            if not text:
                continue
            column = int(columns.get(field_name) or 0)
            evidence = evidence_by_cell.get((item.row_number, column))
            if evidence is None:
                evidence = next(
                    (
                        block
                        for block in page.get("blocks") or []
                        if text == clean_cell_text(block.get("text"))
                    ),
                    None,
                )
            if not evidence:
                low_confidence_fields.append(field_name)
                cell_evidence[field_name] = {
                    "page": page.get("page_number") or 1,
                    "original_text": text,
                    "confidence": None,
                }
                continue
            confidence = _normalized_confidence(evidence)
            if confidence is not None:
                confidences.append(confidence)
            if confidence is None or confidence < OCR_REVIEW_CONFIDENCE:
                low_confidence_fields.append(field_name)
            cell_evidence[field_name] = {
                "page": page.get("page_number") or 1,
                "original_text": str(evidence.get("text") or text),
                "confidence": confidence,
                "position": {
                    key: evidence.get(key)
                    for key in ("left", "top", "width", "height", "center")
                    if evidence.get(key) is not None
                },
            }
        item.provenance.update(
            {
                "page": page.get("page_number") or 1,
                "table_position": {
                    "sheet": item.sheet,
                    "row": item.row_number,
                    "data_start_row": page.get("data_start_row"),
                    "columns": columns,
                },
                "ocr": True,
                "confidence": min(confidences) if confidences else None,
                "low_confidence_fields": sorted(set(low_confidence_fields)),
                "cells": cell_evidence,
                "requires_confirmation": True,
            }
        )
    dataset.warnings.append(
        {
            "code": "ETL_OCR_REVIEW_REQUIRED",
            "message": "OCR 行必须人工复核；无法取得置信度的单元格不会静默写入。",
        }
    )
    return dataset


__all__ = ["OCR_REVIEW_CONFIDENCE", "enrich_ocr_provenance"]
