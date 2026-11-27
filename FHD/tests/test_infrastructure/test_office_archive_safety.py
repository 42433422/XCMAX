from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

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


def _workbook():
    output = BytesIO()
    workbook = Workbook()
    workbook.active["A1"] = 0
    workbook.active["B1"] = False
    workbook.active["XFD1048576"] = "far sparse cell"
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_sparse_extent_does_not_consume_rectangular_budget():
    stream = BytesIO(_workbook())
    stream.seek(7)
    report = inspect_office_archive(stream)
    assert report["worksheet_cell_elements"] == 3
    assert report["merged_area_upper_bound"] == 0
    assert report["calculation_performed"] is False
    assert report["content_trust"] == "untrusted_document_data"
    assert stream.tell() == 7
    assert not stream.closed


@pytest.mark.parametrize("name", ["../outside.xml", "/root.xml", "C:/data.xml", "a\\b.xml"])
def test_unsafe_member_names_rejected_without_extracting(name):
    with pytest.raises(OfficeArchiveError, match="office_unsafe_member"):
        inspect_office_archive(_archive([(name, "<root/>")]))


def test_duplicate_and_normalized_alias_members_rejected():
    with pytest.raises(OfficeArchiveError, match="office_unsafe_member"):
        inspect_office_archive(_archive([("a.xml", "<root/>"), ("./a.xml", "<root/>")]))


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE root [<!ENTITY leak SYSTEM "file:///etc/passwd">]><root>&leak;</root>',
        '<!DOCTYPE root [<!ENTITY x "text">]><root>&x;</root>',
        "<root><invalid></root>",
    ],
)
def test_xml_entities_and_malformed_xml_are_explicitly_blocked(xml):
    with pytest.raises(OfficeArchiveError, match="office_invalid_or_unsafe_archive"):
        inspect_office_archive(_archive([("xl/workbook.xml", xml)]))


def test_archive_expansion_is_rejected_before_xml_is_read():
    body = _archive([("xl/workbook.xml", "x" * 2_000_000)])
    with pytest.raises(OfficeArchiveError, match="office_member_expansion_budget_exceeded"):
        inspect_office_archive(body)
    with pytest.raises(OfficeArchiveError, match="office_expanded_budget_exceeded"):
        inspect_office_archive(body, max_expanded_bytes=10_000)


def test_large_merge_is_blocked_before_openpyxl_allocates(monkeypatch):
    from app.application import reviewed_excel_template
    from app.application.elt.errors import ReviewedExcelError

    body = _workbook()
    with ZipFile(BytesIO(body)) as archive:
        entries = [(item.filename, archive.read(item.filename)) for item in archive.infolist()]
    malicious = _archive(
        [
            (
                name,
                content.replace(
                    b"</worksheet>",
                    b'<mergeCells count="1"><mergeCell ref="A1:XFD1048576"/></mergeCells></worksheet>',
                )
                if name == "xl/worksheets/sheet1.xml"
                else content,
            )
            for name, content in entries
        ]
    )

    def forbidden(*args, **kwargs):
        pytest.fail("native workbook loader must not receive the giant merged rectangle")

    monkeypatch.setattr(reviewed_excel_template, "load_workbook", forbidden)
    with pytest.raises(ReviewedExcelError, match="office_merge_budget_exceeded"):
        reviewed_excel_template.inspect_workbook(malicious)


def test_formula_evidence_cannot_turn_unsafe_archive_into_no_formulas():
    from app.application.reviewed_excel_formula_cells import formula_facts

    with pytest.raises(OfficeArchiveError):
        formula_facts(_archive([("../xl/worksheets/sheet1.xml", "<root/>")]))
