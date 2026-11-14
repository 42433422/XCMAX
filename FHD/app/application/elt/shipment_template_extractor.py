"""Extract one clean, reusable delivery-note layout from a mixed workbook."""

from __future__ import annotations

from copy import copy
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter

from app.application.elt.errors import EltError
from app.application.elt.parser_structure import clean_cell_text, semantic_key
from app.application.shipment_excel_elt_security import (
    open_elt_output_file,
    resolve_elt_output_path,
    resolve_elt_path,
)


def _last_nonempty_row(worksheet: Any, start: int, end: int, last_col: int) -> int:
    for row in range(end, start - 1, -1):
        if any(
            clean_cell_text(worksheet.cell(row=row, column=column).value)
            for column in range(1, last_col + 1)
        ):
            return row
    return start


def _template_bounds(
    regions: list[dict[str, Any]],
    *,
    source_region_id: str | None = None,
) -> tuple[dict[str, Any], int, int]:
    """Choose one explicitly selected delivery-note region.

    A workbook can carry several historical delivery-note layouts.  The
    caller may supply the audited region id selected in the ETL preview; when
    it does, never silently substitute the first layout on a different
    customer/document.  Legacy callers omit it and retain the deterministic
    first-region behaviour.
    """

    selected = [row for row in regions if row.get("status") == "selected"]
    requested = str(source_region_id or "").strip()
    if requested:
        # 显式指定区段时允许取任意状态（例如未选入业务导入、但仍要进模板库的区段）。
        region = next(
            (row for row in regions if str(row.get("id") or "") == requested),
            None,
        )
        if region is None:
            raise EltError(
                "ELT_SHIPMENT_TEMPLATE_REGION_NOT_FOUND",
                "所选发货单版式不在当前预演中，请重新选择",
                status_code=409,
            )
    else:
        if not selected:
            raise EltError("ELT_SHIPMENT_TEMPLATE_REGION_MISSING", "未识别到可提取的送货单版式")
        region = sorted(
            selected,
            key=lambda row: (str(row.get("sheet")), int(row.get("header_row") or 0)),
        )[0]
    header_row = int(region.get("header_row") or 0)
    evidence_rows = [
        int(item.get("row") or 0)
        for item in region.get("evidence_rows") or []
        if isinstance(item, dict) and int(item.get("row") or 0) > 0
    ]
    start = min(evidence_rows) if evidence_rows else max(1, header_row - 2)
    next_starts = [
        max(1, int(item.get("header_row") or 0) - 2)
        for item in regions
        if str(item.get("sheet") or "") == str(region.get("sheet") or "")
        and int(item.get("header_row") or 0) > header_row
    ]
    end_limit = min(next_starts) - 1 if next_starts else 0
    return region, start, end_limit


def _copy_sheet_region(
    source: Any,
    *,
    start_row: int,
    end_row: int,
    last_col: int,
    title: str = "送货单",
) -> Workbook:
    output = Workbook()
    target = output.active
    assert target is not None
    target.title = str(title or "送货单")[:31]
    for source_row in range(start_row, end_row + 1):
        target_row = source_row - start_row + 1
        target.row_dimensions[target_row].height = source.row_dimensions[source_row].height
        target.row_dimensions[target_row].hidden = source.row_dimensions[source_row].hidden
        for column in range(1, last_col + 1):
            src = source.cell(row=source_row, column=column)
            dst = target.cell(row=target_row, column=column, value=src.value)
            if src.has_style:
                dst.font = copy(src.font)
                dst.fill = copy(src.fill)
                dst.border = copy(src.border)
                dst.number_format = src.number_format
                dst.alignment = copy(src.alignment)
                dst.protection = copy(src.protection)
    for column in range(1, last_col + 1):
        letter = get_column_letter(column)
        target.column_dimensions[letter].width = source.column_dimensions[letter].width
        target.column_dimensions[letter].hidden = source.column_dimensions[letter].hidden
    for merged in source.merged_cells.ranges:
        if merged.min_row >= start_row and merged.max_row <= end_row and merged.max_col <= last_col:
            target.merge_cells(
                start_row=merged.min_row - start_row + 1,
                end_row=merged.max_row - start_row + 1,
                start_column=merged.min_col,
                end_column=merged.max_col,
            )
    target.page_margins = copy(source.page_margins)
    target.page_setup = copy(source.page_setup)
    target.print_options = copy(source.print_options)
    target.sheet_properties = copy(source.sheet_properties)
    target.freeze_panes = source.freeze_panes
    target.print_area = f"A1:{get_column_letter(last_col)}{end_row - start_row + 1}"
    return output


_TOTAL_LABELS = {"合计", "总计", "小计", "汇总", "大写人民币"}


def _clear_example_lines(
    worksheet: Any, *, header_row: int, last_col: int, require_total: bool = True
) -> None:
    total_row = 0
    for row in range(header_row + 1, worksheet.max_row + 1):
        values = [
            clean_cell_text(worksheet.cell(row=row, column=column).value)
            for column in range(1, last_col + 1)
        ]
        if semantic_key(" ".join(values)) in _TOTAL_LABELS:
            total_row = row
            break
        if any(semantic_key(value) in _TOTAL_LABELS for value in values):
            total_row = row
            break
    if not total_row:
        if require_total:
            raise EltError("ELT_SHIPMENT_TEMPLATE_TOTAL_MISSING", "送货单版式缺少合计行")
        # 数据型表没有合计行：清空表头之后的全部示例行，只保留表头结构。
        total_row = worksheet.max_row + 1
    for row in range(header_row + 1, total_row):
        for column in range(1, last_col + 1):
            cell = worksheet.cell(row=row, column=column)
            if not isinstance(cell, MergedCell):
                cell.value = None


def _slice_region(
    source_path: str | Path,
    *,
    source_features: dict[str, Any],
    source_region_id: str | None = None,
    clear_example_rows: bool = True,
    require_total: bool = True,
) -> tuple[Workbook, dict[str, Any]]:
    """把预演识别出的一个区段切出来，返回独立工作簿与区段元数据。"""
    regions = [item for item in source_features.get("regions") or [] if isinstance(item, dict)]
    region, start_row, end_limit = _template_bounds(
        regions,
        source_region_id=source_region_id,
    )
    workbook = load_workbook(resolve_elt_path(source_path), data_only=False, keep_links=False)
    try:
        sheet_name = str(region.get("sheet") or "")
        if sheet_name not in workbook.sheetnames:
            raise EltError("ELT_SHIPMENT_TEMPLATE_SHEET_MISSING", "送货单版式所在工作表不存在")
        source = workbook[sheet_name]
        last_col = int(region.get("last_column") or source.max_column)
        end_row = end_limit or source.max_row
        end_row = _last_nonempty_row(source, start_row, end_row, last_col)
        output = _copy_sheet_region(
            source,
            start_row=start_row,
            end_row=end_row,
            last_col=last_col,
            title=sheet_name,
        )
    finally:
        workbook.close()
    header_row = max(1, int(region.get("header_row") or 0) - start_row + 1)
    headerless = bool(region.get("headerless"))
    # 无表头流水区段本身就是模板内容，不能按「表头 + 空数据行」清空。
    if clear_example_rows and not headerless:
        _clear_example_lines(
            output.active,
            header_row=header_row,
            last_col=last_col,
            require_total=require_total,
        )
    return output, {
        "sheet": sheet_name,
        "source_region_id": region.get("id"),
        "header_row": header_row,
        "headerless": headerless,
        "rows": end_row - start_row + 1,
        "columns": last_col,
        "title": "" if headerless else _region_title(output.active, header_row, last_col),
        "headers": [
            str(header).strip() for header in (region.get("headers") or []) if str(header or "").strip()
        ],
        "customer_name": str(region.get("customer_name") or "").strip(),
    }


def _region_title(worksheet: Any, header_row: int, last_col: int) -> str:
    """取区段表头上方第一行有内容的文本，作为模板区分名（如「2025年3月报价」）。"""
    for row in range(1, header_row):
        values = [
            clean_cell_text(worksheet.cell(row=row, column=column).value)
            for column in range(1, last_col + 1)
        ]
        text = " ".join(value for value in values if value).strip()
        if text:
            return text[:60]
    return ""


def extract_region_template(
    source_path: str | Path,
    *,
    source_features: dict[str, Any],
    destination: str | Path,
    source_region_id: str | None = None,
    clear_example_rows: bool = False,
    require_total: bool = False,
) -> dict[str, Any]:
    """把区段切分成独立文件，供模板库登记。

    与 ``extract_shipment_template`` 共用同一套沙箱：来源必须是受管上传目录，
    目标必须是受管的租户模板目录；非发货单目标保留示例行，便于模板库预览。
    """
    output, meta = _slice_region(
        source_path,
        source_features=source_features,
        source_region_id=source_region_id,
        clear_example_rows=clear_example_rows,
        require_total=require_total,
    )
    try:
        destination_path = resolve_elt_output_path(destination)
        with open_elt_output_file(destination_path) as output_file:
            output.save(output_file)
    finally:
        output.close()
    return {"file_path": str(destination_path), **meta}


def extract_shipment_template(
    source_path: str | Path,
    *,
    source_features: dict[str, Any],
    destination: str | Path,
    source_region_id: str | None = None,
) -> dict[str, Any]:
    output, meta = _slice_region(
        source_path,
        source_features=source_features,
        source_region_id=source_region_id,
    )
    destination_path = resolve_elt_output_path(destination)
    with open_elt_output_file(destination_path) as output_file:
        output.save(output_file)
    output.close()
    return {"file_path": str(destination_path), **meta}


__all__ = ["extract_region_template", "extract_shipment_template"]
