"""Bounded second-stage grouping of fully covered model fragments."""

from typing import Any

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import (
    MAX_MODEL_CELLS,
    MAX_MODEL_TEXT_BYTES,
    bounded_range,
)


def _structure_sample_cells(inside: list[dict]) -> list[dict]:
    """Sample first/middle/last structure rows and a capped formula set.

    Classification transport may send up to MAX_MODEL_CELLS (2000) per pack;
    grouping still samples structure only — never dumps full packs unsampled.
    Gate in prepare_grouping uses the shared cell/byte caps so multi-fragment
    samples (previously failing at 617 > 500) fit after sampling.
    """
    by_row: dict[int, list[dict]] = {}
    for cell in inside:
        _, row = coordinate_from_string(cell["cell"])
        by_row.setdefault(row, []).append(cell)
    rows = sorted(by_row)
    chosen_rows = set(rows[:3] + rows[-3:])
    if len(rows) > 6:
        for fraction in (0.25, 0.5, 0.75):
            chosen_rows.add(rows[int((len(rows) - 1) * fraction)])
    selected: list[dict] = []
    for row in sorted(chosen_rows):
        # 3 cells/row (was 4): enough for headers/keys without blowing the
        # sampled grouping budget across many fragments.
        selected.extend(by_row[row][:3])
    formulas = [cell for cell in inside if cell.get("kind") == "formula"]
    formula_cap = 8
    if len(formulas) <= formula_cap:
        selected.extend(formulas)
    else:
        step = max(1, len(formulas) // formula_cap)
        picked = formulas[::step][:formula_cap]
        for edge in (formulas[0], formulas[-1]):
            if edge not in picked:
                picked.append(edge)
        selected.extend(picked[:formula_cap])
    return selected


def _cross_fragment_formula_links(cells: list[dict], fragments: list[dict]) -> list[dict]:
    """Describe formula references that touch another fragment; never merge answers."""
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
    from openpyxl.utils.cell import range_boundaries

    bounds = []
    for part in fragments:
        c1, r1, c2, r2 = bounded_range(part["range"])
        bounds.append((part["sheet"], part["range"], c1, r1, c2, r2))
    links: list[dict] = []
    seen: set[tuple] = set()
    for cell in cells:
        if cell.get("kind") != "formula":
            continue
        owner = None
        col, row = coordinate_from_string(cell["cell"])
        col_i = column_index_from_string(col)
        for sheet, area, c1, r1, c2, r2 in bounds:
            if cell["sheet"] == sheet and c1 <= col_i <= c2 and r1 <= row <= r2:
                owner = (sheet, area)
                break
        if owner is None:
            continue
        try:
            tokens = Tokenizer(cell["value"]).items
        except TokenizerError:
            continue
        for token in tokens:
            if token.type != "OPERAND" or token.subtype != "RANGE":
                continue
            target = token.value
            sheet = cell["sheet"]
            if "!" in target:
                continue
            try:
                tc1, tr1, tc2, tr2 = range_boundaries(target.replace("$", ""))
            except (TypeError, ValueError):
                continue
            if None in (tc1, tr1, tc2, tr2):
                continue
            for fsheet, farea, c1, r1, c2, r2 in bounds:
                if fsheet != sheet or (fsheet, farea) == owner:
                    continue
                if tc1 <= c2 and c1 <= tc2 and tr1 <= r2 and r1 <= tr2:
                    key = (cell["sheet"], cell["cell"], owner[1], farea, target)
                    if key in seen:
                        continue
                    seen.add(key)
                    links.append(
                        {
                            "from_sheet": cell["sheet"],
                            "from_cell": cell["cell"],
                            "from_fragment": owner[1],
                            "to_fragment": farea,
                            "to_range": target,
                            "formula": cell["value"][:500],
                        }
                    )
    return links[:200]


def prepare_grouping(review: dict, classification: dict) -> dict:
    """Build a bounded evidence index; never infer relationships from coordinates alone."""
    if review["sha256"] != classification.get("source_sha256"):
        raise ReviewedExcelError("分组来源与原件不一致")
    sheet_states = {
        overview["sheet"]: overview.get("sheet_state", "visible")
        for overview in review.get("sheet_overview", [])
    }
    coverage = classification.get("coverage", [])
    if len(coverage) != len(review["sheets"]) or any(
        (
            sheet_states.get(row.get("sheet"), "visible") not in {"hidden", "veryHidden"}
            and (
                row.get("unread")
                or row.get("unassigned")
                or row.get("merged_omitted")
                or row.get("drawing_unread")
                or row.get("drawing_unassigned")
            )
        )
        for row in coverage
    ):
        raise ReviewedExcelError("文件覆盖不完整，不能进行最终分组")
    regions = classification.get("regions", [])
    if not 1 <= len(regions) <= 100:
        raise ReviewedExcelError("分组区域数量超过本轮安全预算")
    source_cells = review["cells"]
    sheet_filters_early = [
        {"sheet": overview["sheet"], "ref": overview["auto_filter_ref"]}
        for overview in review.get("sheet_overview", [])
        if overview.get("auto_filter_ref")
    ]
    chosen = {}
    fragments = []
    fragment_structure = []
    omitted_hidden_fragments = []
    for region in regions:
        sheet, area = region["sheet"], region["range"]
        state = sheet_states.get(sheet, "visible")
        if state in {"hidden", "veryHidden"}:
            # Independent extract rejects hidden sheets; keep them out of final
            # grouping so models may omit them without coverage failure.
            omitted_hidden_fragments.append(
                {
                    "sheet": sheet,
                    "range": area,
                    "sheet_state": state,
                    "reason": region.get("reason", "")[:1000],
                }
            )
            continue
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
            *_structure_sample_cells(inside),
            *(c for c in inside if (c["sheet"], c["cell"]) in evidence),
        ]
        # Always surface a capped set of filter-aware aggregates so the model can
        # see them even when structure sampling omitted those rows.
        subtotal_cells = [
            c
            for c in inside
            if c.get("kind") == "formula" and "SUBTOTAL" in str(c.get("value", "")).upper()
        ]
        for cell in subtotal_cells[:12]:
            if cell not in selected:
                selected.append(cell)
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
                "sheet_state": state,
                "reason": region.get("reason", "")[:1000],
            }
        )
        first_row = coordinate_from_string(inside[0]["cell"])[1]
        last_row = coordinate_from_string(inside[-1]["cell"])[1]
        has_filter_aware = any(
            c.get("kind") == "formula" and "SUBTOTAL" in str(c.get("value", "")).upper()
            for c in inside
        )
        covers_sheet_filter = False
        for filt in sheet_filters_early:
            if filt["sheet"] != sheet:
                continue
            fc1, fr1, fc2, fr2 = bounded_range(filt["ref"])
            if not (c1 > fc2 or fc1 > c2 or r1 > fr2 or fr1 > r2):
                covers_sheet_filter = True
                break
        fragment_structure.append(
            {
                "sheet": sheet,
                "range": area,
                "sheet_state": state,
                "nonempty_cells": len(inside),
                "first_nonempty_row": first_row,
                "last_nonempty_row": last_row,
                "has_formulas": any(c.get("kind") == "formula" for c in inside),
                "has_filter_aware_aggregates": has_filter_aware,
                "covers_sheet_filter": covers_sheet_filter,
                "reason": region.get("reason", "")[:1000],
            }
        )
    if not fragments:
        raise ReviewedExcelError("可见工作表没有可分组片段")
    cells = list(chosen.values())
    # Cross-fragment formula facts must not depend on structure sampling: otherwise
    # filter-aware aggregates (e.g. SUBTOTAL) that sit outside the sample never reach
    # the model. Scan every formula cell that falls inside a fragment.
    formula_pool = []
    for part in fragments:
        sheet, area = part["sheet"], part["range"]
        c1, r1, c2, r2 = bounded_range(area)
        for cell in source_cells:
            if cell.get("kind") != "formula" or cell["sheet"] != sheet:
                continue
            col, row = coordinate_from_string(cell["cell"])
            if c1 <= column_index_from_string(col) <= c2 and r1 <= row <= r2:
                formula_pool.append({k: cell[k] for k in ("sheet", "cell", "value", "kind")})
    cross_fragment_formulas = _cross_fragment_formula_links(formula_pool, fragments)
    if (
        len(cells) > MAX_MODEL_CELLS
        or sum(len(c["value"].encode("utf-8")) + 64 for c in cells) > MAX_MODEL_TEXT_BYTES
    ):
        raise ReviewedExcelError("分组证据超过本轮安全预算")
    from app.application.reviewed_excel_reference_ids import source_sheet_prefixes

    sheet_filters = sheet_filters_early
    output = {
        "source_sha256": review["sha256"],
        "fragments": fragments,
        "cells": cells,
        "fragment_structure": fragment_structure,
        "cross_fragment_formulas": cross_fragment_formulas,
        "sheet_filters": sheet_filters,
        "source_sheet_prefixes": source_sheet_prefixes(review["sheets"]),
        "omitted_hidden_fragments": omitted_hidden_fragments,
    }
    model_index = review.get("workbook_structural_index_for_model")
    if isinstance(model_index, dict) and model_index:
        output["workbook_structural_index"] = model_index
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


def _range_group_input(group_input: dict) -> tuple[dict, dict]:
    from app.application.reviewed_excel_reference_ids import source_ranges_schema

    shown_ranges: list[dict] = []
    dimensions: dict[str, dict] = {}
    for part in group_input["fragments"]:
        c1, r1, c2, r2 = bounded_range(part["range"])
        shown_ranges.append(
            {
                "sheet_name": part["sheet"],
                "sheet_state": part.get("sheet_state", "visible"),
                "row_start": r1,
                "row_end": r2,
                "column_start": c1,
                "column_end": c2,
            }
        )
        dimension = dimensions.setdefault(
            part["sheet"], {"sheet": part["sheet"], "rows": 0, "columns": 0}
        )
        dimension["rows"] = max(dimension["rows"], r2)
        dimension["columns"] = max(dimension["columns"], c2)
    shown = {
        "source_sha256": group_input["source_sha256"],
        "ranges": shown_ranges,
        "cells": group_input["cells"],
        "fragment_structure": group_input.get("fragment_structure", []),
        "cross_fragment_formulas": group_input.get("cross_fragment_formulas", []),
    }
    if group_input.get("sheet_filters"):
        shown["sheet_filters"] = group_input["sheet_filters"]
    if group_input.get("workbook_structural_index"):
        shown["workbook_structural_index"] = group_input["workbook_structural_index"]
    return shown, source_ranges_schema(list(dimensions.values()))


def _normalize_range_groups(group_input: dict, data: dict) -> list[dict]:
    from copy import deepcopy

    from app.application.reviewed_excel_reference_ids import (
        decode_source_range,
        internal_document_id,
    )

    dimensions: dict[str, dict] = {}
    known = {(part["sheet"], part["range"]) for part in group_input["fragments"]}
    for sheet, area in known:
        _, _, c2, r2 = bounded_range(area)
        dimension = dimensions.setdefault(sheet, {"rows": 0, "columns": 0})
        dimension["rows"] = max(dimension["rows"], r2)
        dimension["columns"] = max(dimension["columns"], c2)
    assigned, groups = set(), []
    for document in data["documents"]:
        parts, evidence = [], []
        for area in document["ranges"]:
            part = decode_source_range(area, dimensions)
            key = (part["sheet"], part["range"])
            if key not in known or key in assigned:
                raise ReviewedExcelError("分组范围非已有精确片段或重复，未修改答案")
            assigned.add(key)
            parts.append(part)
            c1, r1, c2, r2 = bounded_range(part["range"])
            for cell in group_input["cells"]:
                col, row = coordinate_from_string(cell["cell"])
                if (
                    cell["sheet"] == part["sheet"]
                    and c1 <= column_index_from_string(col) <= c2
                    and r1 <= row <= r2
                ):
                    evidence.append({"sheet": cell["sheet"], "cell": cell["cell"]})
                    break
        groups.append(
            {
                "document_id": internal_document_id(document),
                "fragments": parts,
                "evidence": evidence,
                "reason": document["reason"],
            }
        )
    if assigned != known:
        raise ReviewedExcelError("最终分组未完整覆盖所有片段，不能自动补齐")
    result = validate_grouping(group_input, {"groups": groups})
    for group, raw in zip(result, data["documents"], strict=True):
        group["model_range_response"] = deepcopy(raw)
        group["source_coverage"] = {
            "basis": "exact_validated_source_ranges",
            "document_id_origin": "internal_source_range_hash",
            "fragments": deepcopy(group["fragments"]),
        }
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
    from app.application.reviewed_excel_reference_ids import source_cell_ids

    cells = dict(
        zip(
            source_cell_ids(group_input["cells"], group_input["source_sheet_prefixes"]),
            group_input["cells"],
            strict=True,
        )
    )
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
    group: dict[str, Any] = {
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
        from app.application.reviewed_excel_reference_ids import MAX_DRAWING_IDS_PER_REGION

        group["properties"]["drawing_ids"] = {
            "type": "array",
            "maxItems": min(MAX_DRAWING_IDS_PER_REGION, max(100, len(drawings))),
            "items": {"type": "string", "enum": list(drawings)},
        }
    schema = {
        "type": "object",
        "required": ["groups"],
        "additionalProperties": False,
        "properties": {"groups": {"type": "array", "maxItems": 100, "items": group}},
    }
    from app.application.reviewed_excel_reference_ids import (
        DRAWING_GROUP_PROMPT,
        RANGE_GROUP_PROMPT,
    )

    if not drawings:
        shown, schema = _range_group_input(group_input)

    messages = [
        {"role": "system", "content": DRAWING_GROUP_PROMPT if drawings else RANGE_GROUP_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"output_schema": schema, **shown}, ensure_ascii=False, separators=(",", ":")
            ),
        },
    ]
    from app.application.reviewed_excel_reference_ids import verify_contract

    verify_contract(messages[0]["content"], schema, "group")
    from app.application.reviewed_excel_budget import output_budget, validate_request_budget

    max_output_tokens = output_budget(group_input["fragments"])
    audit_request = {"messages": messages, "schema": schema, "max_tokens": max_output_tokens}
    validate_request_budget(audit_request)
    if prepare_only:
        return audit_request
    if expected_request_sha256 is not None:
        from app.application.reviewed_excel_audit import verify_request

        verify_request(audit_request, expected_request_sha256)
    response = _template_mimo_complete(messages, schema, max_output_tokens)
    if not _validate_template_schema(schema, response.data):
        raise ReviewedExcelError("模型分组编号不在白名单")
    if not drawings:
        return _normalize_range_groups(group_input, response.data)
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
