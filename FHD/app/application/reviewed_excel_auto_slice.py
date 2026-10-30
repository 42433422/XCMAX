"""Extract tentative documents from a previously validated classification result."""

import re

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range
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
    number = 1
    while True:
        name = f"{title}_{number}.xlsx" if title == "切片" or number > 1 else f"{title}.xlsx"
        if name.casefold() not in used:
            used.add(name.casefold())
            return name
        number += 1


def derive_classified_documents(body: bytes, classification: dict) -> list[dict]:
    """Use model groups where available; expose ungrouped regions as uncertain slices.

    This internal function expects the output of classify_semantic_workbook, not
    arbitrary client data. It does not record user confirmation or modify the source.
    """
    source = inspect_workbook(body)
    if classification.get("source_sha256") != source["sha256"]:
        raise ReviewedExcelError("分类结果与原件不一致")
    if classification.get("model_status") != "returned":
        raise ReviewedExcelError("模型分类尚未返回")
    regions = classification.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ReviewedExcelError("没有可提取的模型区域")
    known = {}
    for region in regions:
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
    groups.extend(
        ([{"sheet": sheet, "range": area}], "ungrouped_region")
        for sheet, area in known
        if (sheet, area) not in assigned
    )
    results = []
    used_names: set[str] = set()
    for fragments, basis in groups:
        for fragment in fragments:
            region = known[(fragment["sheet"], fragment["range"])]
            for ref in region.get("dependencies", []):
                col, row = coordinate_from_string(ref["cell"])
                col = column_index_from_string(col)
                if not any(
                    ref["sheet"] == part["sheet"] and c1 <= col <= c2 and r1 <= row <= r2
                    for part in fragments
                    for c1, r1, c2, r2 in [bounded_range(part["range"])]
                ):
                    raise ReviewedExcelError("所选文档依赖外部说明或标题，暂不能保证保真提取")
        output = derive_document_workbook(body, fragments)
        results.append(
            {
                "fragments": fragments,
                "basis": basis,
                "confirmed": False,
                "source_sha256": source["sha256"],
                "filename": _slice_filename(fragments, source["cells"], used_names),
                "workbook": output,
            }
        )
    return results
