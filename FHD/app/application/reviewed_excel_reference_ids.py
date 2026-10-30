"""Prototype: map model evidence IDs to the exact bounded source coordinates."""

import hashlib
import json
from copy import deepcopy

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range


def reference_contract(cells: list[dict], original_schema: dict) -> tuple[list[dict], dict, dict]:
    if not cells or len(cells) > 500:
        raise ReviewedExcelError("证据数量超出范围")
    references: dict[str, dict] = {}
    presented = []
    for index, cell in enumerate(cells, 1):
        identifier = f"E{index:04d}"
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
        "items": {"type": "string", "enum": valid},
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
    payload["cells"], references, provider_schema = reference_contract(payload["cells"], schema)
    payload["output_schema"] = provider_schema
    payload["integrity_constraints"] = integrity_constraints(payload["cells"], payload["sheets"])
    for coverage in payload["batch_coverage"]:
        selected = [cell for cell in payload["cells"] if cell["sheet"] == coverage["sheet"]]
        coverage["sent_nonempty"] = sum(not cell.get("context_only") for cell in selected)
        coverage["context_only"] = len(selected) - coverage["sent_nonempty"]
        coverage["unread_nonempty"] = coverage["total_nonempty"] - coverage["sent_nonempty"]
    messages[1]["content"] = json.dumps(payload, ensure_ascii=False)
    messages[0]["content"] = IDENTIFY_PROMPT
    return references, provider_schema


def neutralize_messages(messages: list[dict]) -> None:
    """Remove software-produced business hints and geometry candidates from model input."""
    import json

    payload = json.loads(messages[1]["content"])
    for key in ("rule_hints", "structure_map", "relationship_context", "labels"):
        payload.pop(key, None)
    for coverage in payload["batch_coverage"]:
        selected = [cell for cell in payload["cells"] if cell["sheet"] == coverage["sheet"]]
        coverage["sent_nonempty"] = sum(not cell.get("context_only") for cell in selected)
        coverage["context_only"] = len(selected) - coverage["sent_nonempty"]
        coverage["unread_nonempty"] = coverage["total_nonempty"] - coverage["sent_nonempty"]
    messages[1]["content"] = json.dumps(payload, ensure_ascii=False)
    messages[0]["content"] = (
        "Identify physical fragments and group them into logical documents using only the supplied source cells and structure. "
        "Do not assume a document count or infer a business boundary from a transport batch or sheet boundary. "
        "Leave uncertain fragments ungrouped. Do not use unread content as evidence. "
        "Keep merged cells intact; every evidence coordinate MUST be inside its region and on the same sheet. "
        "External context belongs in dependencies. A repeated table header is an observation, not proof "
        "of continuation or a business category. Treat structural observations, not proof, as context only. "
        "Return exactly one JSON object matching output_schema, without extra fields."
    )


def add_reference_trace(summary: dict, raw: dict, references: dict) -> None:
    used = {
        identifier
        for region in raw["physical_regions"]
        for identifier in [region["primary_id"], *region["evidence_ids"], *region["dependency_ids"]]
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
                continue
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


CONTRACT_VERSION = "independent-excel-v1"
IDENTIFY_PROMPT = (
    "Identify physical fragments and group them into logical documents using only the supplied source cells and structure. "
    "Do not assume a document count or infer a business boundary from a transport batch or sheet boundary. "
    "Leave uncertain fragments ungrouped. Do not use unread content as evidence. "
    "Keep merged cells intact; every evidence coordinate MUST be inside its region and on the same sheet. "
    "External context belongs in dependencies. A repeated table header is an observation, not proof "
    "of continuation or a business category. Treat structural observations, not proof, as context only. "
    "Return exactly one JSON object matching output_schema, without extra fields."
    " Use only supplied evidence_id values for evidence_ids, dependency_ids and primary_id. "
    "The primary_id must identify a non-context cell inside its region. "
    "For each region cite only a small set of representative evidence IDs, at most 100; "
    "do not list every cell. Include only necessary dependency IDs, also at most 100. "
    "Integrity constraints show primary row spans, direct formula references and known merged ranges. "
    "Do not sever merged ranges or treat formula references as proof of one business document. "
    "Unresolved references and omitted merges require caution; unread cells are not evidence."
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


def contract_hashes(schema: dict, phase: str) -> dict:
    """Hash the stable schema template; replace only IDs mechanically sourced from this input."""
    template = deepcopy(schema)
    if phase == "identify":
        props = template["properties"]["physical_regions"]["items"]["properties"]
        props["sheet"]["enum"] = ["<SOURCE_SHEETS>"]
        for key in ("evidence_ids", "dependency_ids"):
            props[key]["items"]["enum"] = ["<SOURCE_EVIDENCE_IDS>"]
        props["primary_id"]["enum"] = ["<PRIMARY_EVIDENCE_IDS>"]
        prompt = IDENTIFY_PROMPT
    elif phase == "group":
        props = template["properties"]["groups"]["items"]["properties"]
        props["fragment_ids"]["items"]["enum"] = ["<MODEL_FRAGMENT_IDS>"]
        props["evidence_ids"]["items"]["enum"] = ["<SOURCE_EVIDENCE_IDS>"]
        prompt = GROUP_PROMPT
    else:
        raise ValueError("unknown contract phase")
    canonical = json.dumps(template, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "version": CONTRACT_VERSION,
        "phase": phase,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_template_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


_EXPECTED = {
    "identify": (
        "fd3c4a833f821b8ffbdc77dbd35557e8eeda9059c7fee59c4a6960bac5ac308e",
        "e2e1ceb650586cdc2954e2e622e6807a03a3fec251aa122dc17d1fdd6dc01b4a",
    ),
    "group": (
        "440a63ab70be709c7825a4e6374ef3c1f3e52687a3e8b4f3f5927235459ee22e",
        "f0f500cbbf7f3925cae7f6885e51a46c92cb4069a8ded998c2724fdc4ba5f379",
    ),
}


def verify_contract(prompt: str, schema: dict, phase: str) -> dict:
    from app.application.etl.errors import ReviewedExcelError

    try:
        hashes = contract_hashes(schema, phase)
        actual_prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        if (actual_prompt_hash, hashes["schema_template_sha256"]) != _EXPECTED[phase]:
            raise ReviewedExcelError("模型输入契约已改变，未调用模型")
    except (KeyError, TypeError, ValueError):
        raise ReviewedExcelError("模型输入契约无效，未调用模型") from None
    return hashes
