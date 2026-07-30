"""Evidence-bound document advice and cache sharing."""

from __future__ import annotations

from typing import Any, Callable

from app.application.etl.llm_document_evidence import (
    _DOCUMENT_SCHEMA,
    _compact_document_evidence,
    _document_evidence_batches,
    _document_prompt_messages,
    _resolved_inline_value,
)
from app.utils.mixin_module_sync import sync_module_functions


def _merged_file_structure(
    structures: list[str],
    *,
    sheet_count: int,
    document_count: int,
) -> str:
    if "mixed_workbook" in structures:
        return "mixed_workbook"
    if document_count == 1:
        return "single_document"
    if document_count == sheet_count and sheet_count > 1:
        return "one_per_sheet"
    if document_count > sheet_count:
        return "multiple_sections"
    if document_count > 1:
        return "mixed_workbook"
    return "unknown"


def _advise_document_understanding_uncached(
    evidence: dict[str, Any],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> LlmAssistResult:
    """Build a business-document plan whose references are all server-verifiable."""

    sheets = list(evidence.get("sheets") or [])
    cell_index = evidence.get("cell_index") or {}
    if not sheets or not cell_index:
        return LlmAssistResult()
    batches = _document_evidence_batches(evidence)
    batch_results: list[LlmAssistResult] = []
    raw_documents: list[dict[str, Any]] = []
    batch_structures: list[str] = []
    for batch_index, batch in enumerate(batches, start=1):
        logger.info(
            "general etl document understanding batch %s/%s sheets=%s",
            batch_index,
            len(batches),
            len(batch.get("sheets") or []),
        )
        batch_result = _complete(
            _document_prompt_messages(
                batch,
                batch_index=batch_index,
                batch_count=len(batches),
            ),
            schema=_DOCUMENT_SCHEMA,
            max_tokens=5000,
            timeout_seconds=etl_document_timeout_seconds(batch),
            # Document structure is the semantic primary stage. A single
            # schema-repair attempt is cheaper and safer than degrading every
            # Sheet because one model response missed the contract.
            max_repairs=1,
        )
        batch_results.append(batch_result)
        if not batch_result.degraded:
            raw_documents.extend(
                item
                for item in list(batch_result.data.get("documents") or [])
                if isinstance(item, dict)
            )
            batch_structures.append(str(batch_result.data.get("file_structure") or ""))
        if progress_callback is not None:
            progress_callback(batch_index, len(batches))
    result = LlmAssistResult(
        used_llm=any(item.used_llm for item in batch_results),
        degraded=any(item.degraded for item in batch_results),
        degradation_code=next(
            (item.degradation_code for item in batch_results if item.degradation_code),
            "",
        ),
        model=next((item.model for item in batch_results if item.model), ""),
        billing={
            "batch_count": len(batch_results),
            "batches": [item.billing for item in batch_results if item.billing],
        },
        data={
            "file_structure": _merged_file_structure(
                batch_structures,
                sheet_count=len(sheets),
                document_count=len(raw_documents),
            ),
            "summary": "",
            "documents": raw_documents,
        },
    )
    valid_sheets = {str(sheet.get("name") or ""): sheet for sheet in evidence.get("sheets") or []}
    normalized_documents: list[dict[str, Any]] = []
    seen_document_ids: set[str] = set()
    for raw_document in list(result.data.get("documents") or [])[:80]:
        if not isinstance(raw_document, dict):
            continue
        document_id = str(raw_document.get("document_id") or "")[:120]
        document_type = str(raw_document.get("document_type") or "")
        sheet_name = str(raw_document.get("sheet") or "")
        if (
            not document_id
            or document_type not in _DOCUMENT_TYPES
            or sheet_name not in valid_sheets
        ):
            continue
        if document_id in seen_document_ids:
            document_id = f"{sheet_name}:{document_id}"[:120]
        if document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        sheet = valid_sheets[sheet_name]
        max_row = int(sheet.get("max_row") or 0)
        max_column = int(sheet.get("max_column") or 0)
        title_cells = [
            cell_index[cell_id]
            for cell_id in list(raw_document.get("title_cell_ids") or [])[:10]
            if cell_id in cell_index and cell_index[cell_id].get("sheet") == sheet_name
        ]
        header_fields = []
        for raw_field in list(raw_document.get("header_fields") or [])[:80]:
            if not isinstance(raw_field, dict):
                continue
            role = str(raw_field.get("role") or "")
            label_id = str(raw_field.get("label_cell_id") or "")
            value_id = str(raw_field.get("value_cell_id") or "")
            label_item = cell_index.get(label_id)
            value_item = cell_index.get(value_id)
            if (
                role not in _HEADER_FIELD_ROLES
                or not label_item
                or not value_item
                or label_item.get("sheet") != sheet_name
                or value_item.get("sheet") != sheet_name
            ):
                continue
            header_fields.append(
                {
                    "role": role,
                    "label": str(label_item.get("text") or "")[:160],
                    "value": _resolved_inline_value(
                        label_item,
                        value_item,
                        role=role,
                    ),
                    "label_cell_id": label_id,
                    "value_cell_id": value_id,
                    "label_coordinate": label_item.get("coordinate"),
                    "value_coordinate": value_item.get("coordinate"),
                    "reason": _localized_model_text(
                        raw_field.get("reason"),
                        "模型根据单元格标签、位置和样例判定该字段。",
                    )[:300],
                }
            )
        inferred_roles = (
            "document_number",
            "date",
            "supplier",
            "customer",
            "currency",
            "contact",
            "phone",
        )
        existing_roles = {
            str(item.get("role") or "") for item in header_fields if isinstance(item, dict)
        }
        referenced_items = []
        seen_item_ids = set()
        for item in header_fields:
            for key in ("label_cell_id", "value_cell_id"):
                cell_id = str(item.get(key) or "")
                cell_item = cell_index.get(cell_id)
                if (
                    cell_item
                    and cell_item.get("sheet") == sheet_name
                    and cell_id not in seen_item_ids
                ):
                    seen_item_ids.add(cell_id)
                    referenced_items.append(cell_item)
        for inferred_role in inferred_roles:
            if inferred_role in existing_roles:
                continue
            for cell_item in referenced_items:
                cell_text = str(cell_item.get("text") or "")
                inferred_value = normalize_header_role_value(
                    inferred_role,
                    cell_item.get("value"),
                    label=cell_text,
                )
                if (
                    inferred_value in (None, "")
                    or str(inferred_value).strip() == str(cell_item.get("value") or "").strip()
                ):
                    continue
                header_fields.append(
                    {
                        "role": inferred_role,
                        "label": cell_text[:160],
                        "value": inferred_value,
                        "label_cell_id": cell_item.get("id"),
                        "value_cell_id": cell_item.get("id"),
                        "label_coordinate": cell_item.get("coordinate"),
                        "value_coordinate": cell_item.get("coordinate"),
                        "reason": "由同一单据头单元格中的明确标签确定性补全。",
                    }
                )
                existing_roles.add(inferred_role)
                break
        tables = []
        for raw_table in list(raw_document.get("tables") or [])[:20]:
            if not isinstance(raw_table, dict):
                continue
            try:
                header_start = int(raw_table.get("header_start_row"))
                header_end = int(raw_table.get("header_end_row"))
                data_start = int(raw_table.get("data_start_row"))
                data_end = int(raw_table.get("data_end_row"))
                first_column = int(raw_table.get("first_column"))
                last_column = int(raw_table.get("last_column"))
            except (TypeError, ValueError):
                continue
            if not (
                1 <= header_start <= header_end < data_start <= data_end <= max_row
                and 1 <= first_column <= last_column <= max_column
            ):
                continue
            columns = []
            for raw_column in list(raw_table.get("columns") or [])[:80]:
                if not isinstance(raw_column, dict):
                    continue
                try:
                    column = int(raw_column.get("column"))
                except (TypeError, ValueError):
                    continue
                role = str(raw_column.get("role") or "")
                header_id = str(raw_column.get("header_cell_id") or "")
                header_item = cell_index.get(header_id)
                if (
                    role not in _COLUMN_ROLES
                    or column < first_column
                    or column > last_column
                    or not header_item
                    or header_item.get("sheet") != sheet_name
                    or int(header_item.get("row") or 0) < header_start
                    or int(header_item.get("row") or 0) > header_end
                    or int(header_item.get("column") or 0) != column
                ):
                    continue
                columns.append(
                    {
                        "column": column,
                        "role": role,
                        "header": str(header_item.get("text") or "")[:160],
                        "header_cell_id": header_id,
                        "header_coordinate": header_item.get("coordinate"),
                        "reason": _localized_model_text(
                            raw_column.get("reason"),
                            "模型根据表头、数据类型和列值关系判定该字段。",
                        )[:300],
                    }
                )
            tables.append(
                {
                    "header_start_row": header_start,
                    "header_end_row": header_end,
                    "data_start_row": data_start,
                    "data_end_row": data_end,
                    "first_column": first_column,
                    "last_column": last_column,
                    "columns": columns,
                }
            )
        total_id = str(raw_document.get("total_amount_cell_id") or "")
        total_item = cell_index.get(total_id)
        if not total_item or total_item.get("sheet") != sheet_name:
            total_id = ""
            total_item = {}
        try:
            confidence = min(1.0, max(0.0, float(raw_document.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        normalized_documents.append(
            {
                "document_id": document_id,
                "document_type": document_type,
                "sheet": sheet_name,
                "title_cells": [
                    {
                        "cell_id": item.get("id"),
                        "coordinate": item.get("coordinate"),
                        "text": item.get("text"),
                    }
                    for item in title_cells
                ],
                "header_fields": header_fields,
                "tables": tables,
                "total_amount_cell_id": total_id,
                "total_amount_coordinate": total_item.get("coordinate", ""),
                "total_amount": total_item.get("value"),
                "confidence": confidence,
                "requires_review": bool(raw_document.get("requires_review")) or not tables,
                "issues": [
                    {
                        "code": "ETL_DOCUMENT_UNDERSTANDING_REVIEW",
                        "message": _localized_model_text(
                            issue,
                            "模型发现单据结构存在需要人工确认的问题，请结合来源单元格复核。",
                        )[:500],
                    }
                    for issue in list(raw_document.get("issues") or [])[:20]
                    if str(issue).strip()
                ],
            }
        )
    file_structure = str(result.data.get("file_structure") or "")
    result.data = {
        "file_structure": file_structure if file_structure in _FILE_STRUCTURES else "unknown",
        "summary": _document_summary_text(
            result.data.get("summary"),
            normalized_documents,
        ),
        "documents": normalized_documents,
    }
    return result


def advise_document_understanding(
    evidence: dict[str, Any],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> LlmAssistResult:
    """Share one successful semantic analysis across linked target previews."""

    if not evidence.get("sheets") or not evidence.get("cell_index"):
        return LlmAssistResult()
    cache_key = _document_cache_key(evidence)
    cached = _cached_document_result(cache_key)
    if cached is not None:
        if progress_callback is not None:
            batch_count = max(1, int(cached.billing.get("batch_count") or 1))
            progress_callback(batch_count, batch_count)
        logger.info(
            "general etl document understanding cache hit evidence=%s",
            cache_key.rsplit("|", 1)[-1][:12],
        )
        return cached
    with _document_flight_lock(cache_key):
        cached = _cached_document_result(cache_key)
        if cached is not None:
            if progress_callback is not None:
                batch_count = max(1, int(cached.billing.get("batch_count") or 1))
                progress_callback(batch_count, batch_count)
            logger.info(
                "general etl document understanding shared result evidence=%s",
                cache_key.rsplit("|", 1)[-1][:12],
            )
            return cached
        result = _advise_document_understanding_uncached(
            evidence,
            progress_callback=progress_callback,
        )
        if result.used_llm and not result.degraded and result.data.get("documents"):
            _cache_document_result(cache_key, result)
        return result


sync_module_functions(
    target=globals(),
    source_module="app.application.etl.llm_assist",
    function_names=(
        "_merged_file_structure",
        "_advise_document_understanding_uncached",
        "advise_document_understanding",
    ),
)
