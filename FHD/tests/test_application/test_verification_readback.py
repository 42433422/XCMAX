"""Independent readback uses real SQLite receipts and real file bytes."""

from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.application.agent_orchestrator.artifact_files import (
    artifact_path,
    store_run_file,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_permission import (
    _fingerprint,
    idempotency_scope_key,
)
from app.application.agent_orchestrator.verification_readback import (
    verify_independent_result,
)
from app.application.customer_creation_receipt import (
    customer_creation_claim,
    record_customer_creation,
)
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_catalog_product_edits import catalog as catalog
from tests.test_application.test_owned_mixed_source_substrate import host as host


@pytest.fixture
def owner(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(
        role="admin",
        permissions=["customer.view", "customer.edit", "product.view", "dataset.read"],
    )
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", actor.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.artifact_files.get_app_data_dir",
        lambda: str(tmp_path),
    )
    return actor


def invocation(owner, tool="customers", action="create", params=None):
    step = AgentStep(
        node_id="effect",
        tool_id=tool,
        action=action,
        params=(
            params
            if params is not None
            else {"customer_name": "Receipt customer", "contact_phone": "123"}
        ),
    )
    run = AgentRun(
        user_id=str(owner.user_id),
        message="Synthetic verification task",
        steps=[step],
        metadata={"runtime_context": copy.deepcopy(owner.context)},
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=tool,
        action=action,
        params=copy.deepcopy(step.params),
    )
    run.tool_calls.append(call)
    context = {
        **owner.context,
        **task_execution_context(run, step),
        "run_id": run.run_id,
        "step_id": step.step_id,
    }
    call.metadata["idempotency_key"] = context["idempotency_key"]
    return SimpleNamespace(run=run, step=step, call=call, context=context)


def verify(case, output=None):
    return verify_independent_result(
        run=case.run,
        step=case.step,
        call=case.call,
        context=case.context,
        output=output if output is not None else {"success": True, "summary": "done"},
    )


def test_customer_export_uses_original_owned_file_and_rejects_changed_receipts(
    owner, tmp_path, monkeypatch
):
    from openpyxl import load_workbook

    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.customer_app_service import CustomerApplicationService

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    case = invocation(owner, action="export", params={"keyword": "Receipt"})
    context = {
        **case.context,
        "node_id": case.step.node_id,
        "call_id": case.call.call_id,
        "input_sha256": canonical_hash(case.step.params),
    }
    for tenant, name in (
        (owner.tenant_id, "Receipt owned customer"),
        (owner.tenant_id + 1, "Receipt foreign customer"),
    ):
        with tenant_scope(tenant), owner.factory.begin() as db:
            db.add(PurchaseUnit(tenant_id=tenant, unit_name=name))
    with tenant_scope(owner.tenant_id):
        output = CustomerApplicationService().export_to_excel(
            keyword="Receipt", runtime_context=context
        )
    assert output["success"] is True
    path = Path(output["file_path"])
    book = load_workbook(path, read_only=True)
    try:
        rows = list(book.active.iter_rows(values_only=True))
        assert len(rows) == 2 and rows[1][1] == "Receipt owned customer"
    finally:
        book.close()

    def no_export(*_args, **_kwargs):
        raise AssertionError("readback must not invoke customer export")

    monkeypatch.setattr(CustomerApplicationService, "export_to_excel", no_export)
    for _ in range(2):
        assert verify(case, output)["status"] == "verified"
    for field in (
        "run_id",
        "tenant_id",
        "owner_user_id",
        "step_id",
        "node_id",
        "call_id",
        "params_sha256",
    ):
        forged = copy.deepcopy(output)
        forged["artifacts"][0]["metadata"].pop(field)
        assert verify(case, forged)["code"] == "result_artifact_scope_mismatch"
    content = path.read_bytes()
    path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    assert verify(case, output)["code"] == "result_evidence_mismatch"


def create_customer(owner, case, *, receipt=True, tenant=None):
    tenant = owner.tenant_id if tenant is None else tenant
    key = idempotency_scope_key(case.context, "customers", "create", case.step.params)
    with tenant_scope(tenant), owner.factory.begin() as db:
        row = PurchaseUnit(tenant_id=tenant, unit_name="Receipt customer", contact_phone="123")
        db.add(row)
        db.flush()
        if receipt:
            with customer_creation_claim(
                key, _fingerprint(case.step.params, case.context), str(tenant)
            ):
                record_customer_creation(db, row)
        return row.id


def test_customer_transaction_receipt_and_fresh_readback_do_not_reexecute(owner):
    case = invocation(owner)
    customer_id = create_customer(owner, case)
    writes = []
    engine = owner.factory.kw["bind"]

    def observe(_conn, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            result = verify(case, {"success": True, "id": customer_id})
            assert result["status"] == "verified"
            assert result["checks"][0]["evidence"]["customer_id"] == customer_id
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "scenario", ["no_receipt", "different_tenant", "changed_request", "changed_row"]
)
def test_customer_same_name_or_claimed_success_is_not_original_evidence(owner, scenario):
    case = invocation(owner)
    customer_id = create_customer(
        owner,
        case,
        receipt=scenario != "no_receipt",
        tenant=owner.tenant_id + 1 if scenario == "different_tenant" else None,
    )
    if scenario == "changed_request":
        case.step.params["contact_phone"] = "456"
        case.call.params = copy.deepcopy(case.step.params)
    if scenario == "changed_row":
        with tenant_scope(owner.tenant_id), owner.factory.begin() as db:
            db.get(PurchaseUnit, customer_id).contact_phone = "456"
    result = verify(case, {"success": True, "id": customer_id, "verified": True})
    assert result["status"] == "inconclusive"
    assert result["code"] == "result_receipt_unavailable"


def test_customer_returned_identifier_must_match_original_transaction(owner):
    case = invocation(owner)
    customer_id = create_customer(owner, case)
    result = verify(case, {"success": True, "id": customer_id + 1})
    assert result["status"] == "failed"
    assert result["code"] == "result_customer_mismatch"


def test_current_read_permission_is_required_even_with_original_receipt(owner):
    from app.db.models.permission import Role

    case = invocation(owner)
    create_customer(owner, case)
    with owner.factory.begin() as db:
        role = db.query(Role).filter_by(name="admin").one()
        role.permissions = [p for p in role.permissions if p.code != "customer.view"]
    result = verify(case)
    assert result["status"] == "inconclusive"
    assert result["code"] == "result_read_permission_unavailable"


@pytest.mark.parametrize("field", ["tenant_id", "user_id", "run_id", "step_id"])
def test_mismatched_execution_scope_cannot_read_customer_source(owner, monkeypatch, field):
    case = invocation(owner)
    case.context[field] = "different"
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_permission._customer_create_effect",
        lambda *a, **kw: pytest.fail("invalid scope reached business source"),
    )
    assert verify(case)["code"] == "result_scope_mismatch"


def _content(kind):
    if kind == "csv":
        return b"customer,quantity\nexample,3\n"
    stream = io.BytesIO()
    if kind == "xlsx":
        from openpyxl import Workbook

        document = Workbook()
        document.active.append(["Customer", "Quantity"])
        document.active.append(["Example", 3])
    elif kind == "docx":
        from docx import Document

        document = Document()
        document.add_paragraph("Synthetic verified document")
    elif kind == "pptx":
        from pptx import Presentation

        document = Presentation()
        document.slides.add_slide(document.slide_layouts[0])
    else:
        from pypdf import PdfWriter

        pdf_writer = PdfWriter()
        pdf_writer.add_blank_page(width=72, height=72)
        pdf_writer.write(stream)
        return stream.getvalue()
    document.save(stream)
    return stream.getvalue()


def file_result(owner, case, kind="xlsx", *, run_id=None, content=None):
    artifact = store_run_file(
        run_id or case.run.run_id,
        _content(kind) if content is None else content,
        name="result." + kind,
        owner_user_id=owner.user_id,
        tenant_id=str(owner.tenant_id),
    )
    return {"success": True, "artifacts": [artifact]}


@pytest.mark.parametrize(
    "kind,employee",
    [
        ("xlsx", "excel-generate-employee"),
        ("csv", "csv-generate-employee"),
        ("docx", "word-generate-employee"),
        ("pdf", "pdf-generate-employee"),
        ("pptx", "ppt-generate-employee"),
    ],
)
def test_registered_generation_reads_real_run_owned_file_bytes(owner, kind, employee):
    case = invocation(owner, "employee", "execute", {"employee_id": employee})
    output = file_result(owner, case, kind)
    result = verify(case, output)
    assert result["status"] == "verified"
    evidence = result["checks"][0]["evidence"]
    assert evidence["sha256"] == output["artifacts"][0]["metadata"]["sha256"]
    assert evidence["format"] == kind
    assert evidence["run_id"] == case.run.run_id
    assert evidence["verification_scope"] == "artifact_integrity"


@pytest.fixture
def office_output(owner, monkeypatch, tmp_path):
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.tools.workflow_tools.documents import generate_office_document
    from app.domain.shared_services.kitten_ai_document import pickup

    directory = tmp_path / "pickup"
    directory.mkdir()
    monkeypatch.setattr(pickup, "_CACHED_BASE", directory)

    def create(kind="docx", *, native=False):
        case = invocation(
            owner,
            "generate_office_document",
            "execute",
            {
                "user_request": "Produce a sample document",
                "output_format": kind,
            },
        )
        case.context.update(
            node_id=case.step.node_id,
            call_id=case.call.call_id,
            input_sha256=canonical_hash(case.step.params),
        )
        content = _content(kind)
        generated = []

        def generate(request, output_format):
            generated.append((request, output_format))
            return content, f"sample.{kind}"

        if native:
            from app.infrastructure.mods.mod_manager import import_mod_backend_py

            monkeypatch.setattr(
                "app.domain.shared_services.kitten_ai_document.generate.generate_office_file",
                generate,
            )
            mod_path = Path(__file__).resolve().parents[2] / "mods/tools/xcagi-planner-excel-tools"
            mod = import_mod_backend_py(str(mod_path), "xcagi-planner-excel-tools", "tool_handlers")
            output = json.loads(
                mod.run_native_tool(
                    "generate_office_document", case.step.params, runtime_context=case.context
                )
            )
            assert output["source"] == "mod:xcagi-planner-excel-tools"
        else:
            output = generate_office_document(
                case.step.params,
                generate,
                pickup.store_document_pickup,
                runtime_context=case.context,
            )
        return case, output, content, generated

    return create


@pytest.mark.parametrize("kind", ["docx", "xlsx"])
@pytest.mark.parametrize("native", [False, True], ids=["builtin", "native_mod"])
def test_office_generation_retains_pickup_and_independent_original_file(
    office_output, kind, native
):
    from app.domain.shared_services.kitten_ai_document.pickup import pop_document_pickup

    case, output, content, generated = office_output(kind, native=native)
    assert len(output["artifacts"]) == 1
    artifact = output["artifacts"][0]
    assert artifact["artifact_type"] == "office_document"
    assert artifact["uri"].startswith(f"/api/agent/runs/{case.run.run_id}/artifacts/")
    # Consuming the compatible one-time download does not destroy recovery proof.
    assert pop_document_pickup(output["pickup_token"])[0] == content
    assert pop_document_pickup(output["pickup_token"]) is None
    for _ in range(2):
        result = verify(case, output)
        assert result["status"] == "verified", result
        evidence = result["checks"][0]["evidence"]
        assert evidence["verification_scope"] == "artifact_integrity"
        assert evidence["format"] == kind
        assert evidence["sha256"] == artifact["metadata"]["sha256"]
    assert len(generated) == 1


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "owner_user_id",
        "tenant_id",
        "step_id",
        "node_id",
        "call_id",
        "params_sha256",
    ],
)
def test_office_result_requires_every_original_call_binding(office_output, field):
    case, output, _, _ = office_output()
    for omitted in (False, True):
        changed = copy.deepcopy(output)
        metadata = changed["artifacts"][0]["metadata"]
        if omitted:
            metadata.pop(field)
        else:
            metadata[field] = "another-execution"
        assert verify(case, changed)["code"] == "result_artifact_scope_mismatch"


@pytest.mark.parametrize("changed", ["bytes", "format", "pickup_only"])
def test_office_claims_cannot_replace_verified_file_bytes(office_output, changed):
    case, output, _, _ = office_output()
    artifact = output["artifacts"][0]
    if changed == "bytes":
        artifact_path(case.run.run_id, artifact["artifact_id"]).write_bytes(b"not the document")
    elif changed == "format":
        artifact["name"] = "sample.xlsx"
    else:
        artifact.pop("artifact_id")
        artifact["uri"] = output["download_url"]
    assert verify(case, output)["status"] != "verified"


@pytest.mark.parametrize(
    "scenario",
    ["tampered", "other_run", "wrong_owner", "empty", "invalid_format", "symlink"],
)
def test_file_claims_fail_on_source_drift_scope_and_invalid_content(owner, tmp_path, scenario):
    case = invocation(owner, "reports", "export", {})
    body = b"" if scenario == "empty" else b"not an XLSX" if scenario == "invalid_format" else None
    output = file_result(
        owner,
        case,
        run_id="other-run" if scenario == "other_run" else None,
        content=body,
    )
    artifact = output["artifacts"][0]
    path = artifact_path(case.run.run_id, artifact["artifact_id"])
    if scenario == "tampered":
        path.write_bytes(b"replacement")
    if scenario == "wrong_owner":
        artifact["metadata"]["owner_user_id"] = str(owner.user_id + 1)
    if scenario == "symlink":
        target = tmp_path / "elsewhere.xlsx"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    assert verify(case, output)["status"] != "verified"


def test_random_path_and_unknown_action_cannot_opt_in_to_file_verification(owner, tmp_path):
    case = invocation(owner, "inventory", "update", {})
    output = file_result(owner, case)
    output.update(verified=True, verification={"status": "verified"})
    assert verify(case, output)["code"] == "result_verifier_unavailable"
    case = invocation(owner, "reports", "export", {})
    path = tmp_path / "random.xlsx"
    path.write_bytes(_content("xlsx"))
    assert (
        verify(case, {"success": True, "file_path": str(path)})["code"] == "result_artifact_missing"
    )


@pytest.mark.parametrize(
    "outcome,expected", [("saved", "inconclusive"), ("rejected_no_effect", "failed")]
)
def test_catalog_historical_evidence_does_not_claim_a_new_current_success(
    owner, monkeypatch, outcome, expected
):
    case = invocation(owner, "catalog_products_v1", "append_price", {"operation_id": "original"})
    calls = []

    def readback(params, context, *, release):
        calls.append(release)
        return {
            "success": False,
            "operation_outcome": outcome,
            "current_matches": False,
            "historical_effect_verified": outcome == "saved",
            "business_verification": {"verified": True},
        }

    monkeypatch.setattr("app.mod_sdk.catalog_product_store.verify_catalog_action", readback)
    result = verify(case)
    assert result["status"] == expected
    assert result["checks"][0]["evidence"]["fresh_save"] is False
    assert calls == [False]


def test_catalog_source_unavailable_is_never_confirmed_by_executor_claim(owner, monkeypatch):
    case = invocation(owner, "catalog_products_v1", "append_price", {"operation_id": "original"})

    def unavailable(*a, **kw):
        raise TimeoutError("source unavailable")

    monkeypatch.setattr("app.mod_sdk.catalog_product_store.verify_catalog_action", unavailable)
    result = verify(case, {"success": True, "business_verification": {"verified": True}})
    assert result["status"] == "inconclusive"


def test_real_catalog_readback_preserves_host_and_source_without_dispatch(catalog):
    from app.application.agent_orchestrator.catalog_product_edit import action_context
    from tests.test_application.test_catalog_product_edits import (
        authority_images,
        dispatch,
        prepare,
    )

    run, _ = prepare(catalog)
    output, run = dispatch(catalog, run)
    assert output["success"] is True
    step = run.steps[0]
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
    )
    before = authority_images(catalog)
    result = verify_independent_result(
        run=run,
        step=step,
        call=call,
        output=output,
        context=action_context(run),
    )
    assert result["status"] == "verified", result
    assert result["checks"][0]["evidence"]["fresh_save"] is False
    assert authority_images(catalog) == before


def test_file_inner_xml_damage_is_a_failed_check_not_an_uncaught_error(owner):
    original = io.BytesIO(_content("docx"))
    broken = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(broken, "w") as target:
        for item in source.infolist():
            target.writestr(
                item,
                (b"<broken" if item.filename == "word/document.xml" else source.read(item)),
            )
    case = invocation(owner, "employee", "execute", {"employee_id": "word-generate-employee"})
    output = file_result(owner, case, "docx", content=broken.getvalue())
    assert verify(case, output)["status"] == "failed"


def test_missing_current_authorization_and_mismatched_employee_are_not_verified(owner):
    case = invocation(owner, "employee", "execute", {"employee_id": "word-generate-employee"})
    output = file_result(owner, case, "docx")
    output["employee_id"] = "another-employee"
    assert verify(case, output)["code"] == "result_employee_mismatch"
    output.pop("employee_id")
    case.context.pop("_actor_authorization")
    assert verify(case, output)["status"] == "inconclusive"


@pytest.mark.parametrize("field", ["step_id", "node_id", "call_id", "params_sha256"])
def test_file_claim_with_another_step_or_call_binding_is_rejected(owner, field):
    case = invocation(owner, "reports", "export", {})
    output = file_result(owner, case)
    output["artifacts"][0]["metadata"][field] = "another"
    assert verify(case, output)["code"] == "result_artifact_scope_mismatch"


@pytest.mark.parametrize("kind", ["xlsx", "csv"])
def test_export_compares_approved_rows_and_rejects_another_file_in_same_run(owner, kind):
    import pandas as pd

    rows = [{"Customer": "Example", "Quantity": 3}]
    case = invocation(owner, "excel_analysis", "export", {"rows": rows})
    stream = io.BytesIO()
    if kind == "csv":
        pd.DataFrame(rows).to_csv(stream, index=False)
    else:
        pd.DataFrame(rows).to_excel(stream, index=False)
    output = file_result(owner, case, kind, content=stream.getvalue())
    result = verify(case, output)
    assert result["status"] == "verified", result
    assert result["checks"][0]["evidence"]["input_rows_match"] is True
    case.step.params["rows"] = [{"Customer": "Another", "Quantity": 3}]
    case.call.params = copy.deepcopy(case.step.params)
    assert verify(case, output)["status"] == "failed"


@pytest.mark.parametrize("mod_id", ["", "original-mod"])
def test_customer_readback_restores_original_tenant_and_mod_then_leaves_caller_unchanged(
    owner, trusted_actor, monkeypatch, mod_id
):
    from app.infrastructure.tenant_scope import current_tenant_id
    from app.request_active_mod_ctx import (
        get_request_active_mod_id,
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    actor = trusted_actor(role="admin", mod_id=mod_id)
    case = invocation(actor)
    create_customer(actor, case)
    observed = []

    def source():
        observed.append((get_request_active_mod_id(), current_tenant_id()))
        return actor.factory()

    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", source)
    token = set_request_active_mod_id("unrelated-caller-mod")
    try:
        with tenant_scope(actor.tenant_id + 9):
            assert verify(case)["status"] == "verified"
            assert current_tenant_id() == actor.tenant_id + 9
            assert get_request_active_mod_id() == "unrelated-caller-mod"
    finally:
        reset_request_active_mod_id(token)
    assert observed == [(mod_id, actor.tenant_id)]
