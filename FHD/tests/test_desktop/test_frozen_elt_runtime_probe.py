"""The packaged dependency gate executes the real synthetic XLSX derivation path."""

from __future__ import annotations

import builtins
import faulthandler
import os
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.application import reviewed_excel_template
from XCAGI import run_fastapi


def test_elt_probe_derives_and_reads_back_without_starting_server(monkeypatch, capsys):
    calls = []
    derive = reviewed_excel_template.derive_document_workbook

    def record(source, fragments, **kwargs):
        result = derive(source, fragments, **kwargs)
        calls.append((source, result, fragments))
        return result

    monkeypatch.setattr(reviewed_excel_template, "derive_document_workbook", record)
    run_fastapi._verify_frozen_elt_runtime()

    assert len(calls) == 1
    source, result, fragments = calls[0]
    assert fragments == [{"sheet": "Synthetic", "range": "A1:B3"}]
    for body in (source, result):
        workbook = load_workbook(BytesIO(body), data_only=False)
        try:
            assert workbook.sheetnames == ["Synthetic"]
            assert workbook.active["B3"].value == "=SUM(B2:B2)"
            assert workbook.active.auto_filter.ref == "A1:B3"
        finally:
            workbook.close()
    assert "XLSX inspect/derive/readback" in capsys.readouterr().out


def test_elt_probe_fails_closed_when_xml_runtime_is_missing(monkeypatch):
    original_import = builtins.__import__

    def without_safe_xml(name, *args, **kwargs):
        if name == "defusedxml" or name.startswith("defusedxml."):
            raise ModuleNotFoundError("No module named 'defusedxml'", name="defusedxml")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_safe_xml)
    with pytest.raises(ModuleNotFoundError, match="defusedxml"):
        run_fastapi._verify_frozen_elt_runtime()


def test_elt_probe_rejects_corrupt_derived_output(monkeypatch):
    derive = reviewed_excel_template.derive_document_workbook

    def corrupt(source, fragments, **kwargs):
        workbook = load_workbook(BytesIO(derive(source, fragments, **kwargs)))
        try:
            workbook.active["B3"] = 999
            output = BytesIO()
            workbook.save(output)
            return output.getvalue()
        finally:
            workbook.close()

    monkeypatch.setattr(reviewed_excel_template, "derive_document_workbook", corrupt)
    with pytest.raises(RuntimeError, match="did not preserve"):
        run_fastapi._verify_frozen_elt_runtime()


@pytest.mark.parametrize("fails", [False, True])
def test_probe_cli_isolates_before_imports_and_bypasses_normal_bootstrap(
    monkeypatch, tmp_path, fails
):
    events = []
    original = "postgresql://synthetic.invalid/not-used"
    database_keys = (
        "DATABASE_URL",
        "VECTOR_DB_URL",
        "XCAGI_DESKTOP_DATABASE_URL",
        "XCAGI_DESKTOP_VECTOR_DB_URL",
    )
    for name in database_keys:
        monkeypatch.setenv(name, original)

    def forbid_normal_startup(*args):
        raise AssertionError("probe entered normal startup")

    def critical_runtime():
        assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
        assert os.environ["XCAGI_DESKTOP_MODE"] == "1"
        assert os.environ["XCAGI_DATA_DIR"] == str(tmp_path)
        assert all(
            os.environ[name] == "sqlite:///" + (tmp_path / "data/probe.db").as_posix()
            for name in database_keys
        )
        events.append("critical-runtime")
        if fails:
            raise RuntimeError("synthetic frozen import failure")

    def watchdog(seconds, *, repeat, file):
        assert seconds == 60 and repeat
        assert file.name == str(tmp_path / "logs/frozen-runtime-probe.log")
        events.append("watchdog-start")

    monkeypatch.setattr(run_fastapi, "_apply_no_console_child_defaults", forbid_normal_startup)
    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", forbid_normal_startup)
    monkeypatch.setattr(run_fastapi, "_load_dotenv_if_present", forbid_normal_startup)
    monkeypatch.setattr(run_fastapi, "_verify_frozen_critical_runtime", critical_runtime)
    monkeypatch.setattr(faulthandler, "dump_traceback_later", watchdog)
    monkeypatch.setattr(
        faulthandler, "cancel_dump_traceback_later", lambda: events.append("watchdog-cancel")
    )

    arguments = ["--verify-frozen-critical-runtime", "--data-dir", str(tmp_path)]
    if fails:
        with pytest.raises(SystemExit) as error:
            run_fastapi.main(arguments)
        assert error.value.code == 1
        assert "synthetic frozen import failure" in (
            tmp_path / "logs/frozen-runtime-probe.log"
        ).read_text(encoding="utf-8")
    else:
        run_fastapi.main(arguments)

    assert events == ["watchdog-start", "critical-runtime", "watchdog-cancel"]
    assert all(os.environ[name] == original for name in database_keys)
