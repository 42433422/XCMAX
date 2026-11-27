"""Numerical verification uses a real engine; fault cases never count as engine acceptance."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import psutil
import pytest
from openpyxl import Workbook, load_workbook

from app.application.agent_orchestrator import workbook_recalculation as recalc

_REAL_ENGINE = recalc._engine_path()
_REQUIRES_ENGINE = pytest.mark.skipif(
    not _REAL_ENGINE or os.name != "posix",
    reason="real LibreOffice with owned process-group cleanup required",
)


@pytest.fixture
def pinned_real_engine(monkeypatch):
    version = subprocess.run([_REAL_ENGINE, "--version"], text=True, capture_output=True, timeout=5)
    assert version.returncode == 0 and version.stdout.startswith("LibreOffice")
    # Test evidence pins the observed local build, not a production qualification.
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", version.stdout.strip())


def _workbook(tmp_path, formula="=SUM(A1:A2)"):
    path = tmp_path / "input.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet["A1"], sheet["A2"], sheet["B1"] = 3, 7, formula
    book.save(path)
    book.close()
    return path


def _verify(path, expected=None, **kwargs):
    plan = {"plan_version": 1, "phases": []}
    if expected is not None:
        plan["expected"] = {"formula_values": expected}
    return recalc.recalculate_workbook(
        path, plan, artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **kwargs
    )


def _rewrite_zip(path, mutate):
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    mutate(members)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@_REQUIRES_ENGINE
def test_real_calc_replaces_stale_cache_and_preserves_owned_source(tmp_path, pinned_real_engine):
    path = _workbook(tmp_path)
    book = load_workbook(path)
    sheet = book["Data"]
    sheet["B2"], sheet["C1"], sheet["C2"] = "=B1*2", '=""', "=A2>A1"
    book.create_sheet("Summary")["A1"] = "=SUM(Data!A1:A2)"
    book.save(path)
    book.close()

    def stale(members):
        members["xl/worksheets/sheet1.xml"] = members["xl/worksheets/sheet1.xml"].replace(
            b"<f>SUM(A1:A2)</f><v></v>", b"<f>SUM(A1:A2)</f><v>999</v>"
        )

    _rewrite_zip(path, stale)
    original = path.read_bytes()
    stale_book = load_workbook(io.BytesIO(original), data_only=True)
    assert stale_book["Data"]["B1"].value == 999
    stale_book.close()
    report = _verify(
        path,
        [
            {"sheet": "Data", "ref": "B1", "value": 10},
            {"sheet": "Data", "ref": "B2", "value": 20},
            {"sheet": "Summary", "ref": "A1", "value": 10},
        ],
    )
    assert report["status"] == "verified", report
    assert report["formula_recalculation_verified"] and report["expected_values_verified"]
    assert report["formula_count"] == 5 and report["expected_value_count"] == 3
    values = {(row["sheet"], row["ref"]): row["value"] for row in report["values"]}
    assert values == {
        ("Data", "B1"): 10,
        ("Data", "B2"): 20,
        ("Data", "C1"): "",
        ("Data", "C2"): True,
        ("Summary", "A1"): 10,
    }
    assert report["engine_version"].startswith("LibreOffice")
    assert report["artifact_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["output_sha256"] != report["artifact_sha256"]
    assert all(
        len(report[key]) == 64 for key in ("values_sha256", "formulas_sha256", "plan_sha256")
    )
    assert path.read_bytes() == original and report["source_unchanged"] is True
    assert report["delivered_artifact_replaced"] is False
    assert not list(tmp_path.glob("formula-qc-*"))


@_REQUIRES_ENGINE
@pytest.mark.parametrize(
    "formula,expected,code",
    [
        ("=1/0", None, "formula_recalculation_error"),
        (
            "=SUM(A1:A2)",
            [{"sheet": "Data", "ref": "B1", "value": 11}],
            "formula_recalculation_value_mismatch",
        ),
    ],
)
def test_real_calc_does_not_certify_errors_or_wrong_values(
    tmp_path, formula, expected, code, pinned_real_engine
):
    path = _workbook(tmp_path, formula)
    report = _verify(path, expected)
    assert report["status"] == "failed" and report["code"] == code, report
    assert report["formula_recalculation_verified"] is False
    assert report["source_unchanged"] is True


def test_missing_engine_does_not_relabel_formula_text_as_calculated(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    monkeypatch.setattr(recalc, "_engine_path", lambda: None)
    report = _verify(path)
    assert report["code"] == "formula_recalculation_engine_unavailable"
    assert report["status"] == "inconclusive" and not report["formula_recalculation_verified"]
    assert report["source_unchanged"] is True


@pytest.mark.parametrize(
    "formula",
    [
        "=[1]Other!A1",
        '=WEBSERVICE("https://example.invalid/")',
        "=INDIRECT(A1)",
        "=COM.MICROSOFT.WEBSERVICE(A1)",
        "=_xludf.WEBSERVICE(A1)",
        "='/tmp/unowned.xlsx'!A1",
        '=DDE("cmd","/c calc","A1")',
    ],
)
def test_unowned_formula_sources_never_launch_engine(tmp_path, monkeypatch, formula):
    path = _workbook(tmp_path, formula)
    monkeypatch.setattr(recalc, "_engine_path", lambda: pytest.fail("unowned data reached engine"))
    report = _verify(path)
    assert report["status"] == "inconclusive" and "external" in report["code"], report


@pytest.mark.parametrize(
    "part,data",
    [
        ("xl/vbaProject.bin", b"not-executed"),
        ("xl/externalLinks/externalLink1.xml", b"<externalLink/>"),
        (
            "xl/_rels/external.xml.rels",
            b'<Relationships><Relationship TargetMode="External" Target="file:///tmp/a"/></Relationships>',
        ),
        (
            "xl/_rels/disguised.xml.rels",
            b'<Relationships><Relationship Type="http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet" Target="worksheets/innocent.xml"/></Relationships>',
        ),
    ],
)
def test_macros_and_external_relationships_are_not_opened(tmp_path, monkeypatch, part, data):
    path = _workbook(tmp_path)
    _rewrite_zip(path, lambda members: members.update({part: data}))
    monkeypatch.setattr(
        recalc, "_engine_path", lambda: pytest.fail("active package reached engine")
    )
    report = _verify(path)
    assert report["code"] == "formula_recalculation_active_content", report
    assert not report["formula_recalculation_verified"]


@pytest.mark.parametrize(
    "expected",
    [
        [],
        [{"sheet": "Data", "ref": "A1", "value": 3}],
        [{"sheet": "Data", "ref": "B1", "value": 10, "abs_tolerance": -1}],
        [{"sheet": [], "ref": "B1", "value": 10}],
        [{"sheet": "Data", "ref": "B1", "value": 10}] * 2,
    ],
)
def test_invalid_frozen_numeric_expectation_is_not_ignored(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(
        recalc, "_engine_path", lambda: pytest.fail("invalid contract reached engine")
    )
    report = _verify(_workbook(tmp_path), expected)
    assert report["code"] == "formula_recalculation_expectation_invalid", report


@pytest.mark.parametrize("missing", ["xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml"])
def test_missing_ooxml_part_is_unverified_without_launch(tmp_path, monkeypatch, missing):
    path = _workbook(tmp_path)
    _rewrite_zip(path, lambda members: members.pop(missing))
    monkeypatch.setattr(recalc, "_engine_path", lambda: pytest.fail("invalid OOXML reached engine"))
    report = _verify(path)
    assert (
        report["status"] == "inconclusive"
        and report["code"] == "formula_recalculation_package_invalid"
    )


def test_changed_source_cannot_use_old_sha(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(path.read_bytes() + b"changed")
    monkeypatch.setattr(
        recalc, "_engine_path", lambda: pytest.fail("changed artifact reached engine")
    )
    report = recalc.recalculate_workbook(path, {}, artifact_sha256=original_sha)
    assert report["code"] == "formula_recalculation_artifact_changed"
    assert report["source_unchanged"] is False and not report["formula_recalculation_verified"]


def test_changed_engine_version_is_explicitly_unverified(tmp_path, monkeypatch):
    calls = []

    def version(command, **kwargs):
        calls.append(command)
        assert command[-1] == "--version"
        return subprocess.CompletedProcess(command, 0, "LibreOffice 1.0 fixture-build\n", "")

    monkeypatch.setattr(recalc, "_engine_path", lambda: "soffice-test")
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 2.0 required-build")
    monkeypatch.setattr(
        "app.application.employee_runtime.continuity_tool_wait.run_process", version
    )
    report = _verify(_workbook(tmp_path))
    assert report["code"] == "formula_recalculation_engine_version_mismatch"
    assert len(calls) == 1 and report["source_unchanged"] is True


def test_unpinned_engine_cannot_produce_numeric_evidence(tmp_path, monkeypatch):
    def version(command, **kwargs):
        assert command[-1] == "--version"
        return subprocess.CompletedProcess(command, 0, "LibreOffice 1.0 fixture-build\n", "")

    monkeypatch.setattr(recalc, "_engine_path", lambda: "soffice-test")
    monkeypatch.delenv("LIBREOFFICE_EXPECTED_VERSION", raising=False)
    monkeypatch.setattr(
        "app.application.employee_runtime.continuity_tool_wait.run_process", version
    )
    report = _verify(_workbook(tmp_path))
    assert report["code"] == "formula_recalculation_engine_version_unpinned"
    assert report["source_unchanged"] is True and report["formula_recalculation_verified"] is False


def test_process_env_is_scoped_to_child_and_default_still_inherits(tmp_path, monkeypatch):
    from app.application.employee_runtime.continuity_tool_wait import run_process

    monkeypatch.setenv("F06_PROCESS_TEST", "parent")
    command = [sys.executable, "-c", "import os; print(os.environ['F06_PROCESS_TEST'])"]
    default = run_process(command, input=None, cwd=tmp_path, timeout=5)
    isolated = run_process(
        command,
        input=None,
        cwd=tmp_path,
        timeout=5,
        env={**os.environ, "F06_PROCESS_TEST": "child"},
    )
    assert default.returncode == isolated.returncode == 0
    assert default.stdout.strip() == "parent" and isolated.stdout.strip() == "child"
    assert os.environ["F06_PROCESS_TEST"] == "parent"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("copy", "formula_recalculation_output_not_fresh"),
        ("no_cache", "formula_recalculation_cache_missing"),
        ("changed_literal_type", "formula_recalculation_input_cells_changed"),
    ],
)
def test_successful_engine_exit_is_not_proof_of_recalculation(tmp_path, monkeypatch, mode, code):
    path = _workbook(tmp_path)
    book = load_workbook(path)
    book["Data"]["A1"] = 1
    book.save(path)
    book.close()

    def no_calculation(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "LibreOffice 1.0 fault-injection\n", "")
        output = Path(command[command.index("--outdir") + 1]) / "source.xlsx"
        output.write_bytes(Path(command[-1]).read_bytes())
        if mode == "no_cache":
            with ZipFile(output, "a") as archive:
                archive.comment = b"changed container, no formula recalculation"
        elif mode == "changed_literal_type":
            changed = load_workbook(output)
            changed["Data"]["A1"] = True  # Python 1 == True must not mask a Calc input change.
            changed.save(output)
            changed.close()
        return subprocess.CompletedProcess(command, 0, "converted", "")

    monkeypatch.setattr(recalc, "_engine_path", lambda: "soffice-test")
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 1.0 fault-injection")
    monkeypatch.setattr(
        "app.application.employee_runtime.continuity_tool_wait.run_process", no_calculation
    )
    report = _verify(path)
    assert report["status"] == "inconclusive" and report["code"] == code, report
    assert not report["formula_recalculation_verified"] and report["source_unchanged"]


@pytest.mark.skipif(os.name != "posix", reason="existing process-group lifecycle is POSIX-only")
def test_timeout_reaps_engine_descendant_and_cannot_modify_source(tmp_path, monkeypatch):
    engine, pidfile = tmp_path / "slow-engine", tmp_path / "descendant.pid"
    engine.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, subprocess, sys, time\n"
        "if '--version' in sys.argv:\n"
        "    print('LibreOffice 1.0 fault-injection')\n"
        "    sys.exit(0)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    engine.chmod(0o700)
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 1.0 fault-injection")
    monkeypatch.setattr(recalc, "_engine_path", lambda: str(engine))
    path = _workbook(tmp_path)
    original = path.read_bytes()
    report = _verify(path, timeout_seconds=1)
    assert report["code"] == "formula_recalculation_timeout", report
    assert report["source_unchanged"] is True and path.read_bytes() == original
    assert not list(tmp_path.glob("formula-qc-*"))
    assert pidfile.is_file(), "fault-injection child must actually start"
    try:
        child = psutil.Process(int(pidfile.read_text()))
    except psutil.NoSuchProcess:
        pass
    else:
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
