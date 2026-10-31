"""Extract model-grouped documents from a previously validated classification result."""

import re

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range
from app.application.reviewed_excel_legacy import ensure_slice_workbook
from app.application.reviewed_excel_template import derive_document_workbook, inspect_workbook


def _slice_filename(fragments: list[dict], cells: list[dict], used: set[str]) -> str:
    title = ""
    for part in fragments:
        c1, r1, c2, r2 = bounded_range(part["range"])
        for cell in cells:
            if cell["sheet"] != part["sheet"]:
                continue
            col, row = coordinate_from_string(cell["cell"])
            value = cell["value"].strip()
            if (
                c1 <= column_index_from_string(col) <= c2
                and r1 <= row <= min(r2, r1 + 3)
                and len(value) <= 40
                and re.fullmatch(r"[\u4e00-\u9fff\w（）()\- ]*(?:单|表|清单|记录)", value)
            ):
                title = value
                break
        if title:
            break
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" ._")[:40] or "切片"
    if title.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        title = "切片"
    # At most len(used) candidate names can be occupied; the next one is free.
    # Keep the allocation explicitly bounded for review and denial-of-service safety.
    for number in range(1, len(used) + 2):
        name = f"{title}_{number}.xlsx" if title == "切片" or number > 1 else f"{title}.xlsx"
        if name.casefold() not in used:
            used.add(name.casefold())
            return name
    raise ReviewedExcelError("无法分配唯一切片文件名")


def derive_classified_documents(body: bytes, classification: dict) -> list[dict]:
    """Export only documents with explicit model grouping, without inferring missing groups.

    This internal function expects the output of classify_semantic_workbook, not
    arbitrary client data. It does not record user confirmation or modify the source.
    OLE/BIFF8 XLS bodies are converted to XLSX via ensure_slice_workbook before
    openpyxl load and document derivation.
    """
    body, _receipt = ensure_slice_workbook(body)
    source = inspect_workbook(body)
    if classification.get("source_sha256") != source["sha256"]:
        raise ReviewedExcelError("分类结果与原件不一致")
    if source.get("drawing_evidence"):
        from app.application.reviewed_excel_drawing import grouping_drawings

        coverage = classification.get("coverage", [])
        if len(coverage) != len(source["sheets"]) or any(
            row.get("drawing_unread")
            or row.get("drawing_unassigned")
            or row.get("unread")
            or row.get("unassigned")
            or row.get("merged_omitted")
            for row in coverage
        ):
            raise ReviewedExcelError("绘图证据覆盖不完整，暂不能裁切")
        grouping_drawings(source, classification.get("regions", []), [])
    if classification.get("model_status") != "returned":
        raise ReviewedExcelError("模型分类尚未返回")
    regions = classification.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ReviewedExcelError("没有可提取的模型区域")
    known = {}
    for region in regions:
        if region.get("open_fragment"):
            raise ReviewedExcelError("模型片段仍跨越未读边界，不能作为完整单据切片")
        key = (region["sheet"], region["range"])
        if key in known:
            raise ReviewedExcelError("模型区域重复")
        known[key] = region
    assigned = set()
    groups = []
    for document in classification.get("suggested_documents", []):
        fragments = document.get("fragments")
        if not isinstance(fragments, list) or not fragments:
            raise ReviewedExcelError("模型分组无片段")
        group = []
        for fragment in fragments:
            if not isinstance(fragment, dict) or set(fragment) != {"sheet", "range"}:
                raise ReviewedExcelError("模型分组片段无效")
            key = (fragment["sheet"], fragment["range"])
            if key not in known or key in assigned:
                raise ReviewedExcelError("模型分组片段来源无效或重复")
            assigned.add(key)
            group.append(dict(fragment))
        groups.append((group, "model_group"))
    if len(assigned) != len(known):
        raise ReviewedExcelError("模型尚未确定所有区域的独立单据关系，不能自动切片")
    results = []
    used_names: set[str] = set()
    for fragments, basis in groups:
        for fragment in fragments:
            region = known[(fragment["sheet"], fragment["range"])]
            for ref in region.get("dependencies", []):
                column, row = coordinate_from_string(ref["cell"])
                col = column_index_from_string(column)
                if not any(
                    ref["sheet"] == part["sheet"] and c1 <= col <= c2 and r1 <= row <= r2
                    for part in fragments
                    for c1, r1, c2, r2 in [bounded_range(part["range"])]
                ):
                    raise ReviewedExcelError("所选文档依赖外部说明或标题，暂不能保证保真提取")
        print_area_mode = "source"
        # Model grouping is not permission to change the source print layout.
        # Listing/downloading automatic slices must never silently choose selected.
        if source.get("drawing_evidence") and source.get("read_only_print_areas"):
            raise ReviewedExcelError("原打印区域无法安全映射，暂不能自动裁切")
        object_receipt: dict = {}
        output = derive_document_workbook(
            body, fragments, print_area_mode=print_area_mode, object_receipt=object_receipt
        )
        results.append(
            {
                "print_area_mode": print_area_mode,
                "range_objects_receipt": object_receipt,
                "fragments": fragments,
                "basis": basis,
                "confirmed": False,
                "source_sha256": source["sha256"],
                "filename": _slice_filename(fragments, source["cells"], used_names),
                "workbook": output,
            }
        )
    return results
