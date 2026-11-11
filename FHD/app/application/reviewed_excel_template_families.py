"""Ask the configured model which source documents can share a template.

Families describe template reuse only; the source documents remain separate.
"""

from __future__ import annotations

import json
from io import BytesIO
from xml.etree.ElementTree import tostring

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range
from app.application.reviewed_excel_io_lock import serialize_workbook_io
from app.application.reviewed_excel_template import (
    _template_llm_complete,
    _validate_template_schema,
)


@serialize_workbook_io
def _collect_evidence(
    slices: list[dict], cells: list[dict], source_body: bytes | None
) -> list[dict]:
    evidence = []
    workbook = load_workbook(BytesIO(source_body), data_only=False) if source_body else None
    try:
        for index, item in enumerate(slices):
            fragments = item.get("fragments") or []
            selected, merges, layout = [], [], []
            text_truncated = False
            for part in fragments:
                c1, r1, c2, r2 = bounded_range(part["range"])
                sheet = workbook[part["sheet"]] if workbook else None
                if sheet is not None:
                    layout.append(
                        {
                            "defaults": tostring(sheet.sheet_format.to_tree(), encoding="unicode"),
                            "columns": [
                                [
                                    max(c1, left) - c1,
                                    min(c2, right) - c1,
                                    dim.width,
                                    dim.hidden,
                                    dim.style,
                                ]
                                for name, dim in sheet.column_dimensions.items()
                                for left, right in [
                                    (
                                        dim.min or column_index_from_string(name),
                                        dim.max or column_index_from_string(name),
                                    )
                                ]
                                if left <= c2 and right >= c1
                            ],
                            "rows": [
                                [row - r1, dim.height, dim.hidden, dim.style]
                                for row, dim in sheet.row_dimensions.items()
                                if r1 <= row <= r2
                            ],
                            "styles": sorted(
                                [row - r1, col - c1, cell.style_id]
                                for (row, col), cell in sheet._cells.items()
                                if r1 <= row <= r2 and c1 <= col <= c2 and cell.has_style
                            ),
                            "print": [
                                tostring(part.to_tree(), encoding="unicode")
                                for part in (
                                    sheet.page_setup,
                                    sheet.page_margins,
                                    sheet.print_options,
                                    sheet.HeaderFooter,
                                    sheet.row_breaks,
                                    sheet.col_breaks,
                                )
                            ],
                            "print_ranges": [
                                str(sheet.print_area),
                                sheet.print_title_rows,
                                sheet.print_title_cols,
                            ],
                        }
                    )
                    for merged in sheet.merged_cells.ranges:
                        if (
                            c1 <= merged.min_col <= merged.max_col <= c2
                            and r1 <= merged.min_row <= merged.max_row <= r2
                        ):
                            merges.append(
                                [
                                    merged.min_row - r1,
                                    merged.min_col - c1,
                                    merged.max_row - r1,
                                    merged.max_col - c1,
                                ]
                            )
                for cell in cells:
                    if cell.get("sheet") != part["sheet"]:
                        continue
                    column_name, row = coordinate_from_string(cell["cell"])
                    col = column_index_from_string(column_name)
                    if c1 <= col <= c2 and r1 <= row <= r2:
                        value = str(cell.get("value") or "")
                        text_truncated = text_truncated or len(value) > 60
                        selected.append(
                            {
                                "row": row - r1,
                                "column": col - c1,
                                "value": value[:60],
                                "kind": cell.get("kind"),
                                "style": sheet.cell(row, col).style_id
                                if sheet is not None
                                else None,
                            }
                        )
            evidence.append(
                {
                    "index": index,
                    "fragments": fragments,
                    "type": item.get("type_label", ""),
                    "cells": selected[:120],
                    "merged": merges,
                    "layout_available": workbook is not None,
                    "layout": layout,
                    "truncated": len(selected) > 120 or text_truncated,
                }
            )
    finally:
        if workbook is not None:
            workbook.close()
    return evidence


def suggest_template_families(
    slices: list[dict],
    cells: list[dict],
    *,
    owner_id: int,
    source_body: bytes | None = None,
    on_dispatch=None,
    on_answer=None,
) -> list[dict]:
    """Return a complete, non-overlapping partition of source slice indexes."""
    if not slices:
        return []
    if len(slices) > 100:
        raise ReviewedExcelError("文档过多，模板复用关系待核对")
    evidence = _collect_evidence(slices, cells, source_body)
    schema = {
        "type": "object",
        "required": ["families"],
        "additionalProperties": False,
        "properties": {
            "families": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["members", "reason"],
                    "additionalProperties": False,
                    "properties": {
                        "members": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "integer", "minimum": 0, "maximum": len(slices) - 1},
                        },
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }
    payload = json.dumps(
        {"output_schema": schema, "documents": evidence}, ensure_ascii=False, separators=(",", ":")
    )
    if len(payload) > 150_000:
        raise ReviewedExcelError("模板复用证据超出模型处理范围，请分批核对")
    messages = [
        {
            "role": "system",
            "content": "判断哪些原始单据可复用同一空白模板，而不是合并业务数据。仅在版式、固定标题和字段结构有充分证据一致时分为一组；名称相同、相邻或业务类型相同不足以证明一致。证据不足、内容截断或单据残缺时单独分组。每个 index 必须恰好出现一次。只返回符合 schema 的 JSON。",
        },
        {"role": "user", "content": payload},
    ]
    if on_dispatch:
        on_dispatch()
    answer = _template_llm_complete(messages, schema, 4096, owner_id=owner_id)
    if on_answer:
        on_answer()
    if not _validate_template_schema(schema, answer.data):
        raise ReviewedExcelError("模型模板复用结果格式无效")
    groups = answer.data["families"]
    members = [index for group in groups for index in group["members"]]
    if (
        any(type(index) is not int for index in members)
        or len(members) != len(slices)
        or set(members) != set(range(len(slices)))
    ):
        raise ReviewedExcelError("模型模板复用结果遗漏或重复文档")
    if any(
        len(group["members"]) > 1
        and any(
            evidence[index]["truncated"]
            or not evidence[index]["cells"]
            or not evidence[index]["layout_available"]
            for index in group["members"]
        )
        for group in groups
    ):
        raise ReviewedExcelError("模板复用证据不完整，不能合并")
    from app.application.reviewed_excel_template_blocks import merge_same_layout_families

    groups = merge_same_layout_families(groups, evidence)
    return [{"members": group["members"], "reason": group["reason"][:1000]} for group in groups]
