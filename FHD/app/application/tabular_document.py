"""Bounded readback of native document facts through existing owned snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import zipfile
from collections.abc import Iterator
from typing import Any
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException

from app.domain.tabular_facts import location_id
from app.infrastructure.document_parsing.router import read_document_facts

MAX_PAGE_BYTES = 40_000
MAX_PAGE_ITEMS = 1_000
MAX_SCAN_ITEMS = 200_000
_PAGE_VERSION = "native-document-pages-v2"
_VIEWS = {
    "csv": {"tables", "cells"},
    "tsv": {"tables", "cells"},
    "json": {"regions"},
    "xml": {"regions"},
    "docx": {"regions", "tables", "cells"},
    "pptx": {"pages", "regions", "tables", "cells"},
    "pdf": {"pages", "regions", "tables", "cells"},
    "html": {"regions", "tables", "cells"},
    "htm": {"regions", "tables", "cells"},
}
_ID_KEYS = {"pages": "page_id", "regions": "region_id", "tables": "table_id", "cells": "cell_id"}


class DocumentPageError(ValueError):
    def __init__(self, code: str, *, status: str = "blocked", **details: Any) -> None:
        super().__init__(code)
        self.code, self.status, self.details = code, status, details


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _json_regions(document_id: str, value: Any, pointer: str = "") -> Iterator[dict]:
    container = isinstance(value, (dict, list))
    yield {
        "region_id": location_id(document_id, "json", pointer),
        "kind": "json_node",
        "value_type": type(value).__name__,
        "source_ref": {"document_id": document_id, "json_pointer": pointer},
        **({"child_count": len(value)} if container else {"value": value}),
        **({"value": value} if container and not value else {}),
    }
    children = (
        value.items()
        if isinstance(value, dict)
        else enumerate(value)
        if isinstance(value, list)
        else ()
    )
    for key, child in children:
        escaped = str(key).replace("~", "~0").replace("/", "~1")
        yield from _json_regions(document_id, child, pointer + "/" + escaped)


def _xml_regions(document_id: str, node: dict) -> Iterator[dict]:
    ref = node["source_ref"]
    yield {
        "region_id": location_id(document_id, "xml_node", ref["xml_path"]),
        "kind": "xml_node",
        **{key: value for key, value in node.items() if key != "children"},
        "child_count": len(node["children"]),
    }
    for child in node["children"]:
        yield from _xml_regions(document_id, child)


def _identified(document: dict, item: dict, view: str, ordinal: int) -> dict:
    ref = dict(item.get("source_ref") or {})
    ref["document_id"] = document["document_id"]
    if view == "pages":
        ref["page"] = item["page"]
    key = _ID_KEYS[view]
    return {
        **item,
        key: item.get(key)
        or location_id(document["document_id"], view, ordinal, json.dumps(ref, sort_keys=True)),
        "source_ref": ref,
    }


def _items(document: dict, view: str, table_id: str | None) -> Iterator[dict]:
    if view in {"tables", "cells"}:
        found = table_id is None
        for index, source in enumerate(document["tables"]):
            table = _identified(document, source, "tables", index)
            if table_id is not None and table["table_id"] != table_id:
                continue
            found = True
            cells = table.get("cells")
            if not isinstance(cells, list):
                raise DocumentPageError("document_table_cells_unavailable", status="unsupported")
            if view == "tables":
                omitted = [key for key in ("cells", "records", "native_object") if key in table]
                yield {
                    **{key: value for key, value in table.items() if key not in omitted},
                    "projection": "table_metadata",
                    "omitted_fields": omitted,
                    "cell_count": len(cells),
                    "readback": {
                        "view": "cells",
                        "table_id": table["table_id"],
                        "expected_sha256": document["source_ref"]["source_sha256"],
                    },
                }
            else:
                for cell_index, cell in enumerate(cells):
                    yield {
                        **_identified(document, cell, "cells", cell_index),
                        "table_id": table["table_id"],
                    }
        if not found:
            raise DocumentPageError("document_table_not_found")
        return
    for index, item in enumerate(document[view]):
        if view == "regions" and item.get("kind") == "json_tree":
            yield from _json_regions(document["document_id"], item["value"])
        elif view == "regions" and item.get("kind") == "xml_tree":
            yield from _xml_regions(document["document_id"], item["value"])
        else:
            yield _identified(document, item, view, index)


def _coordinates(cell: dict) -> tuple[int, int]:
    ref = cell["source_ref"]
    row, column = ref.get("row", ref.get("record")), ref.get("column")
    if any(type(value) is not int or not 1 <= value < 2**31 for value in (row, column)):
        raise DocumentPageError("document_native_cell_coordinates_unavailable")
    return row, column


def _parameters(arguments: dict) -> tuple[str, int, int, dict, str | None]:
    allowed = {
        "action",
        "file_path",
        "view",
        "offset",
        "max_rows",
        "expected_sha256",
        "cursor",
        "page",
        "table_id",
        "fact_id",
        "row_range",
        "native_columns",
    }
    if any(key not in allowed and value is not None for key, value in arguments.items()):
        raise DocumentPageError("document_argument_not_supported")
    view = arguments.get("view")
    if not isinstance(view, str) or view not in _ID_KEYS:
        raise DocumentPageError("invalid_document_view")
    offset, limit = arguments.get("offset", 0), arguments.get("max_rows", MAX_PAGE_ITEMS)
    if type(offset) is not int or not 0 <= offset <= MAX_SCAN_ITEMS:
        raise DocumentPageError("invalid_document_offset")
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_ITEMS:
        raise DocumentPageError("invalid_document_page_size")
    selection = {
        key: arguments.get(key)
        for key in ("page", "table_id", "fact_id", "row_range", "native_columns")
    }
    if selection["page"] is not None and (
        type(selection["page"]) is not int or selection["page"] < 1
    ):
        raise DocumentPageError("invalid_document_page_number")
    for key in ("table_id", "fact_id"):
        value = selection[key]
        if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 128):
            raise DocumentPageError("invalid_document_fact_id")
    if selection["table_id"] is not None and view != "cells":
        raise DocumentPageError("document_table_selector_requires_cells")
    for key in ("row_range", "native_columns"):
        value = selection[key]
        if value is None:
            continue
        if view != "cells" or not selection["table_id"]:
            raise DocumentPageError("document_range_requires_selected_table")
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= MAX_PAGE_ITEMS
            or any(type(item) is not int or not 1 <= item < 2**31 for item in value)
            or (key == "row_range" and (len(value) != 2 or value[0] > value[1]))
            or (key == "native_columns" and len(set(value)) != len(value))
        ):
            raise DocumentPageError("invalid_document_native_range")
    digest = arguments.get("expected_sha256")
    if digest is not None and (
        not isinstance(digest, str) or re.fullmatch("[0-9a-f]{64}", digest) is None
    ):
        raise DocumentPageError("invalid_document_source_sha256")
    if (
        offset or arguments.get("cursor") or selection["table_id"] or selection["fact_id"]
    ) and digest is None:
        raise DocumentPageError("document_readback_requires_source_sha256")
    if offset and not arguments.get("cursor"):
        raise DocumentPageError("document_page_requires_cursor")
    return view, offset, limit, selection, digest


def _cursor(binding: str, offset: int) -> str:
    return (
        base64.urlsafe_b64encode(_encoded({"v": 1, "binding": binding, "offset": offset}))
        .decode()
        .rstrip("=")
    )


def _resume(arguments: dict, binding: str, offset: int) -> int:
    cursor = arguments.get("cursor")
    if cursor is None:
        return offset
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 512:
        raise DocumentPageError("invalid_document_cursor")
    try:
        decoded = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
    except (ValueError, UnicodeError) as exc:
        raise DocumentPageError("invalid_document_cursor") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"v", "binding", "offset"}:
        raise DocumentPageError("invalid_document_cursor")
    if type(decoded["v"]) is not int or decoded["v"] != 1 or decoded["binding"] != binding:
        raise DocumentPageError("document_cursor_source_or_scope_changed")
    value = decoded["offset"]
    if type(value) is not int or not 0 <= value <= MAX_SCAN_ITEMS:
        raise DocumentPageError("invalid_document_cursor")
    if "offset" in arguments and offset != value:
        raise DocumentPageError("document_cursor_offset_mismatch")
    return value


def _validate_document(document: dict, view: str) -> set[str]:
    available = _VIEWS.get(document["source_ref"]["source_format"], set())
    if "tables" in available:
        available = available | {"table"}
    if document["status"] not in {"complete", "partial"}:
        raise DocumentPageError("document_structure_unavailable", status=document["status"])
    if any(
        str(warning.get("code", "")).endswith("_budget_exceeded")
        for warning in document["warnings"]
    ):
        # A finite projection cannot continue past the native parser's hard
        # stop. Keep OCR/interpretation partials, but never offer an empty or
        # apparently exhausted cursor for facts discarded by a resource cap.
        raise DocumentPageError("document_structure_budget_exceeded")
    if view not in available:
        raise DocumentPageError(
            "document_view_unsupported", status="unsupported", available_views=sorted(available)
        )
    return available


def _matching_items(document: dict, view: str, selection: dict) -> Iterator[dict]:
    page = selection["page"]
    if page is not None and not any(item.get("page") == page for item in document["pages"]):
        raise DocumentPageError("document_page_not_found")
    requested_columns = (
        set(selection["native_columns"]) if selection["native_columns"] is not None else None
    )
    found_columns = set()
    for scanned, item in enumerate(_items(document, view, selection["table_id"]), 1):
        if scanned > MAX_SCAN_ITEMS:
            raise DocumentPageError("document_readback_scan_budget_exceeded")
        if page is not None and item["source_ref"].get("page") != page:
            continue
        if selection["fact_id"] is not None and item[_ID_KEYS[view]] != selection["fact_id"]:
            continue
        if selection["row_range"] is not None or requested_columns is not None:
            row, column = _coordinates(item)
            found_columns.add(column)
            if requested_columns is not None and column not in requested_columns:
                continue
            if selection["row_range"] is not None and not (
                selection["row_range"][0] <= row <= selection["row_range"][1]
            ):
                continue
        yield item
    if requested_columns is not None and not requested_columns.issubset(found_columns):
        raise DocumentPageError("document_native_column_not_found")


def _project(document: dict, arguments: dict, file_path: str) -> dict:
    view, offset, limit, selection, _ = _parameters(arguments)
    _validate_document(document, view)
    return _paginate(
        document,
        arguments,
        file_path,
        view=view,
        selection=selection,
        source_items=_matching_items(document, view, selection),
        offset=offset,
        limit=limit,
    )


def _paginate(
    document: dict,
    arguments: dict,
    file_path: str,
    *,
    view: str,
    selection: dict,
    source_items: Iterator[dict],
    offset: int,
    limit: int,
    extra_data: dict | None = None,
) -> dict:
    binding = hashlib.sha256(
        _encoded(
            [_PAGE_VERSION, document["schema_version"], document["source_ref"], view, selection]
        )
    ).hexdigest()
    offset = _resume(arguments, binding, offset)
    data = {
        "view": view,
        "document_id": document["document_id"],
        "schema_version": document["schema_version"],
        "source_sha256": document["source_ref"]["source_sha256"],
        "source_ref": document["source_ref"],
        "source_status": document["status"],
        "partial": document["status"] != "complete",
        "capabilities": document["capabilities"],
        "warnings": document["warnings"],
        "available_views": sorted(_validate_document(document, view)),
        "selection": selection,
        "offset": offset,
        "known_total": MAX_SCAN_ITEMS,
        "count_scope": "extracted_facts",
        "returned_items": MAX_PAGE_ITEMS,
        "items": [],
        "has_more": False,
        "next_offset": MAX_SCAN_ITEMS,
        "next_cursor": _cursor(binding, MAX_SCAN_ITEMS),
        "response_budget_bytes": MAX_PAGE_BYTES,
        "source": {
            "file": file_path,
            "sha256": document["source_ref"]["source_sha256"],
            "sheet": None,
            "header_row": None,
        },
        **(extra_data or {}),
    }
    result = {
        "success": True,
        "file_path": file_path,
        "source_sha256": data["source_sha256"],
        "data": data,
    }
    remaining = MAX_PAGE_BYTES - len(_encoded(result))
    if remaining < 0:
        raise DocumentPageError("document_metadata_budget_exceeded")
    items: list[dict] = []
    total, stopped = 0, False
    for scanned, item in enumerate(source_items, 1):
        if scanned > MAX_SCAN_ITEMS:
            raise DocumentPageError("document_readback_scan_budget_exceeded")
        index = total
        total += 1
        if index < offset or stopped:
            continue
        if len(items) == limit:
            stopped = True
            continue
        size = len(_encoded(item)) + bool(items)
        if size > remaining:
            if not items:
                raise DocumentPageError(
                    "document_item_budget_exceeded",
                    fact_id=item[_ID_KEYS.get(view, "row_id")],
                    required_item_bytes=size,
                )
            stopped = True
            continue
        items.append(item)
        remaining -= size
    if selection.get("fact_id") is not None and total == 0:
        raise DocumentPageError("document_fact_not_found")
    if offset > total:
        raise DocumentPageError("document_offset_out_of_range")
    more = offset + len(items) < total
    next_offset = offset + len(items) if more else None
    data.update(
        items=items,
        known_total=total,
        returned_items=len(items),
        has_more=more,
        next_offset=next_offset,
        next_cursor=_cursor(binding, next_offset) if next_offset is not None else None,
    )
    if len(_encoded(result)) > MAX_PAGE_BYTES:
        raise DocumentPageError("document_response_budget_exceeded")
    return result


def read_document_facts_page(arguments: dict, runtime_context: dict) -> dict[str, Any]:
    """Public host entry: every read reopens the original authorized snapshot.

    No raw path, model-supplied scope, cursor, prior result or fact ID grants
    access. Existing Excel cell reads delegate unchanged within that same scope.
    """
    from app.application.elt.errors import EltError
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError

    try:
        original = arguments.get("file_path")
        if not isinstance(original, str) or not 1 <= len(original) <= 4096:
            raise DocumentPageError("invalid_document_file_reference")
        with workflow_file_snapshot(original, runtime_context) as snapshot:
            if snapshot.suffix in {".xlsx", ".xlsm", ".xls"} and arguments.get("view") == "cells":
                from app.application.tools.workflow import handle_excel_analysis

                result: dict[str, Any] = handle_excel_analysis(
                    {**arguments, "action": "read", "file_path": str(snapshot)}
                )
                if result.get("success") is True:
                    with snapshot.open("rb") as stream:
                        result["source_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                result["file_path"] = original
                result.pop("resolved_path", None)
                return result
            table_operation = "table_id" in arguments and (
                arguments.get("action", "read") != "read"
                or arguments.get("view", "table") == "table"
            )
            expected: str | None
            if table_operation:
                from app.application.tabular_document_table import (
                    analysis_parameters,
                    analyze_native_table,
                )

                _, _, _, expected = analysis_parameters(arguments)
            else:
                _, _, _, _, expected = _parameters(arguments)
            # The existing snapshot context has just verified this sealed grant
            # against the current account, tenant, Mod and live login session.
            scope = (
                "workflow-document:"
                + hashlib.sha256(
                    json.dumps(
                        runtime_context["_actor_authorization"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            )
            document = read_document_facts(
                snapshot, authorization_scope=scope, expected_sha256=expected
            )
            return (
                analyze_native_table(document, arguments, original)
                if table_operation
                else _project(document, arguments, original)
            )
    except DocumentPageError as exc:
        return {"success": False, "error_code": exc.code, "status": exc.status, **exc.details}
    except PermissionError as exc:
        return {
            "success": False,
            "error_code": "spreadsheet_access_denied",
            "status": "blocked",
            "message": str(exc),
        }
    except (AgentModAuthorizationError, EltError) as exc:
        return {
            "success": False,
            "error_code": "document_access_denied",
            "status": "blocked",
            "message": str(exc),
        }
    except ImportError:
        return {"success": False, "error_code": "document_backend_unavailable", "status": "blocked"}
    except (
        ValueError,
        OSError,
        zipfile.BadZipFile,
        DefusedXmlException,
        ParseError,
        RecursionError,
    ) as exc:
        code = (
            "document_source_changed"
            if str(exc) == "native_document_source_sha256_mismatch"
            else "document_facts_read_failed"
        )
        return {
            "success": False,
            "error_code": code,
            "status": "blocked",
            "message": str(exc)[:240],
        }
