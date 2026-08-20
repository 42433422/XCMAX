"""Excel-specific detection and template argument enrichment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def detected_excel_header_row_1based(
    excel_analysis: Any,
    *,
    preferred_sheet_name: str | None = None,
) -> int | None:
    if not isinstance(excel_analysis, dict):
        return None

    def _from_tables(tables: Any) -> int | None:
        if not isinstance(tables, list) or not tables or not isinstance(tables[0], dict):
            return None
        value = tables[0].get("header_row")
        try:
            row = int(value) if value is not None else 0
        except (TypeError, ValueError):
            return None
        return row if row >= 1 else None

    def _from_sheet_entry(sheet: Any) -> int | None:
        if not isinstance(sheet, dict):
            return None
        grid = sheet.get("grid_preview")
        if isinstance(grid, dict):
            value = grid.get("header_row_index")
            try:
                row = int(value) if value is not None else 0
            except (TypeError, ValueError):
                row = 0
            if row >= 1:
                return row
        return _from_tables(sheet.get("tables"))

    preferred = (preferred_sheet_name or "").strip()
    if preferred:
        sheets = excel_analysis.get("sheets")
        if isinstance(sheets, list):
            for sheet in sheets:
                if (
                    isinstance(sheet, dict)
                    and str(sheet.get("sheet_name") or "").strip() == preferred
                ):
                    hit = _from_sheet_entry(sheet)
                    if hit is not None:
                        return hit
        preview = excel_analysis.get("preview_data")
        if isinstance(preview, dict):
            all_sheets = preview.get("all_sheets")
            if isinstance(all_sheets, list):
                for sheet in all_sheets:
                    if (
                        isinstance(sheet, dict)
                        and str(sheet.get("sheet_name") or "").strip() == preferred
                    ):
                        hit = _from_sheet_entry(sheet)
                        if hit is not None:
                            return hit

    preview = excel_analysis.get("preview_data")
    if isinstance(preview, dict):
        grid = preview.get("grid_preview")
        if isinstance(grid, dict):
            value = grid.get("header_row_index")
            try:
                row = int(value) if value is not None else 0
            except (TypeError, ValueError):
                row = 0
            if row >= 1:
                return row
        hit = _from_tables(preview.get("tables"))
        if hit is not None:
            return hit
    sheets = excel_analysis.get("sheets")
    if isinstance(sheets, list) and sheets and isinstance(sheets[0], dict):
        return _from_sheet_entry(sheets[0])
    return None


def excel_analysis_from_runtime(
    runtime_context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not runtime_context:
        return None
    analysis = runtime_context.get("excel_analysis")
    if isinstance(analysis, dict):
        return analysis
    last = runtime_context.get("last_excel_analysis_context")
    if isinstance(last, dict):
        nested = last.get("excel_analysis")
        return nested if isinstance(nested, dict) else last
    return None


def enrich_template_preview_arguments(
    args: dict[str, Any],
    runtime_context: Mapping[str, Any] | None,
    *,
    header_detector: Callable[..., int | None] = detected_excel_header_row_1based,
) -> dict[str, Any]:
    output = dict(args or {})
    analysis = excel_analysis_from_runtime(runtime_context)
    if not analysis:
        return output
    context_path = (
        str(analysis.get("file_path") or "").strip()
        or str((analysis.get("preview_data") or {}).get("file_path") or "").strip()
    )
    if context_path and not str(output.get("file_path") or "").strip():
        output["file_path"] = context_path
    if not str(output.get("sheet_name") or "").strip() and runtime_context:
        selected = runtime_context.get("excel_analysis_selected_sheet")
        if isinstance(selected, dict) and str(selected.get("sheet_name") or "").strip():
            output["sheet_name"] = str(selected.get("sheet_name")).strip()
        elif str(runtime_context.get("preferred_sheet_name") or "").strip():
            output["sheet_name"] = str(runtime_context.get("preferred_sheet_name")).strip()
    if not str(output.get("sheet_name") or "").strip():
        sheets = analysis.get("sheets")
        if isinstance(sheets, list) and sheets and isinstance(sheets[0], dict):
            first_name = str(sheets[0].get("sheet_name") or "").strip()
            if first_name:
                output["sheet_name"] = first_name
    sheet = str(output.get("sheet_name") or "").strip() or None
    header_row = header_detector(analysis, preferred_sheet_name=sheet)
    if header_row is not None and output.get("header_row") in (None, ""):
        output["header_row"] = header_row
    if sheet and not str(output.get("template_name") or "").strip():
        output["template_name"] = f"{sheet}-模板"
    customer = str(analysis.get("customer_hint") or "").strip()
    preview = analysis.get("preview_data")
    if not customer and isinstance(preview, dict):
        customer = str(preview.get("customer_hint") or "").strip()
    if customer and not str(output.get("unit_name") or "").strip():
        output["unit_name"] = customer
    return output
