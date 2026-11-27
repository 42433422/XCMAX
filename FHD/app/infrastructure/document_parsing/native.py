"""Native document facts, using the existing parsers and the shared tabular contract.

This is a read-only adapter for an already authorized local snapshot. It does not
fetch links, run macros/scripts, send text to a model, or infer business meaning.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from app.domain.tabular_facts import location_id, make_source_ref, new_document
from app.infrastructure.document_parsing.delimited import delimited_reader

NATIVE_SUFFIXES = frozenset(
    {".csv", ".tsv", ".json", ".xml", ".docx", ".pptx", ".pdf", ".html", ".htm"}
)
MAX_SOURCE_BYTES = 40 * 1024 * 1024
MAX_NATIVE_ITEMS = 200_000
MAX_GROUP_DEPTH = 64
_BACKENDS = {
    ".docx": "python-docx",
    ".pptx": "python-pptx",
    ".pdf": "pdfplumber",
    ".html": "lxml",
    ".htm": "lxml",
    ".xml": "defusedxml",
}


def _source(document: dict, **location: Any) -> dict:
    return {"document_id": document["document_id"], **location}


def _partial(document: dict, reason: str) -> None:
    document["status"] = "partial"
    warning = {"code": reason}
    if warning not in document["warnings"]:
        document["warnings"].append(warning)


def _cell(document: dict, value: Any, **location: Any) -> dict:
    ref = _source(document, **location)
    return {
        "cell_id": location_id(
            document["document_id"], "cell", json.dumps(location, sort_keys=True)
        ),
        "value": value,
        "value_type": type(value).__name__,
        "value_state": "blank" if value is None else "empty_string" if value == "" else "present",
        "source_ref": ref,
    }


def _table(document: dict, cells: list[dict], **location: Any) -> dict:
    table = {
        "table_id": location_id(
            document["document_id"], "table", json.dumps(location, sort_keys=True)
        ),
        "cells": cells,
        "source_ref": _source(document, **location),
        "semantic_state": "unknown",
    }
    document["tables"].append(table)
    return table


def _delimited(document: dict, raw: bytes, suffix: str) -> None:
    handle, reader, dialect = delimited_reader(raw, suffix=suffix)
    cells: list[dict] = []
    records = []
    previous_line = 0
    try:
        for row, values in enumerate(reader, 1):
            if len(cells) + len(values) > MAX_NATIVE_ITEMS:
                _partial(document, "native_item_budget_exceeded")
                break
            line_end = reader.line_num
            records.append(
                {
                    "record": row,
                    "line_start": previous_line + 1,
                    "line_end": line_end,
                    "width": len(values),
                }
            )
            cells.extend(
                _cell(
                    document,
                    value,
                    record=row,
                    column=column,
                    line_start=previous_line + 1,
                    line_end=line_end,
                )
                for column, value in enumerate(values, 1)
            )
            previous_line = line_end
    finally:
        handle.close()
    _table(document, cells, section="records").update(
        {"records": records, **dialect, "header_state": "uninterpreted"}
    )
    document["capabilities"].update(
        {"quoted_newlines": True, "duplicate_headers": True, "native_styles": "not_applicable"}
    )


def _json(document: dict, raw: bytes) -> None:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON value: {value}")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict:
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key is ambiguous: {key}")
            value[key] = item
        return value

    value = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=object_pairs)
    # Keep arrays/objects and scalar types verbatim, including empty containers.
    document["regions"].append(
        {
            "region_id": location_id(document["document_id"], "json", ""),
            "kind": "json_tree",
            "value": value,
            "source_ref": _source(document, json_pointer=""),
        }
    )
    document["capabilities"]["nested_structure"] = True


def _xml(document: dict, raw: bytes) -> None:
    from defusedxml.ElementTree import fromstring

    root = fromstring(raw, forbid_dtd=True)
    count = 0

    def node(element, path: str, depth: int) -> dict:
        nonlocal count
        count += 1
        if count > MAX_NATIVE_ITEMS or depth > 128:
            raise ValueError("XML structure exceeds the node/depth budget")
        return {
            "tag": element.tag,
            "attributes": dict(element.attrib),
            "text": element.text,
            "tail": element.tail,
            "source_ref": _source(document, xml_path=path),
            "children": [
                node(child, f"{path}/{child.tag}[{index}]", depth + 1)
                for index, child in enumerate(element, 1)
            ],
        }

    document["regions"].append(
        {
            "region_id": location_id(document["document_id"], "xml", root.tag),
            "kind": "xml_tree",
            "value": node(root, f"/{root.tag}[1]", 0),
            "source_ref": _source(document, xml_path=f"/{root.tag}[1]"),
        }
    )
    document["capabilities"]["nested_structure"] = True


def _docx(document: dict, raw: bytes) -> None:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table, _Cell
    from docx.text.paragraph import Paragraph

    doc = Document(BytesIO(raw))
    count = 0

    def blocks(element, parent, path: str, depth: int = 0) -> None:
        nonlocal count
        if depth > 64:
            raise ValueError("DOCX nesting exceeds the structure budget")
        for ordinal, child in enumerate(element, 1):
            count += 1
            if count > MAX_NATIVE_ITEMS:
                raise ValueError("DOCX structure budget exceeded")
            position = f"{path}/{child.tag.split('}')[-1]}[{ordinal}]"
            if child.tag == qn("w:p"):
                document["regions"].append(
                    {
                        "region_id": location_id(document["document_id"], "paragraph", position),
                        "kind": "paragraph",
                        "text": Paragraph(child, parent).text,
                        "source_ref": _source(document, part=position),
                    }
                )
            elif child.tag == qn("w:tbl"):
                table = Table(child, parent)
                cells: list[dict] = []
                for row_index, row in enumerate(child.tr_lst, 1):
                    before = row.find("./" + qn("w:trPr") + "/" + qn("w:gridBefore"))
                    column = int(before.get(qn("w:val"), "0")) + 1 if before is not None else 1
                    for cell_index, tc in enumerate(row.tc_lst, 1):
                        count += 1
                        if count > MAX_NATIVE_ITEMS:
                            raise ValueError("DOCX cell budget exceeded")
                        source = f"{position}/tr[{row_index}]/tc[{cell_index}]"
                        cell = _Cell(tc, table)
                        span = tc.grid_span
                        facts = _cell(
                            document, cell.text, part=source, row=row_index, column=column
                        )
                        facts.update(
                            {
                                "column_span": span,
                                "vertical_merge": tc.vMerge,
                                "row_span_state": "native_vMerge",
                            }
                        )
                        cells.append(facts)
                        if tc.tbl_lst:
                            blocks(tc, cell, source, depth + 1)
                        column += span
                _table(document, cells, part=position)
                document["regions"].append(
                    {
                        "region_id": location_id(document["document_id"], "block", position),
                        "kind": "table",
                        "source_ref": _source(document, part=position),
                    }
                )

    blocks(doc.element.body, doc, "word/document.xml/body")
    # Accessing section.header/footer can create absent parts in python-docx.
    # Read only relationships that actually exist in the admitted source.
    seen = set()
    for relation in doc.part.rels.values():
        if relation.is_external or not relation.reltype.endswith(("/header", "/footer")):
            continue
        part = relation.target_part
        name = str(part.partname)
        if name not in seen:
            seen.add(name)
            blocks(part.element, doc, name)
    document["capabilities"].update(
        {
            "native_tables": True,
            "nested_tables": True,
            "document_order": True,
            "rendered_page_geometry": "unsupported",
        }
    )
    if doc.element.xpath(".//w:drawing"):
        _partial(document, "embedded_drawings_not_interpreted")


def _pptx(document: dict, raw: bytes) -> None:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = Presentation(BytesIO(raw))
    item_count = 0

    def account_item() -> None:
        nonlocal item_count
        item_count += 1
        if item_count > MAX_NATIVE_ITEMS:
            raise ValueError("PPTX native item budget exceeded")

    def shapes(items, slide: int, parent: str, depth: int = 0) -> None:
        if depth > MAX_GROUP_DEPTH:
            raise ValueError("PPTX group nesting exceeds the depth budget")
        for shape in items:
            account_item()
            path = f"{parent}/{shape.shape_id}"
            source = {
                "page": slide,
                "shape_path": path,
                "bbox": [
                    int(shape.left),
                    int(shape.top),
                    int(shape.left + shape.width),
                    int(shape.top + shape.height),
                ],
                "coordinate_unit": "EMU",
                "coordinate_frame": parent,
            }
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                shapes(shape.shapes, slide, path, depth + 1)
            elif shape.has_table:
                cells = []
                for row, native_row in enumerate(shape.table.rows, 1):
                    for col, cell in enumerate(native_row.cells, 1):
                        account_item()
                        if cell.is_spanned:
                            continue
                        facts = _cell(document, cell.text, **source, row=row, column=col)
                        facts.update({"row_span": cell.span_height, "column_span": cell.span_width})
                        cells.append(facts)
                _table(document, cells, **source)
            elif shape.has_text_frame:
                document["regions"].append(
                    {
                        "region_id": location_id(document["document_id"], "shape", slide, path),
                        "kind": "text",
                        "text": shape.text,
                        "source_ref": _source(document, **source),
                    }
                )
            else:
                _partial(document, "non_text_shapes_not_interpreted")

    for slide_no, slide in enumerate(presentation.slides, 1):
        account_item()
        document["pages"].append(
            {
                "page_id": location_id(document["document_id"], "slide", slide_no),
                "page": slide_no,
                "width": int(presentation.slide_width)
                if presentation.slide_width is not None
                else None,
                "height": int(presentation.slide_height)
                if presentation.slide_height is not None
                else None,
                "coordinate_unit": "EMU",
            }
        )
        if presentation.slide_width is None or presentation.slide_height is None:
            _partial(document, "slide_size_unavailable")
        shapes(slide.shapes, slide_no, "slide")
        if slide.has_notes_slide:
            account_item()
            document["regions"].append(
                {
                    "kind": "speaker_notes",
                    "text": slide.notes_slide.notes_text_frame.text,
                    "source_ref": _source(document, page=slide_no, section="notes"),
                }
            )
    document["capabilities"].update(
        {"native_tables": True, "shape_coordinates": True, "rendered_pixels": "unsupported"}
    )


def _pdf(document: dict, raw: bytes) -> None:
    import pdfplumber
    from pdfminer.pdfexceptions import PDFException
    from pdfplumber.utils.exceptions import PdfminerException

    try:
        parsed = pdfplumber.open(BytesIO(raw))
    except (PDFException, PdfminerException) as exc:
        raise ValueError("PDF native parser rejected the source") from exc
    with parsed as pdf:
        if len(pdf.pages) > 500:
            _partial(document, "pdf_page_budget_exceeded")
        total_cells = 0
        for page_no, page in enumerate(pdf.pages[:500], 1):
            document["pages"].append(
                {
                    "page_id": location_id(document["document_id"], "page", page_no),
                    "page": page_no,
                    "width": page.width,
                    "height": page.height,
                    "coordinate_unit": "point",
                    "coordinate_origin": "top_left",
                }
            )
            words = page.extract_words()
            if len(document["regions"]) + len(words) > MAX_NATIVE_ITEMS:
                _partial(document, "pdf_word_budget_exceeded")
                return
            for word in words:
                document["regions"].append(
                    {
                        "kind": "word",
                        "text": word["text"],
                        "source_ref": _source(
                            document,
                            page=page_no,
                            bbox=[word["x0"], word["top"], word["x1"], word["bottom"]],
                        ),
                    }
                )
            if not words:
                _partial(document, f"page_{page_no}_requires_ocr")
            for table_no, table in enumerate(page.find_tables(), 1):
                cells = []
                values = table.extract()
                for row_no, row in enumerate(table.rows, 1):
                    for col_no, bbox in enumerate(row.cells, 1):
                        if bbox is None:
                            continue
                        cells.append(
                            _cell(
                                document,
                                values[row_no - 1][col_no - 1],
                                page=page_no,
                                table=table_no,
                                row=row_no,
                                column=col_no,
                                bbox=list(bbox),
                            )
                        )
                total_cells += len(cells)
                if total_cells > MAX_NATIVE_ITEMS:
                    _partial(document, "pdf_cell_budget_exceeded")
                    return
                _table(document, cells, page=page_no, table=table_no, bbox=list(table.bbox))
    document["capabilities"].update(
        {
            "native_text_geometry": True,
            "table_boundaries": "candidate",
            "scanned_tables": "requires_ocr",
            "semantic_recognition": "unknown",
        }
    )


def _html(document: dict, raw: bytes) -> None:
    from lxml import etree, html

    try:
        dom = html.fromstring(raw, parser=html.HTMLParser(no_network=True, recover=False))
    except (etree.ParserError, etree.XMLSyntaxError) as exc:
        raise ValueError("HTML parser rejected malformed or over-budget structure") from exc
    for index, _node in enumerate(dom.iter(), 1):
        if index > MAX_NATIVE_ITEMS:
            raise ValueError("HTML native item budget exceeded")
    tree = dom.getroottree()
    placement_work = 0
    for table_node in dom.xpath("self::table | .//table"):
        cells = []
        spans: list[tuple[int, int, int]] = []
        rows = [
            row
            for row in table_node.xpath(".//tr")
            if row.xpath("ancestor::table[1]")[0] is table_node
        ]
        for row_no, row in enumerate(rows, 1):
            # Expired rowspans cannot affect another row. Bound the work for
            # adversarial forests of still-active spans as well as native cells.
            placement_work += len(spans)
            if placement_work > MAX_NATIVE_ITEMS * 8:
                raise ValueError("HTML span placement budget exceeded")
            spans = [span for span in spans if span[0] >= row_no]
            occupied = sorted((start, end) for _end_row, start, end in spans)
            span_index = 0
            column = 1
            for native_cell in row.xpath("./th | ./td"):
                rowspan, colspan = (
                    int(native_cell.get("rowspan", "1")),
                    int(native_cell.get("colspan", "1")),
                )
                if not (1 <= rowspan <= 65536 and 1 <= colspan <= 16384):
                    raise ValueError("HTML cell span exceeds the structure budget")
                while span_index < len(occupied):
                    placement_work += 1
                    start, end = occupied[span_index]
                    if start >= column + colspan:
                        break
                    if end >= column:
                        column = end + 1
                    span_index += 1
                if placement_work > MAX_NATIVE_ITEMS * 8:
                    raise ValueError("HTML span placement budget exceeded")
                if column + colspan - 1 > 16384:
                    raise ValueError("HTML column extent exceeds the structure budget")
                cell = _cell(
                    document,
                    native_cell.text_content(),
                    node_path=tree.getpath(native_cell),
                    row=row_no,
                    column=column,
                )
                cell.update(
                    {"row_span": rowspan, "column_span": colspan, "native_tag": native_cell.tag}
                )
                cells.append(cell)
                if rowspan > 1:
                    spans.append((row_no + rowspan - 1, column, column + colspan - 1))
                column += colspan
        _table(document, cells, node_path=tree.getpath(table_node))
    document["regions"].append(
        {
            "kind": "html_dom",
            "html": etree.tostring(dom, encoding="unicode", method="html"),
            "source_ref": _source(document, node_path=tree.getpath(dom)),
        }
    )
    document["capabilities"].update(
        {"static_dom": True, "dynamic_rendering": "unsupported", "script_execution": False}
    )
    if dom.xpath("self::script | .//script"):
        _partial(document, "dynamic_content_not_executed")


def read_native_document(path: Path, *, authorization_scope: str = "") -> dict:
    """Extract facts from a caller-authorized file; no cross-request cache."""
    path = Path(path)
    suffix = path.suffix.lower()
    with path.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Native document exceeds the source byte budget")
    backend = _BACKENDS.get(suffix, "python-stdlib")
    version = (
        importlib.metadata.version(backend)
        if backend != "python-stdlib"
        else __import__("platform").python_version()
    )
    document: dict[str, Any] = dict(
        new_document(
            make_source_ref(
                source_sha256=hashlib.sha256(raw).hexdigest(),
                source_format=suffix.lstrip(".") or "unknown",
                parser=backend,
                parser_version=version,
                authorization_scope=authorization_scope,
            )
        )
    )
    document["capabilities"]["inference"] = "not_performed"
    if suffix not in NATIVE_SUFFIXES:
        document["status"] = "unsupported"
        document["warnings"].append({"code": "native_adapter_unsupported"})
        return document
    if suffix in {".docx", ".pptx"}:
        from app.infrastructure.document_parsing.archive_safety import inspect_office_archive

        inspect_office_archive(raw)
    if suffix in {".csv", ".tsv"}:
        _delimited(document, raw, suffix)
    else:
        {
            ".json": _json,
            ".xml": _xml,
            ".docx": _docx,
            ".pptx": _pptx,
            ".pdf": _pdf,
            ".html": _html,
            ".htm": _html,
        }[suffix](document, raw)
    return document
