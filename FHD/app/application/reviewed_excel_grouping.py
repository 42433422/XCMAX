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
        row.get("unread")
        or row.get("unassigned")
        or row.get("merged_omitted")
        or row.get("drawing_unread")
        or row.get("drawing_unassigned")
        for row in coverage
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
                "reason": region.get("reason", "")[:1000],
            }
        )
    cells = list(chosen.values())
    if len(cells) > 500 or sum(len(c["value"].encode("utf-8")) + 64 for c in cells) > 96_000:
        raise ReviewedExcelError("分组证据超过本轮安全预算")
    output = {"source_sha256": review["sha256"], "fragments": fragments, "cells": cells}
    if review.get("drawing_evidence"):
        from app.application.reviewed_excel_drawing import grouping_drawings

        output["drawing_evidence"] = grouping_drawings(review, fragments, cells)
    return output


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
        } | ({"drawing_evidence"} if group_input.get("drawing_evidence") else set()):
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
        if group_input.get("drawing_evidence"):
            from app.application.reviewed_excel_drawing import validate_group_drawings

            validate_group_drawings(group_input, group)
        result.append(
            {
                **(
                    {"drawing_evidence": group["drawing_evidence"]}
                    if group_input.get("drawing_evidence")
                    else {}
                ),
                "document_id": docid,
                "fragments": refs,
                "evidence": validated,
                "reason": group["reason"],
                "status": "model_suggested",
            }
        )
    return result


def group_semantic_fragments(
    review: dict, classification: dict, *, prepare_only=False, expected_request_sha256=None
) -> list[dict] | dict:
    """Ask the configured model to group only fully read, validated fragments."""
    import json

    from app.application.reviewed_excel_template import (
        _template_mimo_complete,
        _validate_template_schema,
    )

    group_input = prepare_grouping(review, classification)
    fragments = {f"R{i:04d}": part for i, part in enumerate(group_input["fragments"], 1)}
    cells = {f"E{i:04d}": cell for i, cell in enumerate(group_input["cells"], 1)}
    drawings = {
        f"D{i:04d}": obj for i, obj in enumerate(group_input.get("drawing_evidence", []), 1)
    }
    shown = {
        **group_input,
        "fragments": [{**part, "region_id": key} for key, part in fragments.items()],
        "cells": [{**cell, "evidence_id": key} for key, cell in cells.items()],
    }
    if drawings:
        shown["drawing_evidence"] = [{**obj, "drawing_id": key} for key, obj in drawings.items()]
    group = {
        "type": "object",
        "required": ["document_id", "fragment_ids", "evidence_ids", "reason"],
        "additionalProperties": False,
        "properties": {
            "document_id": {"type": "string"},
            "fragment_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {"type": "string", "enum": list(fragments)},
            },
            "evidence_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": {"type": "string", "enum": list(cells)},
            },
            "reason": {"type": "string"},
        },
    }
    if drawings:
        group["required"].append("drawing_ids")
        group["properties"]["drawing_ids"] = {
            "type": "array",
            "maxItems": 100,
            "items": {"type": "string", "enum": list(drawings)},
        }
    schema = {
        "type": "object",
        "required": ["groups"],
        "additionalProperties": False,
        "properties": {"groups": {"type": "array", "maxItems": 100, "items": group}},
    }
    from app.application.reviewed_excel_reference_ids import DRAWING_GROUP_PROMPT, GROUP_PROMPT

    messages = [
        {"role": "system", "content": DRAWING_GROUP_PROMPT if drawings else GROUP_PROMPT},
        {
            "role": "user",
            "content": json.dumps({"output_schema": schema, **shown}, ensure_ascii=False),
        },
    ]
    from app.application.reviewed_excel_reference_ids import verify_contract

    verify_contract(messages[0]["content"], schema, "group")
    if sum(len(message["content"].encode("utf-8")) for message in messages) > 180_000:
        raise ReviewedExcelError("分组请求超过安全预算，未调用模型")
    audit_request = {"messages": messages, "schema": schema, "max_tokens": 4000}
    if prepare_only:
        return audit_request
    if expected_request_sha256 is not None:
        from app.application.reviewed_excel_audit import verify_request

        verify_request(audit_request, expected_request_sha256)
    response = _template_mimo_complete(messages, schema, 4000)
    if not _validate_template_schema(schema, response.data):
        raise ReviewedExcelError("模型分组编号不在白名单")
    normalized = {
        "groups": [
            {
                **(
                    {
                        "drawing_evidence": [
                            {k: drawings[key][k] for k in ("sheet", "part", "object_id")}
                            for key in item["drawing_ids"]
                        ]
                    }
                    if drawings
                    else {}
                ),
                "document_id": item["document_id"],
                "fragments": [
                    {"sheet": fragments[key]["sheet"], "range": fragments[key]["range"]}
                    for key in item["fragment_ids"]
                ],
                "evidence": [
                    {"sheet": cells[key]["sheet"], "cell": cells[key]["cell"]}
                    for key in item["evidence_ids"]
                ],
                "reason": item["reason"],
            }
            for item in response.data["groups"]
        ]
    }
    result = validate_grouping(group_input, normalized)
    for item, raw in zip(result, response.data["groups"], strict=True):
        item["reference_ids"] = {
            **({"drawing_ids": raw["drawing_ids"]} if drawings else {}),
            "fragment_ids": raw["fragment_ids"],
            "evidence_ids": raw["evidence_ids"],
        }
    return result
