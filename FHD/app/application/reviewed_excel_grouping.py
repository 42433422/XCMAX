"""Bounded second-stage grouping of fully covered model fragments."""

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range


def prepare_grouping(review: dict, classification: dict) -> dict:
    """Build a bounded evidence index; never infer relationships from coordinates alone."""
    if review["sha256"] != classification.get("source_sha256"):
        raise ReviewedExcelError("分组来源与原件不一致")
    coverage = classification.get("coverage", [])
    if len(coverage) != len(review["sheets"]) or any(
        row.get("unread") or row.get("unassigned") or row.get("merged_omitted") for row in coverage
    ):
        raise ReviewedExcelError("文件覆盖不完整，不能进行最终分组")
    regions = classification.get("regions", [])
    if not 1 <= len(regions) <= 100:
        raise ReviewedExcelError("分组区域数量超过本轮安全预算")
    source_cells = review["cells"]
    chosen = {}
    fragments = []
    for region in regions:
        sheet, area = region["sheet"], region["range"]
        c1, r1, c2, r2 = bounded_range(area)
        inside = []
        for cell in source_cells:
            if cell["sheet"] != sheet:
                continue
            col, row = coordinate_from_string(cell["cell"])
            if c1 <= column_index_from_string(col) <= c2 and r1 <= row <= r2:
                inside.append(cell)
        if not inside:
            raise ReviewedExcelError("分组片段没有已读内容")
        evidence = {(ref["sheet"], ref["cell"]) for ref in region.get("evidence", [])}
        selected = [
            inside[0],
            inside[-1],
            *(c for c in inside if (c["sheet"], c["cell"]) in evidence),
        ]
        for cell in selected:
            if len(cell["value"]) > 4000:
                raise ReviewedExcelError("分组证据单格超出安全预算")
            chosen[(cell["sheet"], cell["cell"])] = {
                k: cell[k] for k in ("sheet", "cell", "value", "kind")
            }
        fragments.append(
            {
                "sheet": sheet,
                "range": area,
                "labels": region["labels"],
                "reason": region.get("reason", "")[:1000],
            }
        )
    cells = list(chosen.values())
    if len(cells) > 500 or sum(len(c["value"].encode("utf-8")) + 64 for c in cells) > 96_000:
        raise ReviewedExcelError("分组证据超过本轮安全预算")
    return {"source_sha256": review["sha256"], "fragments": fragments, "cells": cells}


def validate_grouping(group_input: dict, data: dict) -> list[dict]:
    """Validate all model group references and require evidence in every fragment."""
    if (
        not isinstance(data, dict)
        or set(data) != {"groups"}
        or not isinstance(data["groups"], list)
        or len(data["groups"]) > 100
    ):
        raise ReviewedExcelError("模型分组结构无效")
    regions = {(r["sheet"], r["range"]) for r in group_input["fragments"]}
    cells = {(c["sheet"], c["cell"]) for c in group_input["cells"]}
    assigned = set()
    ids = set()
    result = []
    for group in data["groups"]:
        if not isinstance(group, dict) or set(group) != {
            "document_id",
            "fragments",
            "evidence",
            "reason",
        }:
            raise ReviewedExcelError("模型分组结构无效")
        docid = group["document_id"]
        parts = group["fragments"]
        evidence = group["evidence"]
        if (
            not isinstance(docid, str)
            or not docid.strip()
            or len(docid) > 80
            or docid in ids
            or not isinstance(group["reason"], str)
            or not group["reason"].strip()
        ):
            raise ReviewedExcelError("模型分组编号或理由无效")
        if (
            not isinstance(parts, list)
            or not 1 <= len(parts) <= 20
            or not isinstance(evidence, list)
            or not evidence
            or len(evidence) > 100
        ):
            raise ReviewedExcelError("模型分组片段或证据无效")
        ids.add(docid)
        refs = []
        for part in parts:
            if not isinstance(part, dict) or set(part) != {"sheet", "range"}:
                raise ReviewedExcelError("模型分组片段无效")
            key = (part["sheet"], part["range"])
            if key not in regions or key in assigned:
                raise ReviewedExcelError("模型分组片段来源无效或重复")
            assigned.add(key)
            refs.append(dict(part))
        validated = []
        for ref in evidence:
            if (
                not isinstance(ref, dict)
                or set(ref) != {"sheet", "cell"}
                or (ref["sheet"], ref["cell"]) not in cells
            ):
                raise ReviewedExcelError("模型分组证据不在已发送范围")
            validated.append(ref)
        for part in refs:
            c1, r1, c2, r2 = bounded_range(part["range"])
            if not any(
                ref["sheet"] == part["sheet"]
                and c1 <= column_index_from_string(coordinate_from_string(ref["cell"])[0]) <= c2
                and r1 <= coordinate_from_string(ref["cell"])[1] <= r2
                for ref in validated
            ):
                raise ReviewedExcelError("模型分组缺少片段内证据")
        result.append(
            {
                "document_id": docid,
                "fragments": refs,
                "evidence": validated,
                "reason": group["reason"],
                "status": "model_suggested",
            }
        )
    return result


def group_semantic_fragments(
    review: dict, classification: dict, *, prepare_only=False
) -> list[dict]:
    """Ask the configured model to group only fully read, validated fragments."""
    import json

    from app.application.reviewed_excel_template import _template_mimo_complete

    group_input = prepare_grouping(review, classification)
    cell = {
        "type": "object",
        "required": ["sheet", "cell"],
        "additionalProperties": False,
        "properties": {"sheet": {"type": "string"}, "cell": {"type": "string"}},
    }
    part = {
        "type": "object",
        "required": ["sheet", "range"],
        "additionalProperties": False,
        "properties": {"sheet": {"type": "string"}, "range": {"type": "string"}},
    }
    group = {
        "type": "object",
        "required": ["document_id", "fragments", "evidence", "reason"],
        "additionalProperties": False,
        "properties": {
            "document_id": {"type": "string"},
            "fragments": {"type": "array", "minItems": 1, "maxItems": 20, "items": part},
            "evidence": {"type": "array", "minItems": 1, "maxItems": 100, "items": cell},
            "reason": {"type": "string"},
        },
    }
    schema = {
        "type": "object",
        "required": ["groups"],
        "additionalProperties": False,
        "properties": {"groups": {"type": "array", "maxItems": 100, "items": group}},
    }
    messages = [
        {
            "role": "system",
            "content": "Group only fragments that belong to the same business document. "
            "A standalone fragment can be one group. Do not group merely because fragments are adjacent, "
            "have similar headers, or share a category. Leave uncertain fragments ungrouped. "
            "For every grouped fragment cite at least one sent cell within it and explain the relationship "
            "using sent values. Fragment boundaries are fixed; do not invent ranges or cells. "
            "Return exactly one JSON object matching output_schema.",
        },
        {
            "role": "user",
            "content": json.dumps({"output_schema": schema, **group_input}, ensure_ascii=False),
        },
    ]
    if sum(len(message["content"].encode("utf-8")) for message in messages) > 180_000:
        raise ReviewedExcelError("分组请求超过安全预算，未调用模型")
    if prepare_only:
        return []
    response = _template_mimo_complete(messages, schema, 4000)
    return validate_grouping(group_input, response.data)
