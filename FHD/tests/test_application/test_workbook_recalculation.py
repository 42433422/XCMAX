"""Numerical verification uses a real engine; fault cases never count as engine acceptance."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import psutil
import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.table import Table, TableColumn, TableFormula

from app.application.agent_orchestrator import workbook_recalculation as recalc

_REAL_ENGINE = recalc._engine_path()
_REQUIRES_ENGINE = pytest.mark.skipif(
    not _REAL_ENGINE or os.name != "posix",
    reason="real LibreOffice with owned process-group cleanup required",
)
_REQUIRES_LIMITER = pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("prlimit"), reason="Linux prlimit required"
)


@pytest.fixture(autouse=True)
def owned_calc_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))


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
        [
            {"sheet": "Data", "ref": "B1", "value": 10},
            {"sheet": "Data", "ref": "b1", "value": 10},
        ],
    ],
)
def test_invalid_frozen_numeric_expectation_is_not_ignored(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(
        recalc, "_engine_path", lambda: pytest.fail("invalid contract reached engine")
    )
    report = _verify(_workbook(tmp_path), expected)
    assert report["code"] == "formula_recalculation_expectation_invalid", report


def test_lowercase_expectation_reaches_engine_without_rewriting_frozen_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(recalc, "_engine_path", lambda: None)
    expected = [{"sheet": "Data", "ref": "b1", "value": 10}]
    report = _verify(_workbook(tmp_path), expected)
    assert report["code"] == "formula_recalculation_engine_unavailable", report
    assert expected == [{"sheet": "Data", "ref": "b1", "value": 10}]


def test_unavailable_resource_limits_never_launch_engine(tmp_path, monkeypatch):
    from app.application.employee_runtime import continuity_tool_wait as process_runtime

    monkeypatch.setattr(recalc, "_engine_path", lambda: sys.executable)
    monkeypatch.setattr(process_runtime.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        process_runtime.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unbounded engine was launched"),
    )
    report = _verify(_workbook(tmp_path))
    assert report["code"] == "formula_recalculation_resource_limits_unavailable", report
    assert report["source_unchanged"] and not report["formula_recalculation_verified"]


@_REQUIRES_LIMITER
def test_process_limits_bound_real_allocation_file_output_and_cpu(tmp_path):
    import resource

    from app.application.employee_runtime.continuity_tool_wait import ProcessLimits, run_process

    kinds = [resource.RLIMIT_CPU, resource.RLIMIT_AS, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE]
    before = [resource.getrlimit(kind) for kind in kinds]
    output = tmp_path / "bounded-output"
    script = """
import errno, json, os, resource, sys
report = {'limits': [resource.getrlimit(kind) for kind in
    (resource.RLIMIT_CPU, resource.RLIMIT_AS, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE)]}
try:
    allocation = bytearray(256 * 1024 * 1024)
except MemoryError:
    report['allocation_rejected'] = True
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT, 0o600)
try:
    os.write(fd, b'x' * 2048)
    os.write(fd, b'x')
except OSError as exc:
    report['file_errno'] = exc.errno
finally:
    os.close(fd)
print(json.dumps(report))
"""
    limits = ProcessLimits(3, 128 * 1024**2, 1024, 64)
    result = run_process(
        [sys.executable, "-c", script, str(output)],
        input=None,
        cwd=tmp_path,
        timeout=5,
        limits=limits,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["allocation_rejected"] and report["file_errno"] == 27  # EFBIG on Linux.
    assert output.stat().st_size == 1024
    for pair, cap in zip(report["limits"], (3, 128 * 1024**2, 1024, 64), strict=True):
        assert pair[0] == pair[1] <= cap
    cpu = run_process(
        [sys.executable, "-c", "while True: pass"],
        input=None,
        cwd=tmp_path,
        timeout=5,
        limits=ProcessLimits(1, 128 * 1024**2, 1024, 64),
    )
    assert cpu.returncode == -signal.SIGKILL
    assert [resource.getrlimit(kind) for kind in kinds] == before


@_REQUIRES_LIMITER
def test_process_limits_preserve_stricter_inherited_limits(tmp_path):
    from app.application.employee_runtime.continuity_tool_wait import run_process

    script = """
import json, os, resource, sys
from pathlib import Path
from app.application.employee_runtime.continuity_tool_wait import ProcessLimits, run_process
kinds = (resource.RLIMIT_CPU, resource.RLIMIT_AS, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE)
# Importing the full runtime may map more than 192 MiB in CI. Leave the parent
# space to launch; the requested child limit must still preserve its lower cap.
mapped = int(Path('/proc/self/statm').read_text().split()[0]) * os.sysconf('SC_PAGE_SIZE')
memory_limit = max(192 * 1024**2, mapped + 64 * 1024**2)
caps = (3, memory_limit, 2048, 64)
for kind, cap in zip(kinds, caps):
    resource.setrlimit(kind, (cap, cap))
child = 'import json,resource;print(json.dumps([resource.getrlimit(k) for k in '+repr(kinds)+']))'
result = run_process([sys.executable, '-c', child], input=None, cwd='.', timeout=5,
    limits=ProcessLimits(6, 2 * memory_limit, 4096, 128))
assert result.returncode == 0, result.stderr
print(json.dumps({'memory_limit': memory_limit, 'child_limits': json.loads(result.stdout)}))
"""
    result = run_process([sys.executable, "-c", script], input=None, cwd=tmp_path, timeout=8)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["memory_limit"] >= 192 * 1024**2
    assert report["child_limits"] == [[3, 3], [report["memory_limit"]] * 2, [2048, 2048], [64, 64]]


@_REQUIRES_LIMITER
def test_calc_slot_blocks_another_process_within_original_budget(tmp_path, monkeypatch):
    engine = tmp_path / "owned-engine"
    calls, release = tmp_path / "engine-calls", tmp_path / "release"
    engine.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, shutil, sys, time\n"
        f"calls, release = pathlib.Path({str(calls)!r}), pathlib.Path({str(release)!r})\n"
        "with calls.open('a') as stream: stream.write(('version' if '--version' in sys.argv else 'convert')+'\\n')\n"
        "if '--version' in sys.argv:\n"
        "    print('LibreOffice 1.0 concurrency-test')\n"
        "    sys.exit(0)\n"
        "deadline = time.monotonic() + 5\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--outdir')+1]) / 'source.xlsx'\n"
        "shutil.copyfile(sys.argv[-1], output)\n",
        encoding="utf-8",
    )
    engine.chmod(0o700)
    monkeypatch.setenv("LIBREOFFICE_PATH", str(engine))
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 1.0 concurrency-test")
    path = _workbook(tmp_path)
    script = (
        "import hashlib,json,sys;from pathlib import Path;"
        "from app.application.agent_orchestrator.workbook_recalculation import recalculate_workbook;"
        "p=Path(sys.argv[1]);print(json.dumps(recalculate_workbook(p,{},"
        "artifact_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),timeout_seconds=6)))"
    )
    with subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as first:
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if calls.exists() and calls.read_text().splitlines() == ["version", "convert"]:
                    break
                assert first.poll() is None, first.communicate()
                time.sleep(0.01)
            assert calls.read_text().splitlines() == ["version", "convert"]
            second = _verify(path, timeout_seconds=0.15)
            assert second["code"] == "formula_recalculation_timeout", second
            assert second["source_unchanged"] and not second["formula_recalculation_verified"]
            assert calls.read_text().splitlines() == ["version", "convert"]
        finally:
            release.touch()
            stdout, stderr = first.communicate(timeout=8)
        assert first.returncode == 0, stderr
        assert json.loads(stdout)["code"] == "formula_recalculation_output_not_fresh"


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


@pytest.mark.parametrize(
    "mutation",
    ["definition", "local_scope", "date_system", "precision", "reference_mode", "defaults", None],
)
def test_converted_cache_requires_unchanged_calculation_context(tmp_path, monkeypatch, mutation):
    path = _workbook(tmp_path, "=Rate")
    book = load_workbook(path)
    book.defined_names.add(DefinedName("Rate", attr_text="'Data'!$A$1"))
    book.create_sheet("Other")
    book.save(path)
    book.close()
    original = path.read_bytes()

    def conversion(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "LibreOffice 1.0 fault-injection\n", "")
        output = Path(command[command.index("--outdir") + 1]) / "source.xlsx"
        output.write_bytes(Path(command[-1]).read_bytes())

        def change(members):
            workbook = members["xl/workbook.xml"]
            if mutation == "definition":
                workbook = workbook.replace(b"'Data'!$A$1", b"'Data'!$A$2")
            elif mutation == "local_scope":
                workbook = workbook.replace(b'name="Rate"', b'name="Rate" localSheetId="1"')
            elif mutation == "date_system":
                workbook = workbook.replace(b"<workbookPr/>", b'<workbookPr date1904="1"/>')
            elif mutation == "precision":
                workbook = workbook.replace(b"<calcPr ", b'<calcPr fullPrecision="0" ')
            elif mutation == "reference_mode":
                workbook = workbook.replace(b"<calcPr ", b'<calcPr refMode="R1C1" ')
            elif mutation == "defaults":
                workbook = workbook.replace(b"<workbookPr/>", b'<workbookPr date1904="0"/>')
                workbook = workbook.replace(
                    b"<calcPr ", b'<calcPr fullPrecision="true" refMode="A1" '
                )
            if mutation is not None:
                assert workbook != members["xl/workbook.xml"]
            members["xl/workbook.xml"] = workbook
            members["xl/worksheets/sheet1.xml"] = members["xl/worksheets/sheet1.xml"].replace(
                b"<f>Rate</f><v></v>",
                b"<f>Rate</f><v>7</v>" if mutation == "definition" else b"<f>Rate</f><v>3</v>",
            )

        _rewrite_zip(output, change)
        return subprocess.CompletedProcess(command, 0, "converted", "")

    monkeypatch.setattr(recalc, "_engine_path", lambda: "soffice-test")
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 1.0 fault-injection")
    monkeypatch.setattr(
        "app.application.employee_runtime.continuity_tool_wait.run_process", conversion
    )
    report = _verify(
        path, [{"sheet": "Data", "ref": "B1", "value": 7 if mutation == "definition" else 3}]
    )
    if mutation in {None, "defaults"}:
        assert report["status"] == "verified" and report["expected_values_verified"], report
    else:
        assert report["status"] == "inconclusive", report
        assert report["code"] == "formula_recalculation_input_context_changed", report
        assert not report["formula_recalculation_verified"]
        assert not report.get("expected_values_verified")
    assert report["source_unchanged"] and path.read_bytes() == original


@pytest.mark.parametrize(
    "mutation",
    [
        "ref",
        "name",
        "displayName",
        "headerRowCount",
        "totalsRowCount",
        "column_order",
        "column_name",
        "column_formula",
        "column_metadata",
        "sheet",
        "defaults",
        "package_ids",
        None,
    ],
)
def test_controlled_conversion_cannot_change_structured_reference_inputs(
    tmp_path, monkeypatch, mutation
):
    """Fault injection checks the verification boundary, not real Calc evaluation."""
    path = tmp_path / "table.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    for row in [("Column", "Other"), (3, 30), (7, 70)]:
        sheet.append(row)
    sheet["C1"] = "=SUM(TableName[Column])"
    sheet.add_table(
        Table(
            displayName="TableName",
            ref="A1:B3",
            tableColumns=[
                TableColumn(id=1, name="Column"),
                TableColumn(
                    id=2, name="Other", calculatedColumnFormula=TableFormula(attr_text="A2*10")
                ),
            ],
        )
    )
    other = book.create_sheet("Other")
    for row in [("Column", "Other"), (20, 200), (30, 300)]:
        other.append(row)
    book.save(path)
    book.close()

    def stale_cache(members):
        members["xl/worksheets/sheet1.xml"] = members["xl/worksheets/sheet1.xml"].replace(
            b"<f>SUM(TableName[Column])</f><v></v>",
            b"<f>SUM(TableName[Column])</f><v>3</v>",
        )

    _rewrite_zip(path, stale_cache)
    original = path.read_bytes()
    value = {"ref": 3, "sheet": 50}.get(mutation, 10)

    def conversion(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "LibreOffice 1.0 fault-injection\n", "")
        output = Path(command[command.index("--outdir") + 1]) / "source.xlsx"
        output.write_bytes(original)

        def change(members):
            table_path, sheet_path = "xl/tables/table1.xml", "xl/worksheets/sheet1.xml"
            table = ElementTree.fromstring(members[table_path])
            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            columns = table.find(f"{ns}tableColumns")
            if mutation == "ref":
                # Only this ZIP member changes; even the stale cell cache stays identical.
                members[table_path] = members[table_path].replace(b'ref="A1:B3"', b'ref="A1:B2"')
                return
            if mutation in {"name", "displayName", "headerRowCount", "totalsRowCount"}:
                table.set(
                    mutation,
                    {"headerRowCount": "0", "totalsRowCount": "1"}.get(mutation, "Renamed"),
                )
            elif mutation == "column_order":
                columns[:] = reversed(list(columns))
            elif mutation == "column_name":
                columns[0].set("name", "Renamed")
            elif mutation == "column_formula":
                columns[1].find(f"{ns}calculatedColumnFormula").text = "A2*100"
            elif mutation == "column_metadata":
                columns[0].set("uniqueName", "different-column")
            elif mutation == "sheet":
                source = ElementTree.fromstring(members[sheet_path])
                target = ElementTree.fromstring(members["xl/worksheets/sheet2.xml"])
                parts = source.find(f"{ns}tableParts")
                source.remove(parts)
                target.append(parts)
                members[sheet_path] = ElementTree.tostring(source)
                members["xl/worksheets/sheet2.xml"] = ElementTree.tostring(target)
                members["xl/worksheets/_rels/sheet2.xml.rels"] = members.pop(
                    "xl/worksheets/_rels/sheet1.xml.rels"
                )
            elif mutation == "defaults":
                table.attrib.pop("headerRowCount")
                table.set("totalsRowCount", "0")
                table.set("totalsRowShown", "true")
                table.set("tableType", "worksheet")
                columns[0].set("totalsRowFunction", "none")
                columns[1].find(f"{ns}calculatedColumnFormula").set("array", "false")
            elif mutation == "package_ids":
                table.set("id", "27")
                rels = "xl/worksheets/_rels/sheet1.xml.rels"
                members[rels] = members[rels].replace(
                    b'Target="/xl/tables/table1.xml"', b'Target="../tables/table1.xml"'
                )
            members[table_path] = ElementTree.tostring(table)
            source = ElementTree.fromstring(members[sheet_path])
            source.find(f"{ns}sheetData/{ns}row/{ns}c[@r='C1']/{ns}v").text = str(value)
            members[sheet_path] = ElementTree.tostring(source)

        _rewrite_zip(output, change)
        assert recalc._cells(output.read_bytes()) == recalc._cells(original)
        if mutation == "ref":
            with ZipFile(io.BytesIO(original)) as before, ZipFile(output) as after:
                assert [
                    name for name in before.namelist() if before.read(name) != after.read(name)
                ] == ["xl/tables/table1.xml"]
        return subprocess.CompletedProcess(command, 0, "controlled conversion", "")

    monkeypatch.setattr(recalc, "_engine_path", lambda: "soffice-test")
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 1.0 fault-injection")
    monkeypatch.setattr(
        "app.application.employee_runtime.continuity_tool_wait.run_process", conversion
    )
    report = _verify(path, [{"sheet": "Data", "ref": "C1", "value": value}])
    if mutation in {None, "defaults", "package_ids"}:
        assert report["status"] == "verified" and report["expected_values_verified"], report
    else:
        assert report["status"] == "inconclusive", report
        assert report["code"] == "formula_recalculation_input_context_changed", report
        assert not report["formula_recalculation_verified"]
        assert not report.get("expected_values_verified")
    assert report["source_unchanged"] and path.read_bytes() == original


@pytest.mark.parametrize(
    "mutation",
    ["hidden", "hidden_default", "number_format", "number_format_alias", "full_precision_format"],
)
def test_controlled_conversion_binds_visibility_and_displayed_precision(
    tmp_path, monkeypatch, mutation
):
    """Controlled outputs isolate context changes; they are not real-engine acceptance."""
    path = tmp_path / "display.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    hidden = mutation.startswith("hidden")
    if hidden:
        sheet["A1"], sheet["A2"], sheet["B1"] = 3, 7, "=SUBTOTAL(109,A1:A2)"
        stale, correct = "3", 10
    else:
        sheet["A1"], sheet["B1"] = 1.24, "=A1"
        sheet["A1"].number_format = "0.00"
        book.calculation.fullPrecision = mutation == "full_precision_format"
        stale, correct = "1.2", 1.24
    book.save(path)
    book.close()

    def stale_cache(members):
        members["xl/worksheets/sheet1.xml"] = members["xl/worksheets/sheet1.xml"].replace(
            b"</f><v></v>", f"</f><v>{stale}</v>".encode()
        )

    _rewrite_zip(path, stale_cache)
    original = path.read_bytes()
    changed_meaning = mutation in {"hidden", "number_format"}
    expected = float(stale) if changed_meaning else correct

    def conversion(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "LibreOffice 1.0 fault-injection\n", "")
        output = Path(command[command.index("--outdir") + 1]) / "source.xlsx"
        output.write_bytes(original)

        def change(members):
            sheet_path = "xl/worksheets/sheet1.xml"
            if hidden:
                flag = "1" if changed_meaning else "false"
                members[sheet_path] = members[sheet_path].replace(
                    b'<row r="2">', f'<row r="2" hidden="{flag}">'.encode()
                )
            else:
                code = "0.00" if mutation == "number_format_alias" else "0.0"
                members["xl/styles.xml"] = (
                    members["xl/styles.xml"]
                    .replace(
                        b'<numFmts count="0"/>',
                        (
                            '<numFmts count="1"><numFmt numFmtId="164" '
                            f'formatCode="{code}"/></numFmts>'
                        ).encode(),
                    )
                    .replace(b'numFmtId="2"', b'numFmtId="164"')
                )
            if not changed_meaning:
                members[sheet_path] = members[sheet_path].replace(
                    f"</f><v>{stale}</v>".encode(), f"</f><v>{correct}</v>".encode()
                )

        _rewrite_zip(output, change)
        assert recalc._cells(output.read_bytes()) == recalc._cells(original)
        if changed_meaning:
            with ZipFile(io.BytesIO(original)) as before, ZipFile(output) as after:
                assert [
                    name for name in before.namelist() if before.read(name) != after.read(name)
                ] == ["xl/worksheets/sheet1.xml" if hidden else "xl/styles.xml"]
        return subprocess.CompletedProcess(command, 0, "controlled conversion", "")

    monkeypatch.setattr(recalc, "_engine_path", lambda: "soffice-test")
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", "LibreOffice 1.0 fault-injection")
    monkeypatch.setattr(
        "app.application.employee_runtime.continuity_tool_wait.run_process", conversion
    )
    report = _verify(path, [{"sheet": "Data", "ref": "B1", "value": expected}])
    if changed_meaning:
        assert report["status"] == "inconclusive", report
        assert report["code"] == "formula_recalculation_input_context_changed", report
        assert not report["formula_recalculation_verified"]
        assert not report.get("expected_values_verified")
    else:
        assert report["status"] == "verified" and report["expected_values_verified"], report
    assert report["source_unchanged"] and path.read_bytes() == original


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
