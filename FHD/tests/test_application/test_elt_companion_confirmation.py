"""Independent chat approvals execute only the reviewed linked customer/product run."""

import copy
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from openpyxl import Workbook
from sqlalchemy import event

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.approval_grant import (
    issue_approval_grant,
    validate_approval_grant,
)
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_permission import clear_idempotent_replay_for_tests
from app.application.workflow.clarification_inputs import missing_tool_fields
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db import session as db_session
from app.db.models import Product, PurchaseUnit, ShipmentRecord
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.db.models.user import Session as UserSession
from app.infrastructure.auth.agent_principal import require_agent_principal
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_etl_preview_task_boundaries import preview_store as preview_store
from tests.test_application.test_etl_preview_task_boundaries import snapshot


def _linked_preview(store, monkeypatch):
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    monkeypatch.setattr(
        "app.application.elt.target_detection.detect_elt_target",
        lambda *_args, **_kwargs: {"target_type": "shipment_records"},
    )
    book = Workbook()
    sheet = book.active
    sheet.title = "出货"
    sheet.append(["购买单位", "产品名称", "型号", "桶数", "单价"])
    sheet.append(["已审客户", "已审产品", "REVIEW-1", 2, 12.5])
    content = BytesIO()
    book.save(content)
    content.seek(0)
    with store.factory() as db:
        upload = store.service.save_upload(
            db,
            owner_user_id=7,
            file_name="出货附表.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stream=content,
        )
        db.commit()
        parent = store.service.create_preview(
            db, owner_user_id=7, upload_id=upload["upload_id"], target_type="auto"
        )
    store.executor.futures[-1].result(timeout=10)
    parent = snapshot(store, parent["id"])
    linked = parent["details"]["linked_customer_products_preview"]
    child = snapshot(store, linked["run_id"])
    assert parent["status"] == child["status"] == "preview_ready"
    assert linked["preview_revision"] == child["preview_revision"]
    assert len(child["preview_revision"]) == 64
    return parent, child


def test_new_chat_confirmation_preserves_parent_receipt_and_executes_child_once(
    tmp_path, monkeypatch, request, preview_store, local_tools
):
    store = preview_store
    # Build the host authority after the ETL fixture, then keep business data on
    # its own database. Both fixtures otherwise replace the same session seams.
    actor = request.getfixturevalue("trusted_actor")(
        user_id=7, tenant_id=1, role="importer", permissions=["elt.execute"]
    )
    monkeypatch.setattr(db_session, "SessionLocal", store.factory)
    monkeypatch.setattr("app.db.SessionLocal", store.factory)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    with store.factory() as db:
        assert db.query(UserSession).filter_by(session_id=actor.session_id).first() is None
    assert require_agent_principal(actor.request, x_user_id=None).user_id == "7"
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("FHD_ELT_CENTER_ENABLED", "1")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    clear_idempotent_replay_for_tests()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: store.service)
    monkeypatch.setattr(
        "app.domain.shared_services.tools_workflow_elt._finalize_import",
        lambda *_args: ({}, {}, ""),
    )
    parent, child = _linked_preview(store, monkeypatch)
    submitted = Mock(wraps=store.service.execute)
    monkeypatch.setattr(store.service, "execute", submitted)
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)

    def plan(name, params):
        return PlanGraph(
            plan_id=name,
            intent="elt_import",
            risk_level="high",
            nodes=[
                WorkflowNode(
                    node_id="execute",
                    tool_id="elt_import",
                    action="execute",
                    params=params,
                    risk="high",
                )
            ],
        )

    def approve(run):
        assert run.status == "waiting_user", (run.status, run.error)
        grant = issue_approval_grant(run, principal_id="7")
        validate_approval_grant(grant["grant"], run=run, principal_id="7")
        result = orchestrator.continue_run(
            run.run_id, approved_by="7", runtime_context=actor.context
        )
        assert result.status == "completed", (result.status, result.error, result.steps[0].output)
        return result

    pending = orchestrator.start_run_from_plan(
        user_id="7",
        message="导入出货",
        runtime_context=actor.context,
        plan=plan(
            "shipment-request",
            {"run_id": parent["id"], "valid_rows_only": True, "accept_suggested": True},
        ),
    )
    submitted.assert_not_called()
    done = approve(pending)
    receipt = done.steps[0].output
    assert not receipt.get("requires_user_decision") and "resume_params" not in receipt
    assert f"run_id={child['id']}" in receipt["message"]
    assert f"preview_revision={child['preview_revision']}" in receipt["message"]
    with store.factory() as db:
        assert db.query(ShipmentRecord).count() == db.query(PurchaseUnit).count() == 1
        assert db.query(Product).count() == 0
    assert submitted.call_count == 1

    # Reading an existing child in auto mode must never create or execute a run.
    executor = AgentToolExecutor()
    assert missing_tool_fields("elt_import", "preview", {"run_id": child["id"]}) == []
    review = executor.execute(
        AgentStep(
            node_id="review", tool_id="elt_import", action="preview", params={"run_id": child["id"]}
        ),
        runtime_context={**actor.context, "chat_approval_mode": "auto"},
    )
    assert review["success"] is True, review
    assert review["data"]["preview_revision"] == child["preview_revision"]
    assert submitted.call_count == 1
    for revision in (None, "0" * 64):
        denied = executor.execute(
            AgentStep(
                node_id="bad-review",
                tool_id="elt_import",
                action="execute",
                params={
                    "run_id": child["id"],
                    **({"preview_revision": revision} if revision else {}),
                },
            ),
            runtime_context=actor.context,
        )
        assert denied["error_code"] == "ELT_PREVIEW_CHANGED", denied
        assert submitted.call_count == 1

    child_pending = orchestrator.start_run_from_plan(
        user_id="7",
        message="确认导入附表客户及产品",
        runtime_context=actor.context,
        plan=plan(
            "companion-request",
            {
                "run_id": child["id"],
                "preview_revision": child["preview_revision"],
                "valid_rows_only": True,
                "accept_suggested": True,
            },
        ),
    )
    assert child_pending.run_id != done.run_id
    assert (
        task_execution_context(done, done.steps[0])["idempotency_key"]
        != task_execution_context(child_pending, child_pending.steps[0])["idempotency_key"]
    )
    assert submitted.call_count == 1
    child_done = approve(child_pending)
    assert submitted.call_count == 2
    assert submitted.call_args.kwargs["run_id"] == child["id"]
    assert submitted.call_args.kwargs["preview_revision"] == child["preview_revision"]
    assert child_done.steps[0].output["data"]["executed_rows"] == 1
    with store.factory() as db:
        assert (
            db.query(ShipmentRecord).count()
            == db.query(PurchaseUnit).count()
            == db.query(Product).count()
            == 1
        )

    # Same request replays the retained parent receipt; a new read shows child completion.
    replay = executor.execute(
        done.steps[0],
        runtime_context={**actor.context, **task_execution_context(done, done.steps[0])},
    )
    assert replay["success"] is True and submitted.call_count == 2
    assert replay["data"]["customer_products"]["status"] == "preview_ready"
    assert replay["message"] == receipt["message"]
    refreshed = executor.execute(
        AgentStep(
            node_id="refresh",
            tool_id="elt_import",
            action="preview",
            params={"run_id": parent["id"]},
        ),
        runtime_context=actor.context,
    )
    assert refreshed["data"]["customer_products"]["status"] == "completed"
    assert refreshed["data"]["customer_products"]["requires_user_confirmation"] is False
    assert "客户及产品已写入 1 行" in refreshed["message"]
    assert "需单独确认" not in refreshed["message"]
    assert submitted.call_count == 2

    from app.application.agent_orchestrator.verification_readback import verify_independent_result

    def readback(run, *, overrides=None, output=None):
        step, call = run.steps[0], run.tool_calls[0]
        return verify_independent_result(
            run=run,
            step=step,
            call=call,
            output=call.output if output is None else output,
            context={
                **actor.context,
                **task_execution_context(run, step),
                "run_id": run.run_id,
                "step_id": step.step_id,
                **(overrides or {}),
            },
        )

    # Rechecking either original receipt after the child finishes is read-only,
    # and must not turn the retained parent preview into a second child import.
    mutations = []
    engine = store.factory.kw["bind"]

    def observe(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split()[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
            "ALTER",
        }:
            mutations.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        reports = [readback(done), readback(child_done)]
        assert all(report["status"] == "verified" for report in reports), reports
        assert mutations == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert submitted.call_count == 2

    with store.factory.begin() as db:
        product = db.query(Product).one()
        product_id, price = product.id, product.price
        product.price = 999
    assert readback(child_done)["code"] == "result_business_state_mismatch"
    with store.factory.begin() as db:
        row = db.query(EltRunRow).filter_by(run_id=child["id"], execution_status="success").one()
        child_after = row.after_json
        changed = json.loads(child_after)
        changed["product"]["price"] = "999"
        row.after_json = json.dumps(changed)
    # A wrong writer value plus an equally wrong receipt cannot overrule the
    # original reviewed projection or its unchanged normalized source row.
    assert readback(child_done)["code"] == "result_business_state_mismatch"
    with store.factory.begin() as db:
        db.get(Product, product_id).price = price
        db.query(EltRunRow).filter_by(
            run_id=child["id"], execution_status="success"
        ).one().after_json = child_after

    with store.factory.begin() as db:
        record = db.query(ShipmentRecord).one()
        shipment_id, name = record.id, record.product_name
        record.product_name = "修改后的产品"
    assert readback(done)["code"] == "result_business_state_mismatch"
    assert readback(child_done)["code"] == "result_business_state_mismatch"
    with store.factory.begin() as db:
        row = db.query(EltRunRow).filter_by(run_id=parent["id"], execution_status="success").one()
        shipment_after = row.after_json
        changed = json.loads(shipment_after)
        changed["product_name"] = "修改后的产品"
        row.after_json = json.dumps(changed)
    assert readback(done)["code"] == "result_business_state_mismatch"
    with store.factory.begin() as db:
        db.get(ShipmentRecord, shipment_id).product_name = name
        db.query(EltRunRow).filter_by(
            run_id=parent["id"], execution_status="success"
        ).one().after_json = shipment_after

    with store.factory.begin() as db:
        row = db.get(EltRun, child["id"])
        original = row.summary_json
        changed = json.loads(original)
        changed["execution_confirmation"]["preview_revision"] = "0" * 64
        row.summary_json = json.dumps(changed)
    assert readback(child_done)["code"] == "result_preview_changed"
    with store.factory.begin() as db:
        db.get(EltRun, child["id"]).summary_json = original

    with store.factory() as db:
        source = Path(db.get(EltUpload, parent["upload_id"]).storage_path)
    original_bytes = source.read_bytes()
    original_mode = source.stat().st_mode
    source.chmod(original_mode | 0o200)
    try:
        source.write_bytes(original_bytes + b"changed")
        assert readback(done)["code"] == readback(child_done)["code"] == "result_preview_changed"
    finally:
        source.write_bytes(original_bytes)
        source.chmod(original_mode)
    assert readback(done, overrides={"tenant_id": "2"})["code"] == "result_scope_mismatch"
    altered_receipt = copy.deepcopy(child_done.tool_calls[0].output)
    altered_receipt["committed"] = False
    assert readback(child_done, output=altered_receipt)["code"] == "result_receipt_mismatch"
    without_baseline = copy.deepcopy(child_done)
    without_baseline.tool_calls[0].metadata["verification_contract"].pop("elt_execution_baseline")
    assert readback(without_baseline)["code"] == "result_verifier_unavailable"
    absent_claims = tmp_path / "absent-claims.sqlite"
    with monkeypatch.context() as patcher:
        patcher.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(absent_claims))
        assert readback(child_done)["code"] == "result_receipt_unavailable"
        assert not absent_claims.exists()
    assert readback(done)["status"] == readback(child_done)["status"] == "verified"
    assert submitted.call_count == 2

    from app.db.models.permission import Role

    with actor.factory.begin() as db:
        role = db.query(Role).filter_by(name="importer").one()
        role.permissions.clear()
    assert readback(child_done)["code"] == "result_read_permission_unavailable"
    assert submitted.call_count == 2
    clear_idempotent_replay_for_tests()
