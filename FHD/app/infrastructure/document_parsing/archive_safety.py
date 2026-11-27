"""Bound Office ZIP/XML parsing before native readers allocate workbook objects.

Uses Python's ZIP metadata and defusedxml; this is a read-only resource guard,
not another document parser. Callers still own snapshot authorization. Nothing
is extracted, evaluated, fetched, or executed from the supplied package.
"""

from __future__ import annotations

import posixpath
import stat
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree.ElementTree import ParseError
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from openpyxl.packaging.relationship import get_rels_path
from openpyxl.utils.cell import range_boundaries
from openpyxl.xml.constants import XLSM, XLSX, XLTM, XLTX


class OfficeArchiveError(ValueError):
    """Explicit blocked input; callers must not substitute an empty result."""


def _metadata(archive: ZipFile, name: str):
    return SafeET.fromstring(
        archive.read(name), forbid_dtd=True, forbid_entities=True, forbid_external=True
    )


def _part_roles(archive: ZipFile, names: set[str]) -> tuple[set[str], set[str]]:
    """Resolve package metadata only; a suffix is not a native-reader boundary.

    Keep all declared roles, including duplicate metadata, conservatively. The
    native reader follows workbook sheet relationships even when Content_Types
    calls their payload binary, so those references are authoritative for the
    allocation guard. External targets are never fetched.
    """
    xml_parts = {name for name in names if name.lower().endswith((".xml", ".rels"))}
    worksheets = set()
    workbooks = {"xl/workbook.xml"} & names
    default_types: dict[str, set[str]] = {}
    override_types: dict[str, set[str]] = {}
    manifest = "[Content_Types].xml"
    if manifest in names:
        for item in _metadata(archive, manifest):
            kind = item.attrib.get("ContentType", "").lower()
            if item.tag.rsplit("}", 1)[-1] == "Default":
                default_types.setdefault(item.attrib.get("Extension", "").lower(), set()).add(kind)
            elif item.tag.rsplit("}", 1)[-1] == "Override":
                name = posixpath.normpath(item.attrib.get("PartName", "").lstrip("/"))
                override_types.setdefault(name, set()).add(kind)
    workbook_types = {kind.lower() for kind in (XLSX, XLSM, XLTX, XLTM)}
    for name in names:
        types = override_types.get(name, set()) | default_types.get(
            PurePosixPath(name).suffix.lstrip(".").lower(), set()
        )
        if any(
            kind.endswith("+xml")
            or kind
            in {
                "application/xml",
                "text/xml",
                "application/vnd.openxmlformats-officedocument.vmldrawing",
            }
            for kind in types
        ):
            xml_parts.add(name)
        if "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml" in types:
            worksheets.add(name)
        if types & workbook_types:
            workbooks.add(name)
    # Preserve the old conservative audit of orphan worksheet-named XML parts.
    worksheets.update(name for name in xml_parts if name.lower().startswith("xl/worksheets/"))
    for workbook in workbooks:
        relationships = get_rels_path(workbook)
        if relationships not in names:
            continue
        targets: dict[str, set[str]] = {}
        for rel in _metadata(archive, relationships):
            target = rel.attrib.get("Target", "")
            if rel.attrib.get("TargetMode") != "External":
                target = posixpath.normpath(
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.join(posixpath.dirname(workbook), target)
                )
            # For External relationships, openpyxl can still read an exact
            # archive member name; count that local case without fetching URLs.
            if target in names:
                targets.setdefault(rel.attrib.get("Id", ""), set()).add(target)
        for sheet in _metadata(archive, workbook).iter():
            if sheet.tag.rsplit("}", 1)[-1] != "sheet":
                continue
            for attr, identity in sheet.attrib.items():
                if attr.rsplit("}", 1)[-1] == "id":
                    worksheets.update(targets.get(identity, set()))
        xml_parts.update({workbook, relationships})
    xml_parts.update(worksheets)
    return xml_parts, worksheets


def _xml_budget(archive: ZipFile, name: str, *, worksheet: bool) -> tuple[int, int]:
    cells = merged_area = 0
    with archive.open(name) as stream:
        for _, element in SafeET.iterparse(
            stream, events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True
        ):
            if worksheet:
                local_name = element.tag.rsplit("}", 1)[-1]
                if local_name == "c":
                    cells += 1
                    if cells > 2_000_000:
                        raise OfficeArchiveError("office_cell_budget_exceeded")
                elif local_name == "mergeCell":
                    try:
                        c1, r1, c2, r2 = range_boundaries(element.attrib.get("ref", ""))
                    except (TypeError, ValueError) as exc:
                        raise OfficeArchiveError("office_invalid_merge_range") from exc
                    if c1 is None or r1 is None or c2 is None or r2 is None:
                        raise OfficeArchiveError("office_invalid_merge_range")
                    if not (1 <= c1 <= c2 <= 16384 and 1 <= r1 <= r2 <= 1048576):
                        raise OfficeArchiveError("office_invalid_merge_range")
                    merged_area += (r2 - r1 + 1) * (c2 - c1 + 1)
                    if merged_area > 250_000:
                        raise OfficeArchiveError("office_merge_budget_exceeded")
            element.clear()
    return cells, merged_area


def inspect_office_archive(
    source: bytes | Path | BinaryIO,
    *,
    max_compressed_bytes: int = 40 * 1024 * 1024,
    max_expanded_bytes: int = 512 * 1024 * 1024,
) -> dict:
    """Validate a local authorized snapshot, preserving a caller's stream position.

    A far-away sparse cell is allowed; a huge merged rectangle is blocked before
    openpyxl materializes it. Macros and external links are observations only;
    native read-only adapters must keep calculation and network access disabled.
    """
    handle: BinaryIO
    if isinstance(source, bytes):
        handle, owned = BytesIO(source), True
    elif isinstance(source, Path):
        handle, owned = source.open("rb"), True
    else:
        handle, owned = source, False
    position = handle.tell()
    try:
        handle.seek(0, 2)
        compressed = handle.tell()
        handle.seek(0)
        if compressed > max_compressed_bytes:
            raise OfficeArchiveError("office_compressed_budget_exceeded")
        with ZipFile(handle) as archive:
            members = archive.infolist()
            if len(members) > 10_000:
                raise OfficeArchiveError("office_member_budget_exceeded")
            expanded = sum(item.file_size for item in members)
            if expanded > max_expanded_bytes:
                raise OfficeArchiveError("office_expanded_budget_exceeded")
            seen = set()
            for item in members:
                name = item.filename
                path = PurePosixPath(name)
                if (
                    not name
                    or "\\" in name
                    or "\x00" in name
                    or path.is_absolute()
                    or ".." in path.parts
                    or ":" in name
                    or str(path) in seen
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    raise OfficeArchiveError("office_unsafe_member")
                seen.add(str(path))
                if item.flag_bits & 1:
                    raise OfficeArchiveError("office_encrypted_member")
                if item.compress_type not in {ZIP_DEFLATED, ZIP_STORED}:
                    raise OfficeArchiveError("office_unsupported_compression")
                if item.file_size > 128 * 1024 * 1024 or (
                    item.file_size > 1024 * 1024
                    and item.file_size > 1000 * max(item.compress_size, 1)
                ):
                    raise OfficeArchiveError("office_member_expansion_budget_exceeded")
            names = {item.filename for item in members if not item.is_dir()}
            xml_parts, worksheets = _part_roles(archive, names)
            cells = merged = 0
            for item in members:
                if item.filename in xml_parts:
                    count, area = _xml_budget(
                        archive, item.filename, worksheet=item.filename in worksheets
                    )
                    cells += count
                    merged += area
                    if cells > 2_000_000 or merged > 250_000:
                        raise OfficeArchiveError("office_materialization_budget_exceeded")
            return {
                "status": "checked",
                "compressed_bytes": compressed,
                "expanded_bytes": expanded,
                "member_count": len(members),
                "worksheet_cell_elements": cells,
                "merged_area_upper_bound": merged,
                "active_content_present": any(
                    "vbaproject" in name.lower() or "/activex/" in name.lower() for name in seen
                ),
                "external_links_present": any("/externalLinks/" in name for name in seen),
                "calculation_performed": False,
                "network_performed": False,
                "content_trust": "untrusted_document_data",
            }
    except (BadZipFile, ParseError, DefusedXmlException, EOFError, NotImplementedError) as exc:
        raise OfficeArchiveError("office_invalid_or_unsafe_archive") from exc
    finally:
        if owned:
            handle.close()
        else:
            handle.seek(position)
