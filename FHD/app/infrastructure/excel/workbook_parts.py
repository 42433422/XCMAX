"""Locate native workbook sheets using the pinned openpyxl package metadata."""

from __future__ import annotations

import posixpath
from typing import Any, cast
from zipfile import ZipFile

from defusedxml import ElementTree as SafeET
from openpyxl.packaging.manifest import Manifest
from openpyxl.packaging.relationship import get_rels_path
from openpyxl.xml.constants import ARC_CONTENT_TYPES, ARC_WORKBOOK, XLSM, XLSX, XLTM, XLTX

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


def worksheet_parts(archive: ZipFile) -> dict[str, str]:
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
    return {
        sheet.attrib["name"]: targets[sheet.attrib[_RID]]
        for sheet in SafeET.fromstring(archive.read(workbook_part)).iter(_NS + "sheet")
        if sheet.attrib.get(_RID) in targets and sheet.attrib.get("name")
    }
