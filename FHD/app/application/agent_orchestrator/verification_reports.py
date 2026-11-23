"""Compare a delivered report with the frozen, independently read tenant/Mod query."""

from __future__ import annotations

from io import BytesIO
from typing import Any, BinaryIO, Protocol, cast

from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.worksheet._reader import WorkSheetParser

from app.application.agent_orchestrator.artifact_files import (
    compare_run_file_table,
    read_verified_run_file,
)
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.verification_readback import _files, _report
from app.application.agent_orchestrator.verification_transactions import _transaction_read_scope
from app.domain.shared_services.report_service import (
    ReportService,
    report_source_ambiguous,
    resolve_report_type,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class _ReadOnlyReportSheet(Protocol):
    """Internal stream contract of the pinned openpyxl read-only implementation."""

    _shared_strings: list[str]

    def _get_source(self) -> BinaryIO: ...


def _read_report(kind: str, params: dict, context: dict) -> dict:
    with _transaction_read_scope(context, {"tool.reports.export"}, "report"):
        report = ReportService().query_report(kind, params)
    rows = report.get("data")
    if (
        report.get("success") is not True
        or not isinstance(rows, list)
        or len(rows) > 50_000
        or any(not isinstance(row, dict) or len(row) > 200 for row in rows)
        or (kind == "sales" and params.get("order_no") and not rows)
    ):
        raise ValueError("report authority unavailable")
    return report


def _snapshot(kind: str, report: dict) -> dict:
    return {
        "status": "observed",
        "report_type": kind,
        "rows_sha256": canonical_hash(report["data"]),
        "summary_sha256": canonical_hash(report.get("summary") or {}),
        "row_count": len(report["data"]),
    }


def capture_report_baseline(run: Any, step: Any, context: dict) -> dict:
    """Freeze SQL observations before export; never trust producer-supplied source rows."""
    kind = resolve_report_type(step.params, run.message)
    if report_source_ambiguous(step.params):
        return {"status": "ambiguous", "report_type": kind}
    if step.params.get("data") is not None:
        return {"status": "explicit_table", "report_type": kind}
    try:
        return _snapshot(kind, _read_report(kind, step.params, context))
    except RECOVERABLE_ERRORS + (HTTPException,):
        return {"status": "unavailable", "report_type": kind}


def verify_report_export(run, step, call, output: dict, context: dict) -> dict:
    """Read-only: original query plus actual file bytes, without rerunning the exporter."""
    if report_source_ambiguous(step.params):
        return _report("failed", "report_source_ambiguous", "report_sql")
    integrity = _files(run, step, call, output, context, ".xlsx")
    if integrity["status"] != "verified":
        return integrity
    artifacts = output["artifacts"]
    if len(artifacts) != 1:
        return _report("failed", "report_artifact_count_mismatch", "report_sql")
    baseline = (call.metadata.get("verification_contract") or {}).get("report_baseline") or {}
    kind = resolve_report_type(step.params, run.message)
    rows = step.params.get("data")
    business = rows is None
    if business:
        if baseline.get("status") != "observed" or baseline.get("report_type") != kind:
            return _report("inconclusive", "report_baseline_unavailable", "report_sql")
        report = _read_report(kind, step.params, context)
        if _snapshot(kind, report) != baseline:
            return _report("inconclusive", "report_source_changed", "report_sql")
        rows = report["data"]
    if not isinstance(rows, list):
        return _report("failed", "report_rows_invalid", "report_sql")
    content = read_verified_run_file(run.run_id, artifacts[0])
    book = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    try:
        if book.sheetnames != [kind]:
            return _report("failed", "report_sheet_mismatch", "report_sql")
        sheet = book[kind]
        if (
            sheet.max_row is None
            or sheet.max_column is None
            or sheet.max_row > 50_001
            or sheet.max_column > 200
        ):
            return _report("inconclusive", "report_verification_budget_exceeded", "report_sql")
        # Use the pinned read-only worksheet parser before row expansion can
        # truncate out-of-order cells or trust a forged declared dimension.
        stream = cast(_ReadOnlyReportSheet, sheet)
        with stream._get_source() as source:
            parser = WorkSheetParser(
                source,
                stream._shared_strings,
                data_only=False,
                epoch=book.epoch,
            )
            previous_row = 0
            for index, (row_index, cells) in enumerate(parser.parse(), start=1):
                if (
                    index > 50_001
                    or row_index > 50_001
                    or any(cell["row"] > 50_001 or cell["column"] > 200 for cell in cells)
                ):
                    return _report(
                        "inconclusive", "report_verification_budget_exceeded", "report_sql"
                    )
                if row_index <= previous_row or any(cell["row"] != row_index for cell in cells):
                    return _report("failed", "report_cell_order_invalid", "report_sql")
                previous_row = row_index
                previous_column = 0
                for cell in cells:
                    if cell["column"] <= previous_column:
                        return _report("failed", "report_cell_order_invalid", "report_sql")
                    previous_column = cell["column"]
                    if cell["data_type"] == "f":
                        return _report("failed", "report_formula_not_authorized", "report_sql")
    finally:
        book.close()
    comparison = compare_run_file_table(rows, content, ".xlsx")
    if type(output.get("row_count")) is not int or output["row_count"] != len(rows):
        return _report("failed", "report_row_count_mismatch", "report_sql")
    result = _report(
        "verified",
        "result_verified",
        "report_sql" if business else "approved_table",
        report_type=kind,
        order_no=step.params.get("order_no"),
        tenant_id=str(context["tenant_id"]),
        artifact_sha256=artifacts[0]["metadata"]["sha256"],
        business_rows_match=business,
        verification_scope="business_report" if business else "approved_table",
        **comparison,
    )
    result["checks"] = integrity["checks"] + result["checks"]
    return result
