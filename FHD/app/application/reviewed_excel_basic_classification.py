"""Rule-based Excel workbook labeling, without model inference."""

from __future__ import annotations

from openpyxl.utils import get_column_letter

from app.application.reviewed_excel_evidence import bounded_range


def classify_review_workbook(review: dict) -> list[dict]:
    """Suggest non-exclusive document labels from inspected cell text only."""
    import re

    from openpyxl.utils.cell import coordinate_from_string

    from app.application.elt.target_detection import _ATTENDANCE_RE, _DELIVERY_RE, _PURCHASE_RE

    patterns = {
        "quotation": re.compile(r"报价|報價|quotation|sales quote", re.I),
        "delivery": _DELIVERY_RE,
        "purchase": _PURCHASE_RE,
        "attendance": _ATTENDANCE_RE,
    }
    results = []
    for sheet in review["sheets"]:
        cells = [cell for cell in review["cells"] if cell["sheet"] == sheet]
        evidence = []
        for label, pattern in patterns.items():
            for cell in cells:
                match = pattern.search(cell["value"])
                if match is not None:
                    evidence.append(
                        {"label": label, "cell": cell["cell"], "matched": match.group(0)}
                    )
                    break
        headings = {
            "quotation": re.compile(r"^(报价单|報價單|quotation|sales quote)$", re.I),
            "delivery": re.compile(r"^(送货单|发货单|出货单|delivery note)$", re.I),
            "purchase": re.compile(r"^(采购订单|purchase order)$", re.I),
            "attendance": re.compile(r"^(考勤表|attendance sheet)$", re.I),
        }
        anchors: dict[int, list[dict]] = {}
        for cell in cells:
            for label, pattern in headings.items():
                if pattern.fullmatch(cell["value"].strip()):
                    row = coordinate_from_string(cell["cell"])[1]
                    anchors.setdefault(row, []).append(
                        {"label": label, "cell": cell["cell"], "matched": cell["value"]}
                    )
        dimensions: dict = next(
            (item for item in review["sheet_overview"] if item["sheet"] == sheet), {}
        )
        max_row = max(1, int(dimensions.get("rows", 1)))
        max_col = max(1, int(dimensions.get("columns", 1)))
        merges = dimensions.get("merged_regions", [])
        section_headings = {
            "production": r"生产(?:任务|计划)?单|production (?:order|sheet)",
            "process": r"工艺(?:流程|说明|要求)?|工序(?:说明|要求)?|process(?: instructions?| sheet)?",
            "material": r"原(?:辅)?料(?:清单|明细)?|物料(?:清单|明细)|materials?(?: list)?|bill of materials",
            "inspection": r"检验(?:说明|要求|标准|记录|结果)?|质检(?:说明|要求|标准|记录)?|inspection(?: instructions?| standards?| report)?",
        }
        rows_of_cells: dict[int, list[dict]] = {}
        for cell in cells:
            rows_of_cells.setdefault(coordinate_from_string(cell["cell"])[1], []).append(cell)
        merged_titles = {
            f"{get_column_letter(c1)}{r1}"
            for c1, r1, c2, _r2 in map(bounded_range, merges)
            if c2 > c1
        }
        for cell in cells:
            column, row = coordinate_from_string(cell["cell"])
            merged_title = cell["cell"] in merged_titles
            sparse_title = (
                column == "A"
                and len(rows_of_cells[row]) == 1
                and any(
                    len(rows_of_cells.get(next_row, [])) >= 2 for next_row in (row + 1, row + 2)
                )
            )
            if cell.get("kind") == "formula" or not (merged_title or sparse_title):
                continue
            value = cell["value"].strip().rstrip(":：")
            for label, section_pattern in section_headings.items():
                if re.fullmatch(section_pattern, value, re.I):
                    item = {"label": label, "cell": cell["cell"], "matched": cell["value"]}
                    anchors.setdefault(row, []).append(item)
                    if not any(ref["label"] == label for ref in evidence):
                        evidence.append(item)
        rows = sorted(anchors)
        if (
            len(rows) > 1
            and {item["label"] for item in anchors[rows[0]]} == {"production"}
            and any(
                item["label"] in {"process", "material", "inspection"} for item in anchors[rows[1]]
            )
        ):
            # A workbook title remains in the first section, rather than becoming a title-only slice.
            rows = rows[1:]
        split = len(rows) > 1 and all(b - a >= 3 for a, b in zip(rows, rows[1:]))
        if split and any(
            min_row < boundary <= max_row_of_merge
            for merged in merges
            for _min_col, min_row, _max_col, max_row_of_merge in [bounded_range(merged)]
            for boundary in rows[1:]
        ):
            split = False
        possible_shared = [
            {"cell": cell["cell"], "kind": "可能的图例或说明，关联待确认"}
            for cell in cells
            if re.search(r"图例|圖例|legend|说明|說明|备注|備註", cell["value"], re.I)
        ]
        header_pattern = re.compile(
            r"^(产品名称|商品名称|品名|数量|单价|金额|合计|客户|供应商|姓名|日期|product|quantity|price|amount|customer|supplier|date)$",
            re.I,
        )
        boundaries = [1] + rows[1:] if split else [1]
        regions = []
        for index, start in enumerate(boundaries):
            end = boundaries[index + 1] - 1 if index + 1 < len(boundaries) else max_row
            region_cells = [
                cell for cell in cells if start <= coordinate_from_string(cell["cell"])[1] <= end
            ]
            region_evidence = [
                item for row, items in anchors.items() if start <= row <= end for item in items
            ]
            region_labels = list(dict.fromkeys(item["label"] for item in region_evidence)) or [
                "unknown"
            ]
            header_cells = [
                {"cell": cell["cell"], "value": cell["value"]}
                for cell in region_cells
                if header_pattern.fullmatch(cell["value"].strip())
            ]
            merged_in_region = []
            for merged in merges:
                _min_col, min_row, _max_col, max_row_of_merge = bounded_range(merged)
                if min_row <= end and max_row_of_merge >= start:
                    merged_in_region.append(merged)
            regions.append(
                {
                    "range": f"A{start}:{get_column_letter(max_col)}{end}",
                    "labels": region_labels,
                    "label_source": "rule",
                    "range_source": "rule",
                    "evidence": region_evidence,
                    "parent_heading": region_evidence[0]["matched"] if region_evidence else "",
                    "header_cells": header_cells,
                    "merged_ranges": merged_in_region,
                    "possible_shared_context": possible_shared,
                    "checked_cells": len(region_cells),
                    "needs_confirmation": True,
                    "dependency_status": "跨区图例和依赖未分析，边界需确认",
                }
            )
        hidden = dimensions.get("sheet_state", "visible") != "visible"
        blank = bool(dimensions.get("blank")) or not cells
        nonempty_cells = sum(len(items) for items in rows_of_cells.values())
        title_only = not blank and nonempty_cells == 1
        tables, notes = _split_table_blocks(rows_of_cells)
        if len(tables) >= 2:
            regions = _regions_for_blocks(
                sheet_cells=cells,
                rows_of_cells=rows_of_cells,
                tables=tables,
                notes=notes,
                max_col=max_col,
                merges=merges,
                header_pattern=header_pattern,
                possible_shared=possible_shared,
            )
        elif title_only and regions:
            regions = [
                {
                    **regions[0],
                    "data_region": False,
                    "anomaly": "title_only",
                    "anomaly_reason": "只有标题，没有数据行",
                }
            ]
        processable = (
            (not hidden)
            and (not blank)
            and (not title_only)
            and any(region.get("data_region", True) for region in regions)
        )
        if hidden:
            message = "隐藏工作表无法作为独立模板处理；请选择可见工作表。"
        elif blank:
            message = "空白工作表"
        elif title_only:
            message = "只有标题，不是数据区域"
        else:
            message = ""
        results.append(
            {
                "sheet": sheet,
                "sheet_state": dimensions.get("sheet_state", "visible"),
                "blank": blank,
                "processable": processable,
                "processing_message": message,
                "labels": [item["label"] for item in evidence] or ["unknown"],
                "evidence": evidence,
                "checked_cells": len(cells),
                "regions": [] if blank else regions,
            }
        )
    return results


def _split_table_blocks(
    rows_of_cells: dict[int, list[dict]],
) -> tuple[list[list[int]], list[list[int]]]:
    content_rows = sorted(rows_of_cells)
    blocks: list[list[int]] = []
    current: list[int] = []
    previous: int | None = None
    for row in content_rows:
        if previous is not None and row - previous > 1 and current:
            blocks.append(current)
            current = []
        current.append(row)
        previous = row
    if current:
        blocks.append(current)
    tables: list[list[int]] = []
    notes: list[list[int]] = []
    for block in blocks:
        while (
            len(block) >= 2
            and len(rows_of_cells[block[0]]) < 2
            and len(rows_of_cells[block[1]]) >= 2
        ):
            notes.append([block[0]])
            block = block[1:]
        header = rows_of_cells[block[0]]
        if len(block) >= 2 and len(header) >= 2:
            tables.append(block)
        else:
            notes.append(block)
    return tables, notes


def _regions_for_blocks(
    *,
    sheet_cells: list[dict],
    rows_of_cells: dict[int, list[dict]],
    tables: list[list[int]],
    notes: list[list[int]],
    max_col: int,
    merges: list,
    header_pattern,
    possible_shared: list[dict],
) -> list[dict]:
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    def span(rows: list[int]) -> tuple[int, int, int, int]:
        cols = [
            column_index_from_string(coordinate_from_string(cell["cell"])[0])
            for row in rows
            for cell in rows_of_cells[row]
        ]
        return min(cols), rows[0], max(cols), rows[-1]

    merge_bounds = [bounded_range(item) for item in merges]
    blocks = []
    for rows, data_region in (
        *[(item, False) for item in notes],
        *[(item, True) for item in tables],
    ):
        c1, r1, c2, r2 = span(rows)
        merged_title = False
        changed = True
        while changed:
            changed = False
            for m1, n1, m2, n2 in merge_bounds:
                if m1 <= c2 and c1 <= m2 and n1 <= r2 and r1 <= n2:
                    merged_title = merged_title or not data_region
                    grown = (min(c1, m1), min(r1, n1), max(c2, m2), max(r2, n2))
                    if grown != (c1, r1, c2, r2):
                        c1, r1, c2, r2 = grown
                        changed = True
        blocks.append([c1, r1, c2, r2, data_region, merged_title])
    blocks.sort(key=lambda item: (item[1], item[3]))
    joined: list[list] = []
    for block in blocks:
        # Rows are the slice unit: a merge-grown block sharing rows with its neighbour
        # becomes one region so no row is covered twice, and a merged title directly
        # above a table stays with that table as its context.
        last = joined[-1] if joined else None
        if last is not None and (
            block[1] <= last[3]
            or (last[5] and not last[4] and block[4] and block[1] == last[3] + 1)
        ):
            last[0], last[2] = min(last[0], block[0]), max(last[2], block[2])
            last[3] = max(last[3], block[3])
            last[4] = last[4] or block[4]
            last[5] = last[5] and not last[4]
        else:
            joined.append(block)
    regions = []
    for c1, r1, c2, r2, data_region, _merged_title in joined:
        anomaly = "" if data_region else "title_or_note"
        merged_in_region = [
            item
            for item, (m1, n1, m2, n2) in zip(merges, merge_bounds)
            if c1 <= m1 and m2 <= c2 and r1 <= n1 and n2 <= r2
        ]
        region_cells = [
            cell for cell in sheet_cells if r1 <= coordinate_from_string(cell["cell"])[1] <= r2
        ]
        regions.append(
            {
                "range": f"{get_column_letter(c1)}{r1}:{get_column_letter(min(c2, max_col))}{r2}",
                "labels": ["unknown"],
                "label_source": "rule",
                "range_source": "rule",
                "evidence": [],
                "parent_heading": "",
                "header_cells": [
                    {"cell": cell["cell"], "value": cell["value"]}
                    for cell in region_cells
                    if header_pattern.fullmatch(str(cell["value"]).strip())
                ],
                "merged_ranges": merged_in_region,
                "possible_shared_context": possible_shared,
                "checked_cells": len(region_cells),
                "needs_confirmation": True,
                "dependency_status": "跨区图例和依赖未分析，边界需确认",
                "data_region": data_region,
                "anomaly": anomaly,
                "anomaly_reason": "标题或说明，不是数据表" if anomaly else "",
            }
        )
    return regions
