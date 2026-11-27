"""Native source fidelity and explicit unsupported printer settings boundaries."""

from __future__ import annotations

import posixpath
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.packaging.relationship import get_rels_path
from openpyxl.xml.constants import PKG_REL_NS, REL_NS, SHEET_MAIN_NS

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"
_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_PLAN = {
    "phases": [
        {
            "phase": "cell_writes",
            "writes": [
                {"sheet": "Data", "ref": "A1", "value": "keep"},
            ],
        }
    ]
}


@pytest.fixture
def engines():
    return (
        load_module(
            "native_serialization_writer",
            ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
        ),
        load_module(
            "native_serialization_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py"
        ),
    )


def _parts(path):
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _save_parts(path, parts):
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


def _template(tmp_path, *, zero_width=False, printer=None, renamed_sheet=False):
    path = tmp_path / "template.xlsx"
    book = Workbook()
    book.active.title = "Data"
    book.active["A1"] = "keep"
    book.active["B1"] = 0
    if zero_width:
        book.active.column_dimensions["A"].width = 1
        book.active.column_dimensions["A"].hidden = True
    book.save(path)
    book.close()
    parts = _parts(path)
    original_sheet = "xl/worksheets/sheet1.xml"
    sheet_part = "xl/forms/renamed.payload" if renamed_sheet else original_sheet
    sheet = ET.fromstring(parts.pop(original_sheet))
    manifest = ET.fromstring(parts["[Content_Types].xml"])
    if zero_width:
        sheet.find(f"{{{SHEET_MAIN_NS}}}cols/{{{SHEET_MAIN_NS}}}col").set("width", "0")
    if renamed_sheet:
        for item in manifest:
            if item.get("PartName") == "/" + original_sheet:
                item.set("PartName", "/" + sheet_part)
        relations = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
        for item in relations:
            if item.get("Type") == REL_NS + "/worksheet":
                item.set("Target", "/" + sheet_part)
        parts["xl/_rels/workbook.xml.rels"] = ET.tostring(relations)
    if printer:
        ET.SubElement(sheet, f"{{{SHEET_MAIN_NS}}}pageSetup", {f"{{{REL_NS}}}id": "rIdPrinter"})
        relations = ET.Element(f"{{{PKG_REL_NS}}}Relationships")
        ET.SubElement(
            relations,
            f"{{{PKG_REL_NS}}}Relationship",
            {
                "Id": "rIdPrinter",
                "Type": REL_NS + "/printerSettings",
                "Target": posixpath.relpath(printer, posixpath.dirname(sheet_part)),
            },
        )
        parts[get_rels_path(sheet_part)] = ET.tostring(relations)
        parts[printer] = b"opaque native printer settings fixture\x00\x01"
        ET.SubElement(
            manifest,
            f"{{{_TYPES}}}Override",
            {
                "PartName": "/" + printer,
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.printerSettings",
            },
        )
    parts[sheet_part] = ET.tostring(sheet)
    parts["[Content_Types].xml"] = ET.tostring(manifest)
    _save_parts(path, parts)
    return path


def _write(writer, source, output, plan=_PLAN):
    return writer.convert_file(
        None,
        output,
        template_path=source,
        payload={"plan": plan, "strict_protected": True},
        ctx={},
        rule_spec={},
    )


def test_zero_width_survives_native_save_and_independent_qc(engines, tmp_path):
    writer, qc = engines
    source = _template(tmp_path, zero_width=True)
    original = source.read_bytes()
    output = tmp_path / "output.xlsx"
    _write(writer, source, output)
    book = load_workbook(output)
    try:
        assert book["Data"].column_dimensions["A"].width == 0
        assert book["Data"].column_dimensions["A"].hidden is True
    finally:
        book.close()
    report = qc.run_qc(output, _PLAN, template_path=source)
    assert report["verdict"] == "PASS", report
    assert source.read_bytes() == original
    book = load_workbook(output)
    book["Data"].column_dimensions["A"].width = 13
    book.save(output)
    book.close()
    assert qc.run_qc(output, _PLAN, template_path=source)["verdict"] == "FAIL"


def test_qc_rejects_dropped_printer_settings(engines, tmp_path):
    _, qc = engines
    source = _template(tmp_path, printer="xl/devices/printer-profile.payload")
    original = source.read_bytes()
    output = tmp_path / "output.xlsx"
    # Pinned openpyxl deliberately strips the pageSetup binary relationship.
    book = load_workbook(source)
    book.save(output)
    book.close()
    report = qc.run_qc(output, _PLAN, template_path=source)
    assert report["verdict"] == "FAIL", report
    assert any("打印机" in issue["detail"] for issue in report["sections"]["conformance"]["issues"])
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "printer", ["xl/printerSettings/printerSettings1.bin", "xl/devices/profile.payload"]
)
@pytest.mark.parametrize("renamed_sheet", [False, True])
@pytest.mark.parametrize("existing_output", [False, True])
def test_writer_blocks_native_printer_settings_before_load_or_output(
    engines, tmp_path, monkeypatch, printer, renamed_sheet, existing_output
):
    writer, _ = engines
    source = _template(tmp_path, printer=printer, renamed_sheet=renamed_sheet)
    original = source.read_bytes()
    output = tmp_path / "published" / "output.xlsx"
    if existing_output:
        output.parent.mkdir()
        output.write_bytes(b"existing output must survive")
    monkeypatch.setattr(
        "openpyxl.load_workbook",
        lambda *a, **kw: pytest.fail("native allocation before capability guard"),
    )
    with pytest.raises(writer.PlanError, match="unsupported_workbook_printer_settings"):
        _write(writer, source, output)
    assert source.read_bytes() == original
    if existing_output:
        assert output.read_bytes() == b"existing output must survive"
    else:
        assert not output.parent.exists()
    assert not (output.parent / "write_report.json").exists()


@pytest.mark.parametrize("change", ["unchanged", "rename", "content", "unlink", "missing"])
def test_qc_compares_settings_binding_and_bytes_independently_of_part_name(
    engines, tmp_path, change
):
    _, qc = engines
    printer = "xl/devices/profile.payload"
    source = _template(tmp_path, printer=printer, renamed_sheet=True)
    original = source.read_bytes()
    output = tmp_path / "output.xlsx"
    parts = _parts(source)
    sheet_part = "xl/forms/renamed.payload"
    if change == "content":
        parts[printer] += b"changed"
    elif change == "missing":
        del parts[printer]
    elif change == "unlink":
        sheet = ET.fromstring(parts[sheet_part])
        sheet.find(f"{{{SHEET_MAIN_NS}}}pageSetup").attrib.pop(f"{{{REL_NS}}}id")
        parts[sheet_part] = ET.tostring(sheet)
    elif change == "rename":
        replacement = "xl/hardware/replaced-name.bin"
        parts[replacement] = parts.pop(printer)
        manifest = ET.fromstring(parts["[Content_Types].xml"])
        for item in manifest:
            if item.get("PartName") == "/" + printer:
                item.set("PartName", "/" + replacement)
        parts["[Content_Types].xml"] = ET.tostring(manifest)
        relations = ET.fromstring(parts[get_rels_path(sheet_part)])
        relations[0].set("Target", "/" + replacement)
        relations[0].set("Id", "rIdRenumbered")
        parts[get_rels_path(sheet_part)] = ET.tostring(relations)
        sheet = ET.fromstring(parts[sheet_part])
        sheet.find(f"{{{SHEET_MAIN_NS}}}pageSetup").set(f"{{{REL_NS}}}id", "rIdRenumbered")
        parts[sheet_part] = ET.tostring(sheet)
    _save_parts(output, parts)
    report = qc.run_qc(output, _PLAN, template_path=source)
    assert report["verdict"] == ("PASS" if change in {"unchanged", "rename"} else "FAIL"), report
    assert source.read_bytes() == original


def test_file_name_alone_does_not_claim_native_printer_configuration(engines, tmp_path):
    writer, qc = engines
    source = _template(tmp_path)
    parts = _parts(source)
    parts["xl/printerSettings/printerSettings1.bin"] = b"unreferenced lookalike"
    _save_parts(source, parts)
    output = tmp_path / "output.xlsx"
    _write(writer, source, output)
    assert qc.run_qc(output, _PLAN, template_path=source)["verdict"] == "PASS"


def test_external_printer_relationship_is_blocked_without_fetch(engines, tmp_path, monkeypatch):
    writer, _ = engines
    source = _template(tmp_path, printer="xl/devices/profile.payload")
    parts = _parts(source)
    rel_part = get_rels_path("xl/worksheets/sheet1.xml")
    relations = ET.fromstring(parts[rel_part])
    relations[0].set("TargetMode", "External")
    relations[0].set("Target", "https://example.invalid/private-driver")
    parts[rel_part] = ET.tostring(relations)
    _save_parts(source, parts)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("external fetch"))
    with pytest.raises(writer.PlanError, match="unsupported_workbook_printer_settings"):
        _write(writer, source, tmp_path / "output.xlsx")
    assert not (tmp_path / "output.xlsx").exists()


def test_external_sheet_pointing_to_local_part_cannot_hide_printer_configuration(engines, tmp_path):
    writer, qc = engines
    source = _template(tmp_path, printer="xl/devices/profile.payload")
    parts = _parts(source)
    relationships = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    for relationship in relationships:
        if relationship.get("Type") == REL_NS + "/worksheet":
            relationship.set("TargetMode", "External")
            relationship.set("Target", "xl/worksheets/sheet1.xml")
    parts["xl/_rels/workbook.xml.rels"] = ET.tostring(relationships)
    _save_parts(source, parts)
    original = source.read_bytes()
    output = tmp_path / "output.xlsx"
    # openpyxl still reads this local sheet despite its unsupported mode.
    book = load_workbook(source)
    assert book["Data"]["A1"].value == "keep"
    book.save(output)
    book.close()
    previous_output = output.read_bytes()
    with pytest.raises(writer.PlanError, match="workbook_sheet_relationship_unsupported"):
        _write(writer, source, output)
    assert output.read_bytes() == previous_output
    assert source.read_bytes() == original
    report = qc.run_qc(output, _PLAN, template_path=source)
    assert report["verdict"] == "FAIL", report


def test_public_tax_invoice_is_explicitly_unsupported_without_touching_original(engines, tmp_path):
    writer, _ = engines
    source = Path(__file__).resolve().parents[1] / "fixtures/network_forms/net_tax_invoice.xlsx"
    original = source.read_bytes()
    book = load_workbook(source)
    try:
        value = book["20191030"]["X11"].value
    finally:
        book.close()
    plan = {
        "phases": [
            {
                "phase": "cell_writes",
                "writes": [
                    {"sheet": "20191030", "ref": "X11", "value": value},
                ],
            }
        ]
    }
    with pytest.raises(writer.PlanError, match="unsupported_workbook_printer_settings"):
        _write(writer, source, tmp_path / "output.xlsx", plan)
    assert source.read_bytes() == original
    assert not (tmp_path / "output.xlsx").exists()
