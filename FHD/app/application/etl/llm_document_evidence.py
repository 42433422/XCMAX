"""Evidence compaction and prompt construction for document understanding."""

from __future__ import annotations

from typing import Any

from app.utils.mixin_module_sync import sync_module_functions

_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["file_structure", "summary", "documents"],
    "properties": {
        "file_structure": {"type": "string"},
        "summary": {"type": "string"},
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "document_id",
                    "document_type",
                    "sheet",
                    "title_cell_ids",
                    "header_fields",
                    "tables",
                    "total_amount_cell_id",
                    "confidence",
                    "requires_review",
                    "issues",
                ],
                "properties": {
                    "document_id": {"type": "string"},
                    "document_type": {"type": "string"},
                    "sheet": {"type": "string"},
                    "title_cell_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "header_fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "role",
                                "label_cell_id",
                                "value_cell_id",
                                "reason",
                            ],
                            "properties": {
                                "role": {"type": "string"},
                                "label_cell_id": {"type": "string"},
                                "value_cell_id": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "tables": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "header_start_row",
                                "header_end_row",
                                "data_start_row",
                                "data_end_row",
                                "first_column",
                                "last_column",
                                "columns",
                            ],
                            "properties": {
                                "header_start_row": {"type": "integer"},
                                "header_end_row": {"type": "integer"},
                                "data_start_row": {"type": "integer"},
                                "data_end_row": {"type": "integer"},
                                "first_column": {"type": "integer"},
                                "last_column": {"type": "integer"},
                                "columns": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": [
                                            "column",
                                            "role",
                                            "header_cell_id",
                                            "reason",
                                        ],
                                        "properties": {
                                            "column": {"type": "integer"},
                                            "role": {"type": "string"},
                                            "header_cell_id": {"type": "string"},
                                            "reason": {"type": "string"},
                                        },
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                    "total_amount_cell_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "requires_review": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def _resolved_inline_value(
    label_item: dict[str, Any],
    value_item: dict[str, Any],
    *,
    role: str = "",
) -> Any:
    value = value_item.get("value")
    if label_item.get("id") != value_item.get("id"):
        return normalize_header_role_value(
            role,
            value,
            label=label_item.get("text"),
        )
    text = str(value_item.get("text") or "")
    return normalize_header_role_value(role, value, label=text)


def _compact_document_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep every sheet visible while removing prompt-shape duplication."""

    sheets = list(evidence.get("sheets") or [])
    if not sheets:
        return {"cell_legend": ["cell_id", "text", "value_type"], "sheets": []}
    global_cell_budget = 960
    per_sheet_budget = min(160, max(48, global_cell_budget // len(sheets)))
    table_by_sheet = {
        str(item.get("sheet") or ""): item
        for item in evidence.get("table_candidates") or []
        if isinstance(item, dict)
    }
    compact_sheets: list[dict[str, Any]] = []
    supplied_cell_ids: set[str] = set()
    for sheet in sheets:
        sheet_name = str(sheet.get("name") or "")[:160]
        rows = list(sheet.get("rows") or [])
        candidate = table_by_sheet.get(sheet_name) or {}
        header_end = int(candidate.get("header_end_row") or 0)
        data_start = int(candidate.get("data_start_row") or header_end + 1)
        priority_rows: list[int] = []
        priority_rows.extend(
            int(row.get("row") or 0)
            for row in rows
            if int(row.get("row") or 0) <= max(header_end, 6)
        )
        priority_rows.extend(range(data_start, data_start + 3))
        priority_rows.extend(
            int(row.get("row") or 0)
            for row in rows
            if any(
                marker
                in " ".join(str(cell.get("text") or "").lower() for cell in row.get("cells") or [])
                for marker in ("合计", "总计", "小计", "备注", "total", "subtotal", "remark")
            )
        )
        priority_rows.extend(int(row.get("row") or 0) for row in rows[-2:])
        priority_rows.extend(int(row.get("row") or 0) for row in rows)
        row_by_number = {int(row.get("row") or 0): row for row in rows}
        selected_rows: dict[int, list[list[str]]] = {}
        used_cells = 0
        for row_number in dict.fromkeys(priority_rows):
            row = row_by_number.get(row_number)
            if row is None or used_cells >= per_sheet_budget:
                continue
            compact_cells: list[list[str]] = []
            for cell in row.get("cells") or []:
                if used_cells >= per_sheet_budget:
                    break
                cell_id = str(cell.get("id") or "")
                if not cell_id:
                    continue
                compact_cells.append(
                    [
                        cell_id,
                        str(cell.get("text") or "")[:300],
                        str(cell.get("value_type") or ""),
                    ]
                )
                supplied_cell_ids.add(cell_id)
                used_cells += 1
            if compact_cells:
                selected_rows[row_number] = compact_cells
        compact_sheets.append(
            {
                "name": sheet_name,
                "size": [
                    int(sheet.get("max_row") or 0),
                    int(sheet.get("max_column") or 0),
                ],
                "rows": [
                    [row_number, selected_rows[row_number]] for row_number in sorted(selected_rows)
                ],
            }
        )

    compact_tables = [
        [
            str(item.get("candidate_id") or ""),
            str(item.get("sheet") or ""),
            int(item.get("header_start_row") or 0),
            int(item.get("header_end_row") or 0),
            int(item.get("data_start_row") or 0),
            int(item.get("data_end_row") or 0),
            int(item.get("first_column") or 0),
            int(item.get("last_column") or 0),
            list(item.get("headers") or []),
            round(float(item.get("confidence") or 0.0), 3),
        ]
        for item in evidence.get("table_candidates") or []
        if isinstance(item, dict)
    ]
    key_value_counts: dict[str, int] = {}
    compact_key_values = []
    for item in evidence.get("key_value_candidates") or []:
        if not isinstance(item, dict):
            continue
        sheet_name = str(item.get("sheet") or "")
        if key_value_counts.get(sheet_name, 0) >= 16:
            continue
        label_id = str(item.get("label_cell_id") or "")
        value_id = str(item.get("value_cell_id") or "")
        # Candidate IDs are evidence too; prefer those also visible in the
        # compact row sample and keep a small per-sheet allowance otherwise.
        if (
            label_id not in supplied_cell_ids
            and value_id not in supplied_cell_ids
            and key_value_counts.get(sheet_name, 0) >= 8
        ):
            continue
        compact_key_values.append(
            [
                sheet_name,
                str(item.get("label") or "")[:120],
                item.get("value"),
                label_id,
                value_id,
            ]
        )
        key_value_counts[sheet_name] = key_value_counts.get(sheet_name, 0) + 1
    return {
        "cell_legend": ["cell_id", "text", "value_type"],
        "sheet_legend": ["row_number", "cells"],
        "table_candidate_legend": [
            "candidate_id",
            "sheet",
            "header_start",
            "header_end",
            "data_start",
            "data_end",
            "first_column",
            "last_column",
            "headers",
            "confidence",
        ],
        "key_value_legend": ["sheet", "label", "value", "label_cell_id", "value_cell_id"],
        "sheets": compact_sheets,
        "table_candidates": compact_tables,
        "key_value_candidates": compact_key_values,
    }


def _document_evidence_batches(
    evidence: dict[str, Any],
    *,
    batch_size: int = 4,
) -> list[dict[str, Any]]:
    """Split large workbooks by sheet so model output cannot truncate globally."""

    sheets = list(evidence.get("sheets") or [])
    if len(sheets) <= batch_size:
        return [evidence]
    batches: list[dict[str, Any]] = []
    for offset in range(0, len(sheets), batch_size):
        batch_sheets = sheets[offset : offset + batch_size]
        sheet_names = {str(sheet.get("name") or "") for sheet in batch_sheets}
        batches.append(
            {
                **evidence,
                "sheets": batch_sheets,
                "cell_index": {
                    cell_id: item
                    for cell_id, item in (evidence.get("cell_index") or {}).items()
                    if str(item.get("sheet") or "") in sheet_names
                },
                "table_candidates": [
                    item
                    for item in evidence.get("table_candidates") or []
                    if str(item.get("sheet") or "") in sheet_names
                ],
                "key_value_candidates": [
                    item
                    for item in evidence.get("key_value_candidates") or []
                    if str(item.get("sheet") or "") in sheet_names
                ],
            }
        )
    return batches


def _document_prompt_messages(
    evidence: dict[str, Any],
    *,
    batch_index: int,
    batch_count: int,
) -> list[dict[str, str]]:
    compact_evidence = _compact_document_evidence(evidence)
    return [
        {
            "role": "system",
            "content": (
                "You are the primary semantic document-understanding stage of an enterprise ETL. "
                "Analyze every supplied sheet as a human operator would: identify business objects, "
                "count separate documents, locate document headers, detail-table boundaries, totals "
                "and notes, and assign semantic column roles using labels, types, examples, positions "
                "and relationships. Return JSON only. Every cell reference must be an exact supplied "
                "cell ID. Never invent a cell, value, document, row range or database match. Mark "
                "ambiguity and mixed meanings as requires_review. For ignore or summary-only sheets, "
                "use empty header_fields and tables instead of describing every column. All "
                "human-readable summary, issue and reason fields must use Simplified Chinese; enum "
                "identifiers and cell IDs must retain their allowed values."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "understand_business_workbook_batch",
                    "file_name": str(evidence.get("file_name") or "")[:240],
                    "batch": {"index": batch_index, "count": batch_count},
                    "allowed_file_structures": sorted(_FILE_STRUCTURES),
                    "allowed_document_types": sorted(_DOCUMENT_TYPES),
                    "allowed_header_roles": sorted(_HEADER_FIELD_ROLES),
                    "allowed_column_roles": sorted(_COLUMN_ROLES),
                    "rules": [
                        "Find every independent document, including multiple sections on one sheet.",
                        "A summary sheet is not a line-item document unless it contains its own records.",
                        "Separate document header fields from detail-table columns.",
                        "Exclude totals, signatures and notes from data row ranges when possible.",
                        "Use requires_review when business type, boundary or field meaning is ambiguous.",
                        "Do not decide database writes or master-data matches.",
                    ],
                    "evidence_format": (
                        "Compact arrays use the supplied legends. Cell IDs encode sheet, row "
                        "and column; use those exact IDs in every output reference."
                    ),
                    "workbook_evidence": compact_evidence,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


sync_module_functions(
    target=globals(),
    source_module="app.application.etl.llm_assist",
    function_names=(
        "_resolved_inline_value",
        "_compact_document_evidence",
        "_document_evidence_batches",
        "_document_prompt_messages",
    ),
)
