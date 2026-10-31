"""Source-range contracts and archived evidence-ID compatibility."""

import hashlib
import json
from copy import deepcopy

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.etl.errors import ReviewedExcelError
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
            "maxItems": 100,
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


CONTRACT_VERSION = "independent-excel-v10-document-ranges"
SOURCE_PROTOCOL = (
    "Identify physical fragments and group them into logical documents using only the supplied source cells and structure. "
    "Do not assume a document count or infer a business boundary from a transport batch or sheet boundary. "
    "sheets[].sheet_state may be visible, hidden, or veryHidden: prefer leaving fragments on hidden or veryHidden sheets ungrouped and out of logical_documents for independent extraction unless the operator explicitly requires those sheets; never invent workbook-title-specific rules. "
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
LEGACY_IDENTIFY_PROMPT = SOURCE_PROTOCOL + (
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
ATOM_IDENTIFY_PROMPT = (
    "Partition supplied primary source atoms into rectangular physical fragments, then optionally group those fragments into logical documents. "
    "Source atoms are geometry facts, never business candidates or document-count hints. "
    "Each cells[].evidence_id names a source cell; its extent is required_extent when present, otherwise that one cell. "
    "M-prefixed layout IDs encode the matching S-prefixed source sheet and exact merged range; use only IDs in the relevant schema whitelist. "
    "The atom_ids whitelist contains primary cells and explicitly available blank-merge layout atoms, not context cells. "
    "Return only atom IDs, never sheet/range coordinates. For each physical region select atom_ids and choose primary_id from its selected non-context cell atoms. "
    "Its rectangle is defined once as the smallest bounding rectangle of the selected atoms' complete source extents. "
    "Ordinary source blank cells inside that rectangle are allowed; no padding outside those bounds is added. "
    "Every nonempty source cell inside the rectangle must be a selected primary atom of that same region. "
    "Never bridge an unselected cell, context_only cell or unread content. Any intersected merged range must be entirely contained. "
    "Invalid selections are rejected, never expanded, repaired or automatically regrouped. "
    "Use multiple physical regions for nonrectangular content, not an enclosing box that absorbs other content. "
    "Assign every primary cell atom exactly once; do not duplicate atoms across or within regions, and do not overlap rectangles. "
    "Each region must have its own primary_id; blank layout alone cannot form a region. "
    "dependency_ids may name supplied cell evidence, including context_only, but formula targets and metadata do not create additional evidence IDs. "
    "logical_documents.fragments contains the primary_id values of returned physical regions, each region at most once; "
    "document_id must be nonblank, unique and at most 80 characters. Leave uncertain fragments ungrouped. "
    "layout_references is an optional subset of supplied M-prefixed merge IDs, not a coverage ledger; [] is valid. "
    "sheets[].sheet_state may be visible, hidden, or veryHidden: prefer not creating physical regions or logical_documents on hidden or veryHidden sheets; leave that content ungrouped unless explicitly required; never invent workbook-title-specific rules. "
    "Transport batches, sheet boundaries, adjacency and repeated headers do not establish a business document. "
    "Return exactly one JSON object matching output_schema with no extra fields."
)
IDENTIFY_PROMPT = (
    "Split source content into documents, each with one or more exact rectangular ranges. "
    "Return real sheet_name and inclusive integer row_start,row_end,column_start,column_end; do not invent or report IDs. "
    "Each rectangle means ALL original nonempty cells within its boundaries. The server reads the source to verify every supplied primary cell is covered exactly once. "
    "Never include context_only or unread nonempty content, overlap ranges even on blanks, cut any source merge, or exceed source sheet dimensions. "
    "Every intersected merge must be wholly contained. Internal blanks are allowed; blank-only ranges are not. "
    "Invalid ranges are rejected, never clipped, expanded or repaired. Formula targets and merge metadata are source facts, not additional supplied cells or business boundaries. "
    "Use multiple ranges in one document only when the source supports that relationship. Technical batches are not documents. "
    "Sheet boundaries, adjacency and repeated headers alone do not prove one business document. "
    "Prefer omitting hidden or veryHidden sheets (sheets[].sheet_state) from documents unless explicitly required; never invent workbook-title-specific rules. "
    "Export fidelity: when a document contains filter-aware aggregate formulas (for example SUBTOTAL), "
    "every cell those formulas reference on the same sheet must lie inside that document's rectangles; "
    "if the sheet carries an active AutoFilter, include that AutoFilter's full reference rectangle in the same document "
    "(add another rectangle if needed). Prefer self-contained period/documents over leaving such dependencies outside. "
    "Decide from supplied cell values and sheet facts only; never invent coordinates that are not justified by that evidence. "
    "No cleaning, numbering, printing or template decisions. Return exactly output_schema."
)
RANGE_GROUP_PROMPT = (
    "Group the supplied validated ranges into complete documents using source content. Return documents with nested ranges and reasons, no IDs. "
    "Copy each supplied sheet_name and integer boundary tuple exactly once across all documents; never expand, shrink, duplicate or omit a range. "
    "cells, fragment_structure and cross_fragment_formulas provide middle-row samples and cross-fragment formula facts; use them to judge continuity. "
    "Do not auto-merge merely because ranges are adjacent or share a sheet; only group when supplied content supports one business document. "
    "Prefer omitting ranges on hidden or veryHidden sheets unless explicitly required. "
    "sheet_filters (when present) lists each sheet's active AutoFilter reference rectangle as a source fact. "
    "Export fidelity: if cross_fragment_formulas show a filter-aware aggregate (for example SUBTOTAL) whose referenced cells sit in another fragment, "
    "put the hosting fragment and every referenced fragment in the same document so those dependencies stay inside one export. "
    "If a document would keep SUBTOTAL (or similar filter-aware aggregates) but omit the sheet_filters rectangle that covers them, "
    "also group in the fragment that covers that AutoFilter reference when one was supplied. "
    "fragment_structure.has_filter_aware_aggregates and covers_sheet_filter are source facts for that decision. "
    "Technical batches are not document boundaries. Adjacency, sheet membership and repeated headers alone do not prove document identity. "
    "This step groups existing ranges only; do not change source data or make cleaning, numbering, printing or template decisions. Return exactly output_schema."
)
DRAWING_IDENTIFY_PROMPT = LEGACY_IDENTIFY_PROMPT + (
    " When drawing_evidence is present, use only supplied drawing_id values in drawing_ids. "
    "Drawing text and anchors are source evidence; last_col and last_row are conservative outer bounds resolved from worksheet dimension records when available — geometry facts, not document suggestions. "
    "Every drawing must be wholly inside one region; do not cut objects horizontally or vertically. "
    "Choose two-dimensional rectangles independently; transport batches do not prescribe document boundaries."
)
GROUP_PROMPT = (
    "Group only fragments that belong to the same business document. "
    "A standalone fragment can be one group. Do not group merely because fragments are adjacent, "
    "have similar headers, or share a category. Leave uncertain fragments ungrouped. "
    "Prefer not forcing groups whose only purpose is to extract hidden or veryHidden sheets. "
    "For every grouped fragment cite at least one sent cell within it and explain the relationship "
    "using sent values. Use only supplied region_id and evidence_id values. "
    "Fragment boundaries are fixed; do not invent ranges or cells. "
    "If supplied evidence shows a filter-aware aggregate formula (for example SUBTOTAL) whose referenced "
    "cells live in another fragment, group those fragments together so the dependency stays in one document. "
    "When sheet_filters are supplied, keep AutoFilter-covered fragments with any grouped SUBTOTAL that needs that filter. "
    "Return exactly one JSON object matching output_schema."
)
DRAWING_GROUP_PROMPT = GROUP_PROMPT + (
    " When drawing_evidence is present, cite only supplied drawing_id values in drawing_ids; "
    "each cited object must be wholly contained in one of the group's fixed fragments."
)


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
        "fe750f97254a7bdce2c8158d6dbb4e861c163b96694d2d46a7fbbdea3f265a28",
        "06548a8c4a41b87333a2e19dba43320f23ead21993ff7884ff884c54c60699e2",
    ),
    "group_ranges": (
        "2e5113ae50e6445b3086adfd58d6ade3175c4dbc049de43c1af983dd5b8e33a6",
        "06548a8c4a41b87333a2e19dba43320f23ead21993ff7884ff884c54c60699e2",
    ),
    "identify_atoms": (
        "fbe19d61e212772c1763d41a4efeb310e61bbfdbf08f110e58397671f8003972",
        "ffab0241efd5e7fba5087b4ca32774b3ba3b2ccb95124709f624d095ddd0adc0",
    ),
    "group": (
        "30bc484b520ebfb64779fa59828491d73cfc6d074c632e0025764c83861378fb",
        "f0f500cbbf7f3925cae7f6885e51a46c92cb4069a8ded998c2724fdc4ba5f379",
    ),
    "identify_drawing": (
        "7a778c6b35f388c06960bbeb0713c06e4fce748de13ac907f9ca7cba98e12480",
        "15de0f5d41027cf4d1e6034fad68e704e3377763a0e91e37c3dda8509314209b",
    ),
    "group_drawing": (
        "1d064115ea3043d4b868dcd33c51bb6c5150e11367b465352fe375972d84c172",
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
