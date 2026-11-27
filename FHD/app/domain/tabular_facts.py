"""Versioned, format-neutral facts; identifiers are evidence links, not grants."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, NotRequired, TypedDict

SCHEMA_VERSION = "tabular-facts-v1"
FactStatus = Literal["complete", "partial", "blocked", "unsupported"]


class SourceRef(TypedDict):
    source_sha256: str
    source_format: str
    parser: str
    parser_version: str
    authorization_scope: str


class CellFact(TypedDict, total=False):
    cell_id: str
    address: str
    row: int
    column: int
    value: Any
    value_type: str
    value_state: Literal["present", "empty_string", "blank", "unknown"]
    data_type: str
    formula: str | None
    cached_value: Any
    cache_state: str
    style_id: str
    source_ref: dict[str, Any]


class RegionFact(TypedDict, total=False):
    region_id: str
    source_ref: dict[str, Any]
    role: str
    evidence_state: Literal["fact", "inference", "unknown", "not_applicable"]
    confidence: float | None
    native_extensions: dict[str, Any]


class TableFact(RegionFact, total=False):
    table_id: str
    cells: list[CellFact]
    basis: str


class SheetFacts(TypedDict, total=False):
    sheet_id: str
    sheet: str
    sheet_state: str
    cells: list[CellFact]
    status: FactStatus
    source_ref: dict[str, Any]
    native_objects: dict[str, Any]


class PageFacts(TypedDict, total=False):
    page_id: str
    page: int
    source_ref: dict[str, Any]
    regions: list[RegionFact]
    status: FactStatus
    native_extensions: dict[str, Any]


class StyleFact(TypedDict, total=False):
    font: dict[str, Any]
    fill: dict[str, Any]
    border: dict[str, Any]
    alignment: dict[str, Any]
    number_format: str


class DocumentFacts(TypedDict):
    schema_version: str
    document_id: str
    source_ref: SourceRef
    status: FactStatus
    capabilities: dict[str, Any]
    sheets: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    styles: dict[str, Any]
    warnings: list[dict[str, Any]]
    native_extensions: NotRequired[dict[str, Any]]


def make_source_ref(
    *,
    source_sha256: str,
    source_format: str,
    parser: str,
    parser_version: str,
    authorization_scope: str = "",
) -> SourceRef:
    """Bind a parser contract to an already-authorized immutable snapshot.

    An empty scope is permitted for local inspection, but conveys no authority
    and must never be promoted to a reusable account-scoped cache entry.
    """
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if not all(
        isinstance(value, str)
        for value in (source_format, parser, parser_version, authorization_scope)
    ):
        raise ValueError("source identity fields must be strings")
    if not source_format or not parser or not parser_version:
        raise ValueError("source format and parser identity are required")
    return {
        "source_sha256": source_sha256,
        "source_format": source_format,
        "parser": parser,
        "parser_version": parser_version,
        "authorization_scope": authorization_scope,
    }


def location_id(document_id: str, kind: str, *location: Any) -> str:
    """Unambiguous identity: native coordinates remain format-specific."""
    identity = json.dumps([document_id, kind, *location], ensure_ascii=False, separators=(",", ":"))
    return f"{kind}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def new_document(source_ref: SourceRef) -> DocumentFacts:
    source = make_source_ref(**source_ref)
    document_id = location_id(SCHEMA_VERSION, "document", source)
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": document_id,
        "source_ref": source,
        "status": "complete",
        "capabilities": {"authorization": "bound" if source["authorization_scope"] else "unbound"},
        "sheets": [],
        "pages": [],
        "regions": [],
        "tables": [],
        "styles": {},
        "warnings": [],
    }
