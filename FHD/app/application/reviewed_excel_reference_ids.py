"""Source-range contracts and archived evidence-ID compatibility."""

import hashlib
import json
from copy import deepcopy

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError

# Provider cite cap for drawing_ids; dense sheets may approach this in one region.
MAX_DRAWING_IDS_PER_REGION = 300
from app.application.reviewed_excel_evidence import bounded_range
from app.application.reviewed_excel_partition import (
    _normalize_atom_ids,
    _normalize_boundaries,
)
from app.application.reviewed_excel_partition import (
    decode_source_range as decode_source_range,
)
from app.application.reviewed_excel_partition import (
    internal_document_id as internal_document_id,
)
from app.application.reviewed_excel_partition import (
    source_ranges_schema as source_ranges_schema,
)
from app.application.reviewed_excel_reference_prompts import (
    ATOM_IDENTIFY_PROMPT as ATOM_IDENTIFY_PROMPT,
    CONTRACT_VERSION as CONTRACT_VERSION,
    DRAWING_GROUP_PROMPT as DRAWING_GROUP_PROMPT,
    DRAWING_IDENTIFY_PROMPT as DRAWING_IDENTIFY_PROMPT,
    GROUP_PROMPT as GROUP_PROMPT,
    IDENTIFY_PROMPT as IDENTIFY_PROMPT,
    LEGACY_IDENTIFY_PROMPT as LEGACY_IDENTIFY_PROMPT,
    RANGE_GROUP_PROMPT as RANGE_GROUP_PROMPT,
    SOURCE_PROTOCOL as SOURCE_PROTOCOL,
)


def source_sheet_prefixes(sheets: list) -> list[dict]:
    """Assign source identities in workbook order, independent of selected batch cells."""
    names = [sheet["sheet"] if isinstance(sheet, dict) else sheet for sheet in sheets]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(
        names
    ):
        raise ReviewedExcelError("源工作表身份无效或重复")
    return [{"sheet": name, "prefix": f"S{index}"} for index, name in enumerate(names, 1)]


def source_cell_ids(cells: list[dict], prefixes: list[dict]) -> list[str]:
    """Map supplied cells to stable source coordinates."""
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
    from app.application.reviewed_excel_evidence import MAX_MODEL_CELLS

    if not cells or len(cells) + len(drawings) > MAX_MODEL_CELLS:
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
            "maxItems": min(MAX_DRAWING_IDS_PER_REGION, max(100, len(drawing_ids))),
            "items": {"type": "string", "enum": drawing_ids},
        }
        region["required"].append("drawing_ids")
    return presented, references, schema


def _atom_contract(payload: dict, schema: dict, review: dict) -> tuple[dict, dict]:
    """Select source atoms; geometry is decoded once, never repaired from model coordinates."""
    payload["cells"], references, schema = reference_contract(
        payload["cells"], schema, sheets=payload["sheets"]
    )
    source = {(c["sheet"], c["cell"]) for c in review.get("full_cells", review["cells"])}
    prefixes = {row["sheet"]: row["prefix"] for row in source_sheet_prefixes(payload["sheets"])}
    for cell in payload["cells"]:
        references[cell["evidence_id"]]["atom_range"] = cell.get("required_extent", cell["cell"])
    layouts, blank = [], []
    primary_sheets = {cell["sheet"] for cell in payload["cells"] if not cell.get("context_only")}
    for sheet in payload["sheets"]:
        for area in sheet["merged"]:
            identifier = "M" + prefixes[sheet["sheet"]][1:] + ":" + area
            layouts.append(identifier)
            references[identifier] = {
                "ref": {"sheet": sheet["sheet"], "range": area},
                "primary": False,
                "layout": True,
                "atom_range": area,
                "blank": (sheet["sheet"], area.split(":", 1)[0]) not in source,
            }
            if references[identifier]["blank"] and sheet["sheet"] in primary_sheets:
                blank.append(identifier)
    region = schema["properties"]["physical_regions"]["items"]
    props = region["properties"]
    for key in ("sheet", "range", "evidence_ids"):
        props.pop(key)
    props["atom_ids"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": len(props["primary_id"]["enum"]) + len(blank),
        "items": {"type": "string", "enum": list(props["primary_id"]["enum"]) + blank},
    }
    region["required"] = ["atom_ids", "primary_id", "dependency_ids", "reason"]
    schema["properties"]["logical_documents"]["items"]["properties"]["fragments"]["items"] = {
        "type": "string"
    }
    schema["properties"]["layout_references"] = {
        "type": "array",
        "maxItems": 100 if layouts else 0,
        "items": {"type": "string", **({"enum": layouts} if layouts else {})},
    }
    return references, schema


def _boundary_contract(payload: dict, schema: dict, review: dict) -> tuple[dict, dict]:
    _, references, _ = reference_contract(payload["cells"], schema, sheets=payload["sheets"])
    return references, source_ranges_schema(payload["sheets"])


def normalize_reference_ids(
    data: dict,
    references: dict,
    id_schema: dict,
    original_schema: dict,
    *,
    review: dict | None = None,
) -> dict:
    """Fail closed on unknown IDs or primary evidence outside the proposed region."""
    from app.application.reviewed_excel_template import _validate_template_schema

    if not _validate_template_schema(id_schema, data):
        raise ReviewedExcelError("模型证据编号不在本批白名单")
    if "documents" in id_schema["properties"]:
        if review is None:
            raise ReviewedExcelError("边界核验缺少原件上下文")
        normalized = _normalize_boundaries(data, references, review)
        if not _validate_template_schema(original_schema, normalized):
            raise ReviewedExcelError("原分类schema校验失败")
        return normalized
    if "atom_ids" in id_schema["properties"]["physical_regions"]["items"]["properties"]:
        if review is None:
            raise ReviewedExcelError("源原子解码缺少原件核验上下文")
        normalized = _normalize_atom_ids(data, references, review)
        if not _validate_template_schema(original_schema, normalized):
            raise ReviewedExcelError("原分类schema校验失败")
        return normalized
    normalized = deepcopy(data)
    for region in normalized["physical_regions"]:
        # Internal compatibility label, not model output.
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


def prepare_reference_messages(
    messages: list[dict], schema: dict, *, review: dict
) -> tuple[dict, dict]:
    import json

    neutralize_messages(messages)
    payload = json.loads(messages[1]["content"])
    if not payload.get("drawing_evidence"):
        references, provider_schema = _boundary_contract(payload, schema, review)
    else:
        payload["cells"], references, provider_schema = reference_contract(
            payload["cells"], schema, payload.get("drawing_evidence"), sheets=payload["sheets"]
        )
    if payload.get("drawing_evidence"):
        payload["drawing_evidence"] = [
            {**drawing, "drawing_id": f"D{index:04d}"}
            for index, drawing in enumerate(payload["drawing_evidence"], 1)
        ]
    if "documents" not in provider_schema["properties"]:
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
        DRAWING_IDENTIFY_PROMPT
        if payload.get("drawing_evidence")
        else (
            ATOM_IDENTIFY_PROMPT
            if "physical_regions" in provider_schema["properties"]
            and "atom_ids"
            in provider_schema["properties"]["physical_regions"]["items"]["properties"]
            else IDENTIFY_PROMPT
        )
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
    if "documents" in raw:
        summary["reference_response"] = raw
        summary["source_coverage"] = deepcopy(references["_source_coverage"])
        summary["reference_index"] = {
            key: entry for key, entry in references.items() if key != "_source_coverage"
        }
        return
    used = {
        identifier
        for region in raw["physical_regions"]
        for identifier in [
            region["primary_id"],
            *region.get("atom_ids", region.get("evidence_ids", [])),
            *region["dependency_ids"],
            *region.get("drawing_ids", []),
        ]
    }
    if "atom_ids" in raw["physical_regions"][0]:
        used.update(raw["layout_references"])
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
            {
                **(
                    {"evidence_id": cell["evidence_id"]}
                    if "evidence_id" in cell
                    else {"sheet": cell["sheet"], "cell": cell["cell"]}
                ),
                "references": references,
                "unresolved": unresolved,
            }
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

def contract_hashes(schema: dict, phase: str) -> dict:
    """Hash the stable schema template; replace only IDs mechanically sourced from this input."""
    template = deepcopy(schema)
    if "documents" in template["properties"]:
        props = template["properties"]["documents"]["items"]["properties"]["ranges"]["items"][
            "properties"
        ]
        props["sheet_name"]["enum"] = ["<SOURCE_SHEET_NAMES>"]
        for axis, limit in (("row", 1048576), ("column", 16384)):
            maximum = props[f"{axis}_start"]["maximum"]
            if (
                maximum != props[f"{axis}_end"]["maximum"]
                or type(maximum) is not int
                or type(props[f"{axis}_end"]["maximum"]) is not int
                or not 1 <= maximum <= limit
            ):
                raise ValueError("source dimension bounds disagree")
            props[f"{axis}_start"]["maximum"] = 1
            props[f"{axis}_end"]["maximum"] = 1
        prompt = IDENTIFY_PROMPT if phase == "identify" else RANGE_GROUP_PROMPT
        canonical = json.dumps(template, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return {
            "version": CONTRACT_VERSION,
            "phase": phase,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "schema_template_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    if phase == "identify":
        props = template["properties"]["physical_regions"]["items"]["properties"]
        if "atom_ids" in props:
            atoms = props["atom_ids"]["items"]["enum"]
            primary = props["primary_id"]["enum"]
            if not isinstance(atoms, list) or not set(primary) <= set(atoms):
                raise ValueError("atom contract lacks source primary cells")
            if type(props["atom_ids"]["maxItems"]) is not int or props["atom_ids"][
                "maxItems"
            ] != len(atoms):
                raise ValueError("atom selection bound must match its source whitelist")
            props["atom_ids"]["maxItems"] = 0  # Source-count placeholder, never a provider schema.
            if any(key not in primary and not key.startswith("M") for key in atoms):
                raise ValueError("atom contract contains non-primary cell identities")
            props["atom_ids"]["items"]["enum"] = ["<PRIMARY_AND_BLANK_MERGE_ATOMS>"]
            props["dependency_ids"]["items"]["enum"] = ["<SOURCE_EVIDENCE_IDS>"]
            props["primary_id"]["enum"] = ["<PRIMARY_EVIDENCE_IDS>"]
            layout = template["properties"]["layout_references"]
            if type(layout["maxItems"]) is not int or layout["maxItems"] not in (0, 100):
                raise ValueError("invalid layout source bound")
            if layout["maxItems"] == 0:
                if "enum" in layout["items"]:
                    raise ValueError("empty layout source has unexpected enum")
                layout["maxItems"] = 100
            elif not isinstance(layout["items"].get("enum"), list) or not layout["items"]["enum"]:
                raise ValueError("layout source enum is missing")
            if not (set(atoms) - set(primary)) <= set(layout["items"].get("enum", [])):
                raise ValueError("layout atoms must reference source merges")
            layout["items"]["enum"] = ["<SOURCE_MERGE_IDS>"]
            prompt = ATOM_IDENTIFY_PROMPT
        else:
            if props["evidence_ids"]["items"]["enum"] != props["primary_id"]["enum"]:
                raise ValueError("classification evidence must use the primary source whitelist")
            props["sheet"]["enum"] = ["<SOURCE_SHEETS>"]
            props["evidence_ids"]["items"]["enum"] = ["<PRIMARY_EVIDENCE_IDS>"]
            props["dependency_ids"]["items"]["enum"] = ["<SOURCE_EVIDENCE_IDS>"]
            props["primary_id"]["enum"] = ["<PRIMARY_EVIDENCE_IDS>"]
            if "drawing_ids" in props:
                props["drawing_ids"]["items"]["enum"] = ["<SOURCE_DRAWING_IDS>"]
                if type(props["drawing_ids"].get("maxItems")) is not int or not (
                    100 <= props["drawing_ids"]["maxItems"] <= MAX_DRAWING_IDS_PER_REGION
                ):
                    raise ValueError("invalid drawing_ids source bound")
                props["drawing_ids"]["maxItems"] = 100  # template placeholder; live bound is source-sized
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
                or any(
                    not isinstance(value, str) or not value for value in layout_props[key]["enum"]
                )
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
            if type(props["drawing_ids"].get("maxItems")) is not int or not (
                100 <= props["drawing_ids"]["maxItems"] <= MAX_DRAWING_IDS_PER_REGION
            ):
                raise ValueError("invalid drawing_ids source bound")
            props["drawing_ids"]["maxItems"] = 100  # template placeholder; live bound is source-sized
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
        "891b2e2a660d06b1fd5f70bac345165d6d05fa8c8c826d0194646cf7d4b5a5f4",
        "06548a8c4a41b87333a2e19dba43320f23ead21993ff7884ff884c54c60699e2",
    ),
    "group_ranges": (
        "92c5797d18ab9e1a4f862890f98a03b55d1103c2f138586b90735a5be9322774",
        "06548a8c4a41b87333a2e19dba43320f23ead21993ff7884ff884c54c60699e2",
    ),
    "identify_atoms": (
        "681768c2961ea4575978ab01ab904f2e39d8ee7b3f7b28f5de690703425f0ce0",
        "ffab0241efd5e7fba5087b4ca32774b3ba3b2ccb95124709f624d095ddd0adc0",
    ),
    "group": (
        "b1f917464cda760f733f99e88487bf32c4f59e053f42d4ac9e0e32dca4f365b0",
        "f0f500cbbf7f3925cae7f6885e51a46c92cb4069a8ded998c2724fdc4ba5f379",
    ),
    "identify_drawing": (
        "c538accb443bc1fa957bfc05142df52ee32f4fb3e54f1f8084630837225074bb",
        "15de0f5d41027cf4d1e6034fad68e704e3377763a0e91e37c3dda8509314209b",
    ),
    "group_drawing": (
        "09c3a75a5ca5cb4fa67db361f0c018c496e55c913ba9097fd06f34d0c62bd097",
        "47042d8477ddf0eb59819d512ead64c7213fc4210351687df0bedea6403129df",
    ),
}


def verify_contract(prompt: str, schema: dict, phase: str) -> dict:
    from app.application.etl.errors import ReviewedExcelError

    try:
        hashes = contract_hashes(schema, phase)
        actual_prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        if "documents" in schema["properties"]:
            key = "identify" if phase == "identify" else "group_ranges"
        else:
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
            if (
                phase == "identify"
                and "atom_ids" in schema["properties"]["physical_regions"]["items"]["properties"]
            ):
                key = "identify_atoms"
        if (actual_prompt_hash, hashes["schema_template_sha256"]) != _EXPECTED[key]:
            raise ReviewedExcelError("模型输入契约已改变，未调用模型")
    except (KeyError, TypeError, ValueError):
        raise ReviewedExcelError("模型输入契约无效，未调用模型") from None
    return hashes
