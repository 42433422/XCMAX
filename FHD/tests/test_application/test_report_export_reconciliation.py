"""A valid XLSX receipt must still agree with the original authorized SQL report."""

from __future__ import annotations

import copy
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from sqlalchemy import event

from app.application.agent_orchestrator.artifact_files import store_scoped_run_file
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.db.models import SalesOrderItem
from app.domain.shared_services.report_export import export_report_to_excel
from app.domain.shared_services.tools_workflow_erp import _registered_router_reports
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_enterprise_acceptance import _seed_order
from tests.test_application.test_verification_readback import invocation


@pytest.fixture
def report_case(trusted_actor, monkeypatch, tmp_path):
    from app.db.models.permission import DEFAULT_ROLES

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    permissions = next(row["permissions"] for row in DEFAULT_ROLES if row["name"] == "admin")
    actor = trusted_actor(role="admin", permissions=permissions)
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    monkeypatch.setattr("app.db.session.SessionLocal", actor.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.artifact_files.get_app_data_dir", lambda: str(tmp_path)
    )
    _seed_order(actor)
    case = invocation(
        actor,
        "reports",
        "export",
        {"report_type": "sales", "group_by": "product", "order_no": "EC-ORDER-1"},
    )
    case.context.update(
        call_id=case.call.call_id,
        node_id=case.step.node_id,
        input_sha256=canonical_hash(case.step.params),
    )
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("reports", "export"), case.context
    )
    return actor, case


def produce(actor, case):
    with tenant_scope(actor.tenant_id):
        return _registered_router_reports("export", case.step.params, case.context, "", "销售报表")


def check(case, output):
    case.step.status = case.call.status = "completed"
    case.step.output = copy.deepcopy(output)
    case.call.output = copy.deepcopy(output)
    bind_execution_receipt(case.call)
    return verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)


@pytest.mark.parametrize("corruption", ["amount", "quantity", "extra_row", "column", "sheet"])
def test_valid_file_hash_cannot_certify_another_business_report(report_case, corruption):
    actor, case = report_case
    rows = [{"product_name": "经营验收产品", "quantity": 10, "amount": 1000}]
    if corruption in {"amount", "quantity"}:
        rows[0][corruption] += 1
    elif corruption == "extra_row":
        rows.append({"product_name": "另一个订单", "quantity": 2, "amount": 600})
    elif corruption == "column":
        rows[0]["unapproved"] = "extra"
    body = export_report_to_excel("other" if corruption == "sheet" else "sales", rows, "sales")
    artifact = store_scoped_run_file(body["data"], name=body["filename"], context=case.context)
    output = {"success": True, "row_count": len(rows), "artifacts": [artifact]}
    assert check(case, output)["accepted"] is False


def test_source_drift_does_not_certify_historical_export_as_current(report_case):
    actor, case = report_case
    output = produce(actor, case)
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.query(SalesOrderItem).one().amount = 900
    assert check(case, output)["accepted"] is False


def test_export_requires_original_invocation_binding(report_case):
    actor, case = report_case
    output = produce(actor, case)
    output["artifacts"][0]["metadata"].pop("call_id", None)
    assert check(case, output)["accepted"] is False


def test_formula_text_cannot_be_delivered_as_an_executable_formula(report_case):
    actor, case = report_case
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.query(SalesOrderItem).one().product_name = "=1+1"
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("reports", "export"), case.context
    )
    output = produce(actor, case)
    assert check(case, output)["accepted"] is True
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file

    book = load_workbook(BytesIO(read_verified_run_file(case.run.run_id, output["artifacts"][0])))
    assert book["sales"]["A2"].data_type == "s"
    book["sales"]["A2"].data_type = "f"
    content = BytesIO()
    book.save(content)
    book.close()
    output["artifacts"] = [
        store_scoped_run_file(content.getvalue(), name="sales.xlsx", context=case.context)
    ]
    assert check(case, output)["accepted"] is False


def test_revoked_report_permission_cannot_read_business_source(report_case):
    from app.db.models.permission import Role

    actor, case = report_case
    output = produce(actor, case)
    with actor.factory.begin() as db:
        db.query(Role).filter_by(name="admin").one().permissions = []
    assert check(case, output)["accepted"] is False


@pytest.mark.parametrize("unordered", [False, True])
def test_forged_workbook_dimensions_cannot_hide_a_far_column(report_case, monkeypatch, unordered):
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file

    actor, case = report_case
    output = produce(actor, case)
    book = load_workbook(BytesIO(read_verified_run_file(case.run.run_id, output["artifacts"][0])))
    book["sales"].cell(row=2, column=202, value="=1+1")
    actual = BytesIO()
    book.save(actual)
    book.close()
    forged = BytesIO()
    with ZipFile(actual) as source, ZipFile(forged, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                assert b'<dimension ref="A1:GT2"/>' in content
                content = content.replace(b'<dimension ref="A1:GT2"/>', b'<dimension ref="A1:C2"/>')
                if unordered:
                    far_cell = b'<c r="GT2"><f>1+1</f><v></v></c>'
                    assert content.count(far_cell) == 1
                    assert content.count(b'<c r="B2"') == 1
                    # The read-only row renderer uses its last XML cell's
                    # column; moving GT2 before B2/C2 used to hide the far cell.
                    content = content.replace(far_cell, b"").replace(
                        b'<c r="B2"', far_cell + b'<c r="B2"'
                    )
            target.writestr(entry, content)
    output["artifacts"] = [
        store_scoped_run_file(forged.getvalue(), name="sales.xlsx", context=case.context)
    ]

    def no_unbounded_read(*_args, **_kwargs):
        pytest.fail("actual worksheet coordinates must be checked before pandas reads the file")

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_reports.compare_run_file_table",
        no_unbounded_read,
    )
    assert check(case, output)["accepted"] is False


def test_unordered_in_budget_text_cells_cannot_hide_an_extra_business_column(report_case):
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file

    actor, case = report_case
    output = produce(actor, case)
    book = load_workbook(BytesIO(read_verified_run_file(case.run.run_id, output["artifacts"][0])))
    expected = [
        ("product_name", "quantity", "amount"),
        ("经营验收产品", 10, 1000),
    ]
    assert list(book["sales"].values) == expected
    book["sales"]["D1"] = "unapproved_column"
    book["sales"]["D2"] = "wrong_business_value"
    actual = BytesIO()
    book.save(actual)
    book.close()
    forged = BytesIO()
    with ZipFile(actual) as source, ZipFile(forged, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                assert b'<dimension ref="A1:D2"/>' in content
                for index in (1, 2):
                    start = content.index(f'<c r="D{index}"'.encode())
                    end = content.index(b"</c>", start) + len(b"</c>")
                    cell = content[start:end]
                    anchor = f'<c r="B{index}"'.encode()
                    assert b"<f>" not in cell and content.count(anchor) == 1
                    content = content.replace(cell, b"").replace(anchor, cell + anchor)
            target.writestr(entry, content)
    # The actual file still contains the extra column; only the read-only
    # row renderer can lose D when the last XML cell in each row is C.
    book = load_workbook(BytesIO(forged.getvalue()))
    assert list(book["sales"].values) == [
        (*expected[0], "unapproved_column"),
        (*expected[1], "wrong_business_value"),
    ]
    book.close()
    output["artifacts"] = [
        store_scoped_run_file(forged.getvalue(), name="sales.xlsx", context=case.context)
    ]
    assert check(case, output)["accepted"] is False


@pytest.mark.parametrize(
    "kind,filters", [("inventory", {"order_no": "EC-ORDER-1"}), ("purchase", {"customer_id": 7})]
)
def test_inapplicable_business_filters_are_rejected_instead_of_silently_ignored(kind, filters):
    from app.domain.shared_services.report_service import ReportService

    with pytest.raises(ValueError, match="unsupported report filters"):
        ReportService().query_report(kind, filters)


@pytest.mark.parametrize("rows", [[], [{"product_name": "unrelated", "quantity": 1, "amount": 1}]])
def test_explicit_rows_cannot_bypass_the_approved_order_query(report_case, monkeypatch, rows):
    from app.domain.shared_services.report_service import ReportService

    actor, original = report_case
    case = invocation(actor, "reports", "export", {**original.step.params, "data": rows})
    case.context.update(
        call_id=case.call.call_id,
        node_id=case.step.node_id,
        input_sha256=canonical_hash(case.step.params),
    )
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("reports", "export"), case.context
    )
    assert case.call.metadata["verification_contract"]["report_baseline"]["status"] == "ambiguous"

    def no_export(*_args, **_kwargs):
        pytest.fail("ambiguous source must be rejected before file creation")

    with monkeypatch.context() as patch:
        patch.setattr(ReportService, "export_to_excel", no_export)
        output = produce(actor, case)
    assert output["success"] is False
    assert output["error_code"] == "report_source_ambiguous"

    # A historically saved, correctly hashed receipt also cannot certify the query.
    case.call.metadata["verification_contract"]["report_baseline"] = {
        "status": "explicit_table",
        "report_type": "sales",
    }
    body = export_report_to_excel("sales", rows, "sales")
    artifact = store_scoped_run_file(body["data"], name=body["filename"], context=case.context)
    assert (
        check(case, {"success": True, "row_count": len(rows), "artifacts": [artifact]})["accepted"]
        is False
    )


def test_report_reconciliation_is_read_only_and_checks_exact_cells(report_case):
    actor, case = report_case
    output = produce(actor, case)
    writes = []
    engine = actor.factory.kw["bind"]

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            result = check(case, output)
            assert result["accepted"], result
            evidence = result["checks"][-1]["evidence"]
            assert evidence["business_rows_match"] is True
            assert evidence["row_count"] == 1
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file

    book = load_workbook(BytesIO(read_verified_run_file(case.run.run_id, output["artifacts"][0])))
    assert list(book["sales"].values) == [
        ("product_name", "quantity", "amount"),
        ("经营验收产品", 10, 1000),
    ]
    book.close()


@pytest.mark.parametrize("kind,scope", [("sales", "customer_id"), ("inventory", "warehouse_id")])
def test_explicit_zero_scope_cannot_expand_report_to_all_business_records(report_case, kind, scope):
    from app.domain.shared_services.report_service import ReportService

    actor, _ = report_case
    with tenant_scope(actor.tenant_id):
        service = ReportService()
        assert service.query_report(kind, {})["data"]
        # An explicit, nonexistent identity must remain a filter. Treating it
        # as an omitted value makes exporter and readback agree on the wrong scope.
        assert service.query_report(kind, {scope: 0})["data"] == []
