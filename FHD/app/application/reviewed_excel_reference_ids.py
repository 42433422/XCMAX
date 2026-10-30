"""Prototype: map model evidence IDs to the exact bounded source coordinates."""

import hashlib
import json
from copy import deepcopy

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range


def source_sheet_prefixes(sheets: list) -> list[dict]:
    """Assign source identities in workbook order, independent of selected batch cells."""
    names = [sheet["sheet"] if isinstance(sheet, dict) else sheet for sheet in sheets]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(
        names
    ):
        raise ReviewedExcelError("源工作表身份无效或重复")
    return [{"sheet": name, "prefix": f"S{index}"} for index, name in enumerate(names, 1)]


def source_cell_ids(cells: list[dict], prefixes: list[dict]) -> list[str]:
    """Encode only supplied source identities; returned IDs must still pass the exact whitelist."""
    mapping = {item["sheet"]: item["prefix"] for item in prefixes}
    identifiers = []
    for cell in cells:
        if cell["sheet"] not in mapping:
            raise ReviewedExcelError("证据工作表不在源工作簿中")
        identifiers.append(f"{mapping[cell['sheet']]}:{cell['cell']}")
    if len(set(identifiers)) != len(identifiers):
        raise ReviewedExcelError("证据坐标重复")
    return identifiers


def source_layout_schema(sheets: list[dict]) -> dict:
    """Source merge references have their own schema, never document fragment aliases."""
    props: dict = {"sheet": {"type": "string"}, "range": {"type": "string"}}
    ranges = sorted({area for sheet in sheets for area in sheet["merged"]})
    if ranges:
        props["sheet"]["enum"] = sorted({sheet["sheet"] for sheet in sheets if sheet["merged"]})
        props["range"]["enum"] = ranges
    return {
        "type": "array",
        "maxItems": 100 if ranges else 0,
        "items": {
            "type": "object",
            "required": ["sheet", "range"],
            "additionalProperties": False,
            "properties": props,
        },
    }


def reference_contract(
    cells: list[dict],
    original_schema: dict,
    drawings: list[dict] | None = None,
    *,
    sheets: list | None = None,
) -> tuple[list[dict], dict, dict]:
    drawings = drawings or []
    if not cells or len(cells) + len(drawings) > 500:
        raise ReviewedExcelError("证据数量超出范围")
    references: dict[str, dict] = {}
    presented = []
    prefixes = source_sheet_prefixes(
        sheets if sheets is not None else list(dict.fromkeys(cell["sheet"] for cell in cells))
    )
    for identifier, cell in zip(source_cell_ids(cells, prefixes), cells, strict=True):
        ref = {"sheet": cell["sheet"], "cell": cell["cell"]}
        if any(entry["ref"] == ref for entry in references.values()):
            raise ReviewedExcelError("证据坐标重复")
        references[identifier] = {"ref": ref, "primary": not cell.get("context_only", False)}
        presented.append({**cell, "evidence_id": identifier})
    valid = list(references)
    primary = [key for key, value in references.items() if value["primary"]]
    if not primary:
        raise ReviewedExcelError("本批没有主体证据")
    schema = deepcopy(original_schema)
    region = schema["properties"]["physical_regions"]["items"]
    props = region["properties"]
    props["sheet"]["enum"] = sorted({cell["sheet"] for cell in cells})
    props.pop("labels")
    props.pop("evidence")
    props.pop("dependencies")
    props["evidence_ids"] = {
        "type": "array",
        "maxItems": 100,
        "items": {"type": "string", "enum": list(primary)},
    }
    props["dependency_ids"] = {
        "type": "array",
        "maxItems": 100,
        "items": {"type": "string", "enum": valid},
    }
    props["primary_id"] = {"type": "string", "enum": primary}
    region["required"] = [
        "sheet",
        "range",
        "evidence_ids",
        "dependency_ids",
        "primary_id",
        "reason",
    ]
    if drawings:
        drawing_ids = []
        for index, drawing in enumerate(drawings, 1):
            key = f"D{index:04d}"
            ref = {k: drawing[k] for k in ("sheet", "part", "object_id")}
            if any(entry["ref"] == ref for entry in references.values()):
                raise ReviewedExcelError("绘图证据身份重复")
            references[key] = {"ref": ref, "primary": True, "drawing": True}
            drawing_ids.append(key)
        props.pop("drawing_evidence")
        props["drawing_ids"] = {
            "type": "array",
            "maxItems": 100,
            "items": {"type": "string", "enum": drawing_ids},
        }
        region["required"].append("drawing_ids")
    return presented, references, schema


def normalize_reference_ids(
    data: dict, references: dict, id_schema: dict, original_schema: dict
) -> dict:
    """Fail closed on unknown IDs or primary evidence outside the proposed region."""
    from app.application.reviewed_excel_template import _validate_template_schema

    if not _validate_template_schema(id_schema, data):
        raise ReviewedExcelError("模型证据编号不在本批白名单")
    normalized = deepcopy(data)
    for region in normalized["physical_regions"]:
        # Internal compatibility state only; it is not supplied to or predicted by the model.
        region["labels"] = ["unknown"]
        primary_id = region.pop("primary_id")
        entry = references[primary_id]
        if not entry["primary"]:
            raise ReviewedExcelError("主体证据不能只来自上下文")
        ref = entry["ref"]
        col, row = coordinate_from_string(ref["cell"])
        c1, r1, c2, r2 = bounded_range(region["range"])
        if ref["sheet"] != region["sheet"] or not (
            c1 <= column_index_from_string(col) <= c2 and r1 <= row <= r2
        ):
            raise ReviewedExcelError("模型区域没有区域内主体证据")
        if "drawing_ids" in region:
            identifiers = region.pop("drawing_ids")
            if len(set(identifiers)) != len(identifiers):
                raise ReviewedExcelError("模型绘图证据编号重复")
            region["drawing_evidence"] = [deepcopy(references[key]["ref"]) for key in identifiers]
        for old, new in [("evidence_ids", "evidence"), ("dependency_ids", "dependencies")]:
            identifiers = region.pop(old)
            if len(set(identifiers)) != len(identifiers):
                raise ReviewedExcelError("模型证据编号重复")
            if old == "evidence_ids" and any(not references[key]["primary"] for key in identifiers):
                raise ReviewedExcelError("分类证据不能只来自上下文")
            region[new] = [deepcopy(references[key]["ref"]) for key in identifiers]
    if not _validate_template_schema(original_schema, normalized):
        raise ReviewedExcelError("原分类schema校验失败")
    return normalized


def prepare_reference_messages(messages: list[dict], schema: dict) -> tuple[dict, dict]:
    import json

    neutralize_messages(messages)
    payload = json.loads(messages[1]["content"])
    payload["cells"], references, provider_schema = reference_contract(
        payload["cells"], schema, payload.get("drawing_evidence"), sheets=payload["sheets"]
    )
    if payload.get("drawing_evidence"):
        payload["drawing_evidence"] = [
            {**drawing, "drawing_id": f"D{index:04d}"}
            for index, drawing in enumerate(payload["drawing_evidence"], 1)
        ]
    payload["source_sheet_prefixes"] = source_sheet_prefixes(payload["sheets"])
    payload["output_schema"] = provider_schema
    payload["integrity_constraints"] = integrity_constraints(payload["cells"], payload["sheets"])
    for coverage in payload["batch_coverage"]:
        selected = [cell for cell in payload["cells"] if cell["sheet"] == coverage["sheet"]]
        coverage["sent_nonempty"] = sum(not cell.get("context_only") for cell in selected)
        coverage["context_only"] = len(selected) - coverage["sent_nonempty"]
        coverage["unread_nonempty"] = coverage["total_nonempty"] - coverage["sent_nonempty"]
    messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    messages[0]["content"] = (
        DRAWING_IDENTIFY_PROMPT if payload.get("drawing_evidence") else IDENTIFY_PROMPT
    )
    return references, provider_schema


def neutralize_messages(messages: list[dict]) -> None:
    """Remove software-produced business hints and geometry candidates from model input."""
    import json

    payload = json.loads(messages[1]["content"])
    anchors = {
        (sheet["sheet"], area.split(":", 1)[0]): area
        for sheet in payload["sheets"]
        for area in sheet["merged"]
    }
    for cell in payload["cells"]:
        cell.pop("required_extent", None)
        area = anchors.get((cell["sheet"], cell["cell"]))
        if area:
            cell["required_extent"] = area
    for key in ("rule_hints", "structure_map", "relationship_context", "labels"):
        payload.pop(key, None)
    for coverage in payload["batch_coverage"]:
        selected = [cell for cell in payload["cells"] if cell["sheet"] == coverage["sheet"]]
        coverage["sent_nonempty"] = sum(not cell.get("context_only") for cell in selected)
        coverage["context_only"] = len(selected) - coverage["sent_nonempty"]
        coverage["unread_nonempty"] = coverage["total_nonempty"] - coverage["sent_nonempty"]
    messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    messages[0]["content"] = SOURCE_PROTOCOL


def add_reference_trace(summary: dict, raw: dict, references: dict) -> None:
    used = {
        identifier
        for region in raw["physical_regions"]
        for identifier in [
            region["primary_id"],
            *region["evidence_ids"],
            *region["dependency_ids"],
            *region.get("drawing_ids", []),
        ]
    }
    summary["reference_response"] = raw
    summary["reference_index"] = {key: references[key] for key in sorted(used)}


def integrity_constraints(cells: list[dict], sheets: list[dict]) -> dict:
    """Describe sent primary rows and static formula references without claiming document identity."""
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
    from openpyxl.utils.cell import range_boundaries

    primary_rows: dict[str, set[int]] = {}
    formulas = []
    for cell in cells:
        if cell.get("context_only"):
            continue
        _, row = coordinate_from_string(cell["cell"])
        primary_rows.setdefault(cell["sheet"], set()).add(row)
        if cell.get("kind") != "formula":
            continue
        references = []
        unresolved = False
        try:
            for token in Tokenizer(cell["value"]).items:
                if token.type == "OPERAND" and token.subtype == "ERROR":
                    unresolved = True
                if (
                    token.type == "FUNC"
                    and token.subtype == "OPEN"
                    and token.value[:-1].upper()
                    not in {
                        "SUM",
                        "AVERAGE",
                        "MIN",
                        "MAX",
                        "ROUND",
                        "IF",
                        "IFERROR",
                        "COUNT",
                        "COUNTA",
                    }
                ):
                    unresolved = True
                if token.type != "OPERAND" or token.subtype != "RANGE":
                    continue
                target = token.value
                sheet = cell["sheet"]
                if "!" in target:
                    unresolved = True
                    sheet, target = target.rsplit("!", 1)
                    sheet = sheet.strip("'").replace("''", "'")
                if "[" in sheet or "[" in target or ":" in sheet:
                    unresolved = True
                    continue
                try:
                    bounds = range_boundaries(target.replace("$", ""))
                    if any(value is None for value in bounds):
                        unresolved = True
                        continue
                except (TypeError, ValueError):
                    unresolved = True
                    continue
                references.append({"sheet": sheet, "range": target})
        except TokenizerError:
            unresolved = True
        formulas.append(
            {"evidence_id": cell["evidence_id"], "references": references, "unresolved": unresolved}
        )
    rows = []
    for sheet, numbers in sorted(primary_rows.items()):
        spans: list[list[int]] = []
        for row in sorted(numbers):
            if spans and row == spans[-1][1] + 1:
                spans[-1][1] = row
            else:
                spans.append([row, row])
        rows.append({"sheet": sheet, "primary_row_spans": spans})
    merges = [
        {"sheet": sheet["sheet"], "ranges": sheet["merged"], "omitted": sheet["merged_omitted"]}
        for sheet in sheets
    ]
    return {"primary_rows": rows, "formula_references": formulas, "merged_ranges": merges}


def neutral_transport_batches(review: dict) -> list[list[dict]]:
    """Partition only by worksheet, source row and transport budget, never business hints."""
    from collections import deque

    from app.application.reviewed_excel_evidence import (
        MAX_MODEL_CELLS,
        MAX_MODEL_TEXT_BYTES,
        MAX_VALUE_CHARS,
        _model_cell_cost,
    )

    cells = review["cells"]
    if (
        len(cells) <= MAX_MODEL_CELLS
        and all(len(cell["value"]) <= MAX_VALUE_CHARS for cell in cells)
        and sum(map(_model_cell_cost, cells)) <= MAX_MODEL_TEXT_BYTES
    ):
        return [list(cells)]
    queues = []
    for sheet in review["sheets"]:
        rows: dict[int, list[dict]] = {}
        for cell in cells:
            if cell["sheet"] == sheet:
                _, row = coordinate_from_string(cell["cell"])
                rows.setdefault(row, []).append(cell)
        sheet_cells = [cell for row in sorted(rows) for cell in rows[row]]
        context = list(
            {
                (cell["sheet"], cell["cell"]): cell for cell in sheet_cells[:5] + sheet_cells[-5:]
            }.values()
        )
        context = [cell for cell in context if len(cell["value"]) <= MAX_VALUE_CHARS]
        reserved_count = len(context)
        reserved_cost = sum(map(_model_cell_cost, context))
        batches: list[list[dict]] = []
        current: list[dict] = []
        current_cost = 0
        for row in sorted(rows):
            group = rows[row]
            cost = sum(map(_model_cell_cost, group))
            if (
                len(group) > MAX_MODEL_CELLS
                or cost > MAX_MODEL_TEXT_BYTES
                or any(len(c["value"]) > MAX_VALUE_CHARS for c in group)
            ):
                if current:
                    batches.append(current)
                    current, current_cost = [], 0
                raise ReviewedExcelError("单行超出模型安全预算，未调用模型")
            if current and (
                len(current) + len(group) > MAX_MODEL_CELLS - reserved_count
                or current_cost + cost > MAX_MODEL_TEXT_BYTES - reserved_cost
            ):
                batches.append(current)
                current, current_cost = [], 0
            current.extend(group)
            current_cost += cost
        if current:
            batches.append(current)
        for batch in batches:
            seen = {(cell["sheet"], cell["cell"]) for cell in batch}
            cost = sum(map(_model_cell_cost, batch))
            for cell in context:
                key = (cell["sheet"], cell["cell"])
                item_cost = _model_cell_cost(cell)
                if (
                    key not in seen
                    and len(batch) < MAX_MODEL_CELLS
                    and cost + item_cost <= MAX_MODEL_TEXT_BYTES
                ):
                    batch.append({**cell, "context_only": True})
                    seen.add(key)
                    cost += item_cost
        if batches:
            queues.append(deque(batches))
    result = []
    while any(queues):
        for queue in queues:
            if queue:
                result.append(queue.popleft())
    if not result:
        raise ReviewedExcelError("单行超出模型安全预算，未调用模型；请人工检查并分开文件")
    return result


CONTRACT_VERSION = "independent-excel-v6-merge-closed"
SOURCE_PROTOCOL = (
    "Identify physical fragments and group them into logical documents using only the supplied source cells and structure. "
    "Do not assume a document count or infer a business boundary from a transport batch or sheet boundary. "
    "Leave uncertain fragments ungrouped. Do not use unread content as evidence. "
    "Keep merged cells intact; every evidence coordinate MUST be inside its region and on the same sheet. "
    "External context belongs in dependencies. A repeated table header is an observation, not proof "
    "of continuation or a business category. Treat structural observations, not proof, as context only. "
    "Return exactly one JSON object matching output_schema, without extra fields."
    " physical_regions are non-overlapping geometric fragments, not document counts. "
    "Every supplied non-context nonempty cell must lie in exactly one physical region. "
    "A physical region must contain its own supplied non-context nonempty evidence; "
    "blank cells may be included, but blank layout, formatting or merge metadata alone cannot form a region. "
    "Any region intersecting a merged range must contain that entire merged range. "
    "A cell's required_extent is its exact source merged rectangle, including blank subordinate cells: "
    "the physical region containing that primary cell must contain the whole required_extent on that sheet. "
    "This extent is indivisible source geometry, not a business boundary or a separate document. "
    "Use two-dimensional rectangles where needed, not just whole-row cuts; "
    "never cut a merge or borrow unread nonempty cells to complete a rectangle. "
    "context_only cells may be dependencies, never primary or classification evidence. "
    "Formula target coordinates and merge metadata describe source structure, not additional supplied cells. "
    "A formula target is available evidence only if it is explicitly present in cells. "
    "logical_documents.fragments must copy exact sheet/range pairs from this response's physical_regions; "
    "do not invent larger document bounding boxes. Assign each fragment to at most one document, "
    "without duplicate fragments. document_id must be nonblank, unique and at most 80 characters. "
    "Ungrouped fragments are allowed and logical_documents may be []. "
    "layout_references contains only exact sheet/range pairs from sheets[].merged on the same sheet, "
    "not physical-region or document bounding boxes. It is an optional subset of source layout references, "
    "not a merge-coverage ledger: use [] when none is needed, not an enumeration of every merge."
)
IDENTIFY_PROMPT = SOURCE_PROTOCOL + (
    " Use only supplied evidence_id values for evidence_ids, dependency_ids and primary_id. "
    "Evidence IDs encode source_sheet_prefixes and source coordinates, not sequence numbers. "
    "The primary_id must identify a non-context cell inside its region. "
    "For each region cite only a small set of representative evidence IDs, at most 100; "
    "do not list every cell. Include only necessary dependency IDs, also at most 100. "
    "Integrity constraints show primary row spans, direct formula references and known merged ranges. "
    "Do not sever merged ranges or treat formula references as proof of one business document. "
    "Every sent non-context primary cell must be inside exactly one non-overlapping physical region, "
    "including isolated headers, footnotes, and formulas; do not include unread cells to fill gaps. "
    "Unresolved references and omitted merges require caution; unread cells are not evidence."
    " Create physical_regions only for ranges containing at least one supplied non-context nonempty source cell. "
    "Never create a standalone physical_region for blank layout, formatting-only areas, merge metadata alone, "
    "or unread areas; never borrow a primary_id from outside a region to satisfy the schema. "
    "Blank cells may remain inside a larger region that also contains its own supplied primary evidence. "
    "Full primary-cell coverage does not require enumerating all cells as evidence: "
    "choose 1 to 8 representative evidence_ids per region. "
    "Check each selected ID against its supplied sheet and coordinate; "
    "related references outside the region belong only in dependency_ids. "
    "Never synthesize evidence IDs from formula targets or other metadata coordinates; "
    "only cells[].evidence_id values are available, with context_only IDs restricted to dependency_ids."
)
DRAWING_IDENTIFY_PROMPT = IDENTIFY_PROMPT + (
    " When drawing_evidence is present, use only supplied drawing_id values in drawing_ids. "
    "Drawing text and anchors are source evidence; last_col and last_row are conservative outer bounds, not document suggestions. "
    "Every drawing must be wholly inside one region; do not cut objects horizontally or vertically. "
    "Choose two-dimensional rectangles independently; transport batches do not prescribe document boundaries."
)
GROUP_PROMPT = (
    "Group only fragments that belong to the same business document. "
    "A standalone fragment can be one group. Do not group merely because fragments are adjacent, "
    "have similar headers, or share a category. Leave uncertain fragments ungrouped. "
    "For every grouped fragment cite at least one sent cell within it and explain the relationship "
    "using sent values. Use only supplied region_id and evidence_id values. "
    "Fragment boundaries are fixed; do not invent ranges or cells. "
    "Return exactly one JSON object matching output_schema."
)
DRAWING_GROUP_PROMPT = GROUP_PROMPT + (
    " When drawing_evidence is present, cite only supplied drawing_id values in drawing_ids; "
    "each cited object must be wholly contained in one of the group's fixed fragments."
)


def contract_hashes(schema: dict, phase: str) -> dict:
    """Hash the stable schema template; replace only IDs mechanically sourced from this input."""
    template = deepcopy(schema)
    if phase == "identify":
        props = template["properties"]["physical_regions"]["items"]["properties"]
        if props["evidence_ids"]["items"]["enum"] != props["primary_id"]["enum"]:
            raise ValueError("classification evidence must use the primary source whitelist")
        props["sheet"]["enum"] = ["<SOURCE_SHEETS>"]
        props["evidence_ids"]["items"]["enum"] = ["<PRIMARY_EVIDENCE_IDS>"]
        props["dependency_ids"]["items"]["enum"] = ["<SOURCE_EVIDENCE_IDS>"]
        props["primary_id"]["enum"] = ["<PRIMARY_EVIDENCE_IDS>"]
        if "drawing_ids" in props:
            props["drawing_ids"]["items"]["enum"] = ["<SOURCE_DRAWING_IDS>"]
        layout = template["properties"]["layout_references"]
        layout_props = layout["items"]["properties"]
        if type(layout["maxItems"]) is not int:
            raise ValueError("invalid layout source bound")
        if layout["maxItems"] == 0:
            if any("enum" in layout_props[key] for key in ("sheet", "range")):
                raise ValueError("empty layout source has unexpected enums")
            layout["maxItems"] = 100
        elif layout["maxItems"] != 100 or any(
            not isinstance(layout_props[key].get("enum"), list)
            or not layout_props[key]["enum"]
            or any(not isinstance(value, str) or not value for value in layout_props[key]["enum"])
            for key in ("sheet", "range")
        ):
            raise ValueError("invalid source layout enum contract")
        layout_props["sheet"]["enum"] = ["<SOURCE_MERGE_SHEETS>"]
        layout_props["range"]["enum"] = ["<SOURCE_MERGE_RANGES>"]
        prompt = DRAWING_IDENTIFY_PROMPT if "drawing_ids" in props else IDENTIFY_PROMPT
    elif phase == "group":
        props = template["properties"]["groups"]["items"]["properties"]
        props["fragment_ids"]["items"]["enum"] = ["<MODEL_FRAGMENT_IDS>"]
        props["evidence_ids"]["items"]["enum"] = ["<SOURCE_EVIDENCE_IDS>"]
        if "drawing_ids" in props:
            props["drawing_ids"]["items"]["enum"] = ["<SOURCE_DRAWING_IDS>"]
        prompt = DRAWING_GROUP_PROMPT if "drawing_ids" in props else GROUP_PROMPT
    else:
        raise ValueError("unknown contract phase")
    canonical = json.dumps(template, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "version": CONTRACT_VERSION + "-drawing" if "drawing_ids" in props else CONTRACT_VERSION,
        "phase": phase,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_template_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


_EXPECTED = {
    "identify": (
        "dc367beb7386ca10082be112dff5b50d32dce0968aa6a868be5e8c06841106f5",
        "bb4c8dca5c9e7fa2815e2066ea4ff82af17ef3cf1e9c4067bae8ff8a8021bc80",
    ),
    "group": (
        "440a63ab70be709c7825a4e6374ef3c1f3e52687a3e8b4f3f5927235459ee22e",
        "f0f500cbbf7f3925cae7f6885e51a46c92cb4069a8ded998c2724fdc4ba5f379",
    ),
    "identify_drawing": (
        "1c30723c74bd33de1608a802b67c735093f80f4192ab6d7c262de725c9c317a6",
        "15de0f5d41027cf4d1e6034fad68e704e3377763a0e91e37c3dda8509314209b",
    ),
    "group_drawing": (
        "49665c8535ed2aa9ba6a4dfc047fe360ccf97ddcead5063b20f05314f097c4b8",
        "47042d8477ddf0eb59819d512ead64c7213fc4210351687df0bedea6403129df",
    ),
}


def verify_contract(prompt: str, schema: dict, phase: str) -> dict:
    from app.application.etl.errors import ReviewedExcelError

    try:
        hashes = contract_hashes(schema, phase)
        actual_prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        key = phase + (
            "_drawing"
            if "drawing_ids"
            in (
                schema["properties"]["physical_regions" if phase == "identify" else "groups"][
                    "items"
                ]["properties"]
            )
            else ""
        )
        if (actual_prompt_hash, hashes["schema_template_sha256"]) != _EXPECTED[key]:
            raise ReviewedExcelError("模型输入契约已改变，未调用模型")
    except (KeyError, TypeError, ValueError):
        raise ReviewedExcelError("模型输入契约无效，未调用模型") from None
    return hashes
