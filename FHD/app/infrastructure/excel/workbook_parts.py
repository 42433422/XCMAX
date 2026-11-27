"""Locate native workbook sheets using the pinned openpyxl package metadata."""

from __future__ import annotations

import hashlib
import posixpath
from pathlib import Path
from typing import Any, cast
from zipfile import ZipExtFile, ZipFile

from defusedxml import ElementTree as SafeET
from openpyxl.packaging.manifest import Manifest
from openpyxl.packaging.relationship import RelationshipList, get_dependents, get_rels_path
from openpyxl.xml.constants import ARC_CONTENT_TYPES, ARC_WORKBOOK, REL_NS, XLSM, XLSX, XLTM, XLTX

from app.infrastructure.document_parsing.archive_safety import inspect_office_archive

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_WORKBOOK_TYPES = (XLTM, XLTX, XLSM, XLSX)


def _workbook_part(archive: ZipFile) -> str:
    # Manifest accepts ElementTree nodes; the shared Serialisable stub also
    # requires chart-only methods that this deserializer never calls.
    node = SafeET.fromstring(archive.read(ARC_CONTENT_TYPES))
    manifest = Manifest.from_tree(cast(Any, node))
    if manifest is None:
        raise OSError("File contains no valid content types manifest")
    # Use the native reader's ContentType precedence, including its compatibility
    # case for producers assigning the workbook type as an extension default.
    for content_type in _WORKBOOK_TYPES:
        part = manifest.find(content_type)
        if part is not None:
            return str(part.PartName)[1:]
    if any(item.ContentType in _WORKBOOK_TYPES for item in manifest.Default):
        return ARC_WORKBOOK
    raise OSError("File contains no valid workbook part")


def worksheet_parts(archive: ZipFile, *, require_complete: bool = False) -> dict[str, str]:
    """Map source sheet names to local parts; never fetch external relationships."""
    workbook_part = _workbook_part(archive)
    targets: dict[str, str] = {}
    for rel in SafeET.fromstring(archive.read(get_rels_path(workbook_part))):
        if rel.attrib.get("TargetMode") == "External":
            continue
        target, identity = rel.attrib.get("Target", ""), rel.attrib.get("Id")
        if not identity or not target or ":" in target:
            continue
        targets[identity] = posixpath.normpath(
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.join(posixpath.dirname(workbook_part), target)
        )
    sheets = list(SafeET.fromstring(archive.read(workbook_part)).iter(_NS + "sheet"))
    parts = {
        sheet.attrib["name"]: targets[sheet.attrib[_RID]]
        for sheet in sheets
        if sheet.attrib.get(_RID) in targets and sheet.attrib.get("name")
    }
    if require_complete and len(parts) != len(sheets):
        raise ValueError("workbook_sheet_relationship_unsupported")
    return parts


def printer_settings_facts(source: str | Path) -> dict[str, list[tuple[bool, str, str]]]:
    """Read native associations and opaque settings hashes, never printer commands.

    The pinned openpyxl PrintPageSetup reader deliberately strips binary links.
    Inspect the bounded original package before that conversion; part names and
    relationship IDs are not semantic identities and external targets are not read.
    """
    path = Path(source)
    inspect_office_archive(path)
    facts = {}
    with ZipFile(path) as archive:
        for sheet, part in worksheet_parts(archive, require_complete=True).items():
            bound = set()
            with archive.open(part) as stream:
                for _, element in SafeET.iterparse(
                    stream,
                    events=("end",),
                    forbid_dtd=True,
                    forbid_entities=True,
                    forbid_external=True,
                ):
                    if element.tag == _NS + "pageSetup" and element.get(_RID):
                        bound.add(element.attrib[_RID])
                    element.clear()
            rel_path = get_rels_path(part)
            if rel_path not in archive.namelist():
                if bound:
                    raise ValueError("workbook_printer_settings_relationship_missing")
                continue
            # get_dependents intentionally tolerates invalid definitions; first
            # validate with its native model so the write/QC guard fails closed.
            node = SafeET.fromstring(archive.read(rel_path))
            if RelationshipList.from_tree(cast(Any, node)) is None:
                raise ValueError("workbook_printer_settings_relationship_invalid")
            relations = list(get_dependents(archive, rel_path).find(REL_NS + "/printerSettings"))
            if bound - {item.Id for item in relations}:
                raise ValueError("workbook_printer_settings_relationship_invalid")
            entries = []
            for relation in relations:
                mode = relation.TargetMode or "Internal"
                if mode == "External":
                    fingerprint = relation.Target
                else:
                    with archive.open(relation.Target) as content:
                        fingerprint = hashlib.file_digest(
                            cast(ZipExtFile, content), "sha256"
                        ).hexdigest()
                entries.append((relation.Id in bound, mode, fingerprint))
            if entries:
                facts[sheet] = sorted(entries)
    return facts
