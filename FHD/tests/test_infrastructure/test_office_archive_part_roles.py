from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from defusedxml import ElementTree as SafeET
from openpyxl import Workbook, load_workbook

from app.application import tabular_workbook
from app.infrastructure.document_parsing.archive_safety import (
    OfficeArchiveError,
    inspect_office_archive,
)


def _archive(entries):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def _renamed_sheet(target, *, misdeclare_binary=False):
    book = Workbook()
    sheet = book.active
    sheet["A1"], sheet["B1"], sheet["A2"] = 0, False, "anchor"
    sheet.merge_cells("A2:C3")
    output = BytesIO()
    book.save(output)
    book.close()
    entries = []
    with ZipFile(output) as original:
        for item in original.infolist():
            content = original.read(item.filename)
            if item.filename in {"[Content_Types].xml", "xl/_rels/workbook.xml.rels"}:
                content = content.replace(b"/xl/worksheets/sheet1.xml", ("/" + target).encode())
            if item.filename == "[Content_Types].xml" and misdeclare_binary:
                root = SafeET.fromstring(content)
                for part in root:
                    if part.attrib.get("PartName") == "/" + target:
                        part.attrib["ContentType"] = "application/octet-stream"
                content = SafeET.tostring(root, encoding="utf-8")
            entries.append(
                (target if item.filename == "xl/worksheets/sheet1.xml" else item.filename, content)
            )
    return _archive(entries)


@pytest.mark.parametrize(
    ("target", "misdeclare_binary"),
    [
        ("xl/custom/sheet1.payload", False),
        ("xl/worksheets/SHEET1.XML", False),
        ("xl/custom/sheet1.payload", True),
    ],
)
def test_native_reader_relationship_targets_cannot_evade_budget(
    target, misdeclare_binary, monkeypatch
):
    body = _renamed_sheet(target, misdeclare_binary=misdeclare_binary)
    # Actual openpyxl loading proves these are reachable worksheet objects,
    # even when Content_Types labels the relationship target as binary.
    book = load_workbook(BytesIO(body), keep_links=False)
    try:
        assert [book.active[ref].value for ref in ("A1", "B1", "A2")] == [0, False, "anchor"]
        assert len(book.active._cells) == 8
    finally:
        book.close()
    report = inspect_office_archive(body)
    assert report["worksheet_cell_elements"] == 3
    assert report["merged_area_upper_bound"] == 6

    def forbidden(*args, **kwargs):
        pytest.fail("formula extraction must not start over the allocation limit")

    monkeypatch.setattr(tabular_workbook, "WORKBOOK_MATERIALIZED_CELL_LIMIT", 1)
    with pytest.raises(OfficeArchiveError, match="tabular_native_materialization_budget_exceeded"):
        tabular_workbook.read_workbook_facts(body)


@pytest.mark.parametrize("name", ["custom.DATA", "UPPER.XML"])
def test_xml_role_or_case_insensitive_extension_preserves_entity_rejection(name):
    content_types = f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/{name}" ContentType="application/example+xml"/></Types>'
    body = _archive(
        [
            ("[Content_Types].xml", content_types),
            (
                name,
                '<!DOCTYPE root [<!ENTITY leak SYSTEM "file:///must-not-be-read">]><root>&leak;</root>',
            ),
        ]
    )
    with pytest.raises(OfficeArchiveError, match="office_invalid_or_unsafe_archive"):
        inspect_office_archive(body)


def test_opaque_binary_part_does_not_become_an_xml_parser_input():
    content_types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/media/object.bin" ContentType="application/octet-stream"/></Types>'
    body = _archive(
        [("[Content_Types].xml", content_types), ("media/object.bin", b"\x00\xffnot XML")]
    )
    report = inspect_office_archive(body)
    assert report["status"] == "checked"
    assert report["worksheet_cell_elements"] == 0
