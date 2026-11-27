"""Independent formula evidence; actual recalculation uses a generated fixture only."""

import hashlib
import os
import shutil
import subprocess
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from app.application.workbook_formula_evidence import (
    formula_dependency_facts,
    summarize_formula_evidence,
)

_LIBREOFFICE = shutil.which("libreoffice") or shutil.which("soffice")


def _fixture(path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    other = book.create_sheet("Other sheet")
    other["A1"] = 3
    sheet["A1"] = 2
    sheet["B4"] = "=A1+'Other sheet'!A1"
    sheet["B5"] = "=SUM(B4,7)"
    sheet["D1"] = "=1/0"
    sheet.merge_cells("A8:B8")
    sheet["A8"] = "untouched"
    book.save(path)
    book.close()


def test_dependency_tokens_keep_quoted_sheet_and_unresolved_names():
    result = formula_dependency_facts("=A1+'Other sheet'!$B$2+INDIRECT(A3)+NamedRange", "Data")
    assert result["references"][1] == {
        "token": "'Other sheet'!$B$2",
        "sheet": "Other sheet",
        "kind": "cross_sheet",
    }
    assert set(result["unresolved"]) == {"dynamic_reference", "named_or_unknown"}
    assert formula_dependency_facts("", "Data")["unresolved"] == ["missing_formula_text"]


def test_invalid_and_nonstatic_dependencies_are_not_claimed_as_resolved():
    assert formula_dependency_facts("=)", "Data")["unresolved"] == ["unsupported_formula_syntax"]
    assert formula_dependency_facts("=XFE1", "Data")["unresolved"] == ["named_or_unknown"]
    result = formula_dependency_facts("=[Book.xlsx]Data!A1+Table1[Column]+Sheet1:Sheet2!B1", "Data")
    assert set(result["unresolved"]) == {"external", "structured", "three_dimensional"}


def test_cache_is_observed_not_recalculated(tmp_path):
    source = tmp_path / "input.xlsx"
    _fixture(source)
    body = source.read_bytes()
    evidence = summarize_formula_evidence(body, qc_formula_count=3)
    assert evidence["artifact_sha256"] == hashlib.sha256(body).hexdigest()
    assert evidence["cache_states"] == {"missing_or_empty": 3}
    assert evidence["reference_token_counts"] == {"local": 2, "cross_sheet": 1}
    output = BytesIO()
    with ZipFile(BytesIO(body)) as src, ZipFile(output, "w") as dst:
        for member in src.infolist():
            content = src.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(b"<v></v>", b"<v>0</v>", 1)
            dst.writestr(member, content)
    observed = summarize_formula_evidence(output.getvalue(), qc_formula_count=3)
    assert observed["cache_states"] == {"present_unverified": 1, "missing_or_empty": 2}
    assert observed["coverage"] == "not_proven"
    assert observed["formula_recalculation_verified"] is False


def test_bad_archive_cannot_prove_no_formulas():
    evidence = summarize_formula_evidence(b"invalid", qc_formula_count=0)
    assert evidence["status"] == "invalid_archive"
    assert evidence["coverage"] == "not_proven"


@pytest.mark.skipif(
    os.getenv("XCAGI_WG10_LO_FIXTURE") != "1" or not _LIBREOFFICE,
    reason="opt-in calculation-engine qualification on generated fixture only",
)
def test_real_libreoffice_recalculation_compatibility(tmp_path):
    source = tmp_path / "input.xlsx"
    _fixture(source)
    original = source.read_bytes()
    out = tmp_path / "out"
    out.mkdir()
    subprocess.run(
        [
            _LIBREOFFICE,
            "-env:UserInstallation=" + (tmp_path / "profile").as_uri(),
            "--headless",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(out),
            str(source),
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    calculated = out / source.name
    values = load_workbook(calculated, data_only=True)
    formulas = load_workbook(calculated, data_only=False)
    try:
        assert source.read_bytes() == original
        assert (values["Data"]["B4"].value, values["Data"]["B5"].value) == (5, 12)
        assert values["Data"]["D1"].value == "#DIV/0!"
        assert formulas["Data"]["B4"].value == "=A1+'Other sheet'!A1"
        assert formulas["Data"]["B5"].value == "=SUM(B4,7)"
        assert str(formulas["Data"].merged_cells) == "A8:B8"
        assert formulas["Data"]["A8"].value == "untouched"
        evidence = summarize_formula_evidence(calculated.read_bytes())
        assert evidence["formula_recalculation_verified"] is False
    finally:
        values.close()
        formulas.close()
