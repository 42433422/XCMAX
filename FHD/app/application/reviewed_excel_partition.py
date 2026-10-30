"""Manual workbook partition geometry and reviewed classification corrections."""

from __future__ import annotations

from openpyxl.utils import get_column_letter

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range

DOCUMENT_LABELS = frozenset(
    {
        "quotation",
        "delivery",
        "purchase",
        "attendance",
        "production",
        "process",
        "material",
        "inspection",
        "template",
        "unknown",
    }
)


def apply_classification_corrections(review: dict, latest: dict, labels: list) -> dict:
    """Validate user corrections against source geometry, preserving shared context conservatively."""
    from copy import deepcopy

    expected = {
        (sheet["sheet"], region["range"]): region
        for sheet in latest["sheets"]
        for region in sheet["regions"]
    }
    supplied: dict[tuple[str, str], list[dict]] = {}
    from openpyxl.utils.cell import (
        column_index_from_string,
        coordinate_from_string,
    )

    dimensions = {sheet["sheet"]: sheet for sheet in review["sheet_overview"]}
    rectangles: dict[str, list[tuple[int, int, int, int]]] = {}
    limit = max(200, len(expected))
    if not isinstance(labels, list) or len(labels) > limit:
        raise ReviewedExcelError(f"分类区域数量无效，最多{limit}个片段")
    for item in labels:
        if (
            not isinstance(item, dict)
            or set(item)
            not in ({"sheet", "range", "labels"}, {"sheet", "original_range", "range", "labels"})
            or not isinstance(item["sheet"], str)
            or not isinstance(item["range"], str)
            or ("original_range" in item and not isinstance(item["original_range"], str))
            or not isinstance(item["labels"], list)
            or not item["labels"]
            or any(
                not isinstance(label, str) or label not in DOCUMENT_LABELS
                for label in item["labels"]
            )
            or len(set(item["labels"])) != len(item["labels"])
            or ("unknown" in item["labels"] and len(item["labels"]) > 1)
        ):
            raise ReviewedExcelError("分类修正无效")
        key = (item["sheet"], item.get("original_range", item["range"]))
        if key not in expected:
            raise ReviewedExcelError("分类区域不属于该版本")
        try:
            c1, r1, c2, r2 = bounded_range(item["range"])
            size = dimensions[item["sheet"]]
            if not all(isinstance(x, int) for x in (c1, r1, c2, r2)) or not (
                1 <= c1 <= c2 <= size["columns"] and 1 <= r1 <= r2 <= size["rows"]
            ):
                raise ReviewedExcelError("bounds")
        except (ValueError, TypeError, KeyError):
            raise ReviewedExcelError("分类区域越界") from None
        for oc1, or1, oc2, or2 in rectangles.setdefault(item["sheet"], []):
            if c1 <= oc2 and oc1 <= c2 and r1 <= or2 and or1 <= r2:
                raise ReviewedExcelError("分类区域重叠")
        rectangles[item["sheet"]].append((c1, r1, c2, r2))
        for merged in size.get("merged_regions", []):
            mc1, mr1, mc2, mr2 = bounded_range(merged)
            if (
                c1 <= mc2
                and mc1 <= c2
                and r1 <= mr2
                and mr1 <= r2
                and not (c1 <= mc1 <= mc2 <= c2 and r1 <= mr1 <= mr2 <= r2)
            ):
                raise ReviewedExcelError("分类区域切断合并单元格")
        supplied.setdefault(key, []).append(item)
    if set(supplied) != set(expected):
        raise ReviewedExcelError("分类区域不完整")
    partition_changed = False
    corrected: dict[str, list[dict]] = {sheet["sheet"]: [] for sheet in latest["sheets"]}
    for key, original in expected.items():
        children = supplied[key]
        if len(children) > 1:
            partition_changed = True
            c1, r1, c2, r2 = bounded_range(original["range"])
            area = 0
            for child in children:
                sc1, sr1, sc2, sr2 = bounded_range(child["range"])
                if not (c1 <= sc1 <= sc2 <= c2 and r1 <= sr1 <= sr2 <= r2):
                    raise ReviewedExcelError("拆分片段必须位于原区域内")
                area += (sc2 - sc1 + 1) * (sr2 - sr1 + 1)
            # All final rectangles were checked for overlap above; equal area proves no holes.
            if area != (c2 - c1 + 1) * (r2 - r1 + 1):
                raise ReviewedExcelError("拆分必须完整覆盖原区域，不能遗漏行列")
        for item in children:
            region = deepcopy(original)
            if region["labels"] != item["labels"]:
                region["label_source"] = "user"
            region["labels"] = item["labels"]
            c1, r1, c2, r2 = bounded_range(item["range"])
            region["range"] = f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}"
            for field in ("original_range", "modified"):
                region.pop(field, None)
            if original["range"] != region["range"]:
                region["range_source"] = "user"

                def in_region(ref):
                    col, row = coordinate_from_string(ref["cell"])
                    return (
                        ref.get("sheet", key[0]) == key[0]
                        and c1 <= column_index_from_string(col) <= c2
                        and r1 <= row <= r2
                    )

                region["evidence"] = [ref for ref in original["evidence"] if in_region(ref)]
                region["header_cells"] = [ref for ref in original["header_cells"] if in_region(ref)]
                region["checked_cells"] = sum(
                    in_region(cell) for cell in review["cells"] if cell["sheet"] == key[0]
                )
                region["merged_ranges"] = [
                    merged
                    for merged in dimensions[key[0]].get("merged_regions", [])
                    for mc1, mr1, mc2, mr2 in [bounded_range(merged)]
                    if c1 <= mc1 <= mc2 <= c2 and r1 <= mr1 <= mr2 <= r2
                ]
                region.pop("continuation_context", None)
                region.pop("value_extent", None)
                region["parent_heading"] = ""
                region["dependency_status"] = "用户修改边界；共享说明和依赖需重新确认"
                region["needs_confirmation"] = True
            corrected[key[0]].append(region)
    for sheet in latest["sheets"]:
        sheet["regions"] = corrected[sheet["sheet"]]
        sheet["labels"] = list(
            dict.fromkeys(label for region in sheet["regions"] for label in region["labels"])
        )
    latest["partition_pending"] = partition_changed
    for coverage in latest.get("coverage", []):
        name = coverage["sheet"]
        coverage.setdefault("model_unassigned", list(coverage["unassigned"]))
        coverage["unassigned"] = []
        for cell in (cell for cell in review["cells"] if cell["sheet"] == name):
            col, row = coordinate_from_string(cell["cell"])
            number = column_index_from_string(col)
            if not any(
                c1 <= number <= c2 and r1 <= row <= r2
                for c1, r1, c2, r2 in rectangles.get(name, [])
            ):
                coverage["unassigned"].append(cell["cell"])
    return latest
