"""Synthetic business inputs through real approval, SQL, XLSX and independent readback.

These integration cases do not constitute customer-original or production acceptance.
Only test-owned storage and outbound notifications are replaced; business writes,
approval authority, the worker lease and file downloads use the production code.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import event

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    issue_approval_grant,
)
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.approval_workspace_app_service import approve_request
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_fingerprint,
    plan_from_dict,
)
from app.db.models import SalesOrder, SalesOrderItem
from app.db.models.approval import ApprovalFlowNode, ApprovalRecord, ApprovalRequest
from app.domain.shared_services.report_service import ReportService
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_sales_agent_acceptance import _seed_closed_loop_sale


@pytest.fixture
def business(trusted_actor, monkeypatch, tmp_path):
    requester, payload, foreign_tenant = _seed_closed_loop_sale(
        trusted_actor, monkeypatch, tmp_path, 0
    )
    reviewer = trusted_actor(role="admin")
    unauthorized = trusted_actor(role="user", permissions=[])
    foreign_reviewer = trusted_actor(role="admin", tenant_id=foreign_tenant)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    engine = requester.factory.kw["bind"]
    from app.domain.shared_services import ai_action_audit_service

    monkeypatch.setattr(ai_action_audit_service, "engine", engine)
    ai_action_audit_service.ensure_ai_action_audit_table()
    repository = SQLAlchemyAgentRunRepository(session_factory=requester.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=requester.factory)
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", repository
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.task_execution_repository._task_execution_repository",
        queue,
    )
    monkeypatch.setattr(
        "app.application.approval_workspace_app_service._agent_executor",
        lambda: AgentOrchestrator(repository=repository, tool_executor=executor),
    )
    monkeypatch.setattr(
        "app.application.approval_workspace_app_service.notify_mobile_user", lambda *_args: None
    )
    # An unscoped export would include 9,900 from this unrelated order. The
    # other tenant also has matching product names and must remain untouched.
    with tenant_scope(requester.tenant_id), requester.factory.begin() as db:
        unrelated = SalesOrder(
            order_no="UNRELATED-ORDER", customer_name="其他订单客户", total_amount=9900
        )
        db.add(unrelated)
        db.flush()
        db.add(
            SalesOrderItem(
                order_id=unrelated.id,
                product_name="产品 B",
                quantity=99,
                unit_price=100,
                amount=9900,
            )
        )
    return SimpleNamespace(
        requester=requester,
        reviewer=reviewer,
        unauthorized=unauthorized,
        foreign_reviewer=foreign_reviewer,
        payload=payload,
        repository=repository,
        queue=queue,
        executor=executor,
        engine=engine,
    )


def _plan(payload, *, workspace):
    return PlanGraph(
        plan_id="full-business-acceptance",
        intent="sales_write",
        metadata={"approval_required_node_ids": ["sale"]} if workspace else {},
        nodes=[
            WorkflowNode(
                "sale",
                "sales",
                "execute_closed_loop",
                {"payload": deepcopy(payload)},
                risk="high",
                idempotent=True,
            ),
            WorkflowNode(
                "verify",
                "sales",
                "verify_closed_loop",
                {"payload": deepcopy(payload)},
                risk="low",
                idempotent=True,
                depends_on=["sale"],
            ),
            WorkflowNode(
                "export",
                "reports",
                "export",
                {
                    "report_type": "sales",
                    "group_by": "product",
                    "order_no": "{{sale.data.order_no}}",
                    "filename": "原销售订单交付",
                },
                risk="low",
                idempotent=True,
                depends_on=["sale", "verify"],
            ),
        ],
    )


def _start(business, *, workspace):
    actor = business.requester
    with tenant_scope(actor.tenant_id):
        run = AgentOrchestrator(
            repository=business.repository, tool_executor=business.executor
        ).start_task_from_plan(
            user_id=str(actor.user_id),
            message="批准后销售10件产品B、出库、记应收并交付该订单Excel，不得虚构收款。",
            plan=_plan(business.payload, workspace=workspace),
            runtime_context=actor.context,
        )
    assert run.status == "waiting_user" and not run.tool_calls
    return run


def _sql(business):
    return closing(sqlite3.connect(f"file:{business.engine.url.database}?mode=ro", uri=True))


def _no_effect(business):
    with _sql(business) as db:
        assert db.execute("SELECT count(*) FROM sales_orders").fetchone() == (1,)
        for table in ("inventory_transactions", "journal_entries", "receivable_allocations"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def _workspace_approval(business, run, *, configured=False):
    actor = business.requester
    plan = plan_from_dict(run.metadata["plan"])
    assert plan is not None
    approvals = ApprovalService()
    with tenant_scope(actor.tenant_id):
        request = approvals.create_approval_request(
            plan_id=plan.plan_id,
            node=plan.nodes[0],
            plan=plan,
            runtime_context={**actor.context, "_approval_agent_run_required": True},
            require_persistence=True,
        )
        assert approvals.attach_pending_agent_run(
            request.request_id, agent_run_id=run.run_id, approved_step_id="sale"
        )
        with actor.factory.begin() as db:
            stored = db.query(ApprovalRequest).filter_by(request_no=request.request_id).one()
            request_id = stored.id
            if configured:
                node = ApprovalFlowNode(
                    flow_id=stored.flow_id,
                    node_name="Independent business reviewer",
                    node_order=100,
                    approver_type="user",
                    approver_ids=json.dumps([business.reviewer.user_id]),
                )
                db.add(node)
                db.flush()
                stored.current_node_id = node.id
                stored.current_node_order = node.node_order
    return request_id, request.request_id


def _reconcile_sql_and_download(business, run):
    from app.application.agent_orchestrator.result_verification import verify_step_result
    from app.application.agent_orchestrator.task_background import task_execution_context

    actor = business.requester
    assert run.status == "completed", run.to_dict()
    assert [step.node_id for step in run.steps] == ["sale", "verify", "export"]
    assert [step.status for step in run.steps] == ["completed"] * 3
    assert len(run.tool_calls) == 3
    assert all(
        call.metadata["verification"]["status"] in {"verified", "not_required"}
        for call in run.tool_calls
    )
    sale = run.steps[0].output["data"]
    assert run.steps[2].params["order_no"] == sale["order_no"]
    with _sql(business) as db:
        order = db.execute(
            "SELECT tenant_id,total_amount,paid_amount,payment_state,invoice_status "
            "FROM sales_orders WHERE id=? AND order_no=?",
            (sale["order_id"], sale["order_no"]),
        ).fetchone()
        assert order == (actor.tenant_id, 1000, 0, "unpaid", "invoiced")
        rows = db.execute(
            "SELECT product_name,quantity,amount,delivered_quantity FROM sales_order_items "
            "WHERE order_id=? AND tenant_id=?",
            (sale["order_id"], actor.tenant_id),
        ).fetchall()
        assert rows == [("产品 B", 10, 1000, 10)]
        assert db.execute(
            "SELECT quantity FROM inventory_transactions WHERE sales_order_id=?",
            (sale["order_id"],),
        ).fetchall() == [(-10,)]
        assert db.execute(
            "SELECT available_quantity FROM inventory_ledger WHERE tenant_id=?",
            (actor.tenant_id,),
        ).fetchall() == [(10,)]
        assert db.execute(
            "SELECT available_quantity FROM inventory_ledger WHERE tenant_id=?",
            (business.foreign_reviewer.tenant_id,),
        ).fetchmany(2) == [(20,)]
        journal_id = sale["invoice_entry_id"]
        assert db.execute(
            "SELECT debit_total,credit_total,status FROM journal_entries WHERE id=?",
            (journal_id,),
        ).fetchone() == (1000, 1000, "posted")
        debit, credit = db.execute(
            "SELECT sum(debit),sum(credit) FROM journal_entry_lines WHERE entry_id=?",
            (journal_id,),
        ).fetchone()
        assert Decimal(str(debit)) == Decimal(str(credit)) == Decimal("1000")
        assert db.execute("SELECT count(*) FROM receivable_allocations").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM sales_orders").fetchone() == (2,)

    from app.fastapi_routes.domains.agent.artifact_routes import router

    app = FastAPI()
    app.include_router(router)
    artifact = run.steps[2].output["artifacts"][0]
    with TestClient(app) as client:
        response = client.get(artifact["uri"], headers=actor.headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert hashlib.sha256(response.content).hexdigest() == artifact["metadata"]["sha256"]
        book = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
        try:
            assert book.sheetnames == ["sales"]
            assert list(book["sales"].values) == [
                ("product_name", "quantity", "amount"),
                ("产品 B", 10, 1000),
            ]
        finally:
            book.close()
        assert (
            client.get(artifact["uri"], headers=business.foreign_reviewer.headers).status_code
            == 403
        )
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(business.engine, "before_cursor_execute", observe)
    try:
        for step, call in zip(run.steps, run.tool_calls, strict=True):
            result = verify_step_result(
                run=run,
                step=step,
                call=call,
                context={
                    **run.metadata["runtime_context"],
                    **task_execution_context(run, step),
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                },
            )
            assert result["accepted"] is True, result
        assert writes == []
    finally:
        event.remove(business.engine, "before_cursor_execute", observe)
    return artifact


def _assert_workspace_approval_delivery(business, monkeypatch, *, configured):
    actor = business.requester
    run = _start(business, workspace=True)
    plan = plan_from_dict(run.metadata["plan"])
    assert plan is not None
    frozen = deepcopy(run.metadata["plan"])
    request_id, _ = _workspace_approval(business, run, configured=configured)
    # Fresh service and repository force reads of the original durable snapshots.
    monkeypatch.setattr(
        "app.application.workflow.approval_service._approval_service", ApprovalService()
    )
    fresh = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", fresh
    )
    with tenant_scope(actor.tenant_id):
        for denied_actor in (business.unauthorized, business.foreign_reviewer):
            denied = approve_request(request_id, denied_actor.request, body={}, x_user_id=None)
            assert denied.status_code == 403
            _no_effect(business)
        response = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
    assert isinstance(response, dict) and response["success"] is True, response
    assert response["data"]["workflow_execution"]["success"] is True, response
    completed = fresh.get(run.run_id)
    resolved = deepcopy(frozen)
    resolved["nodes"][2]["params"]["order_no"] = completed.steps[0].output["data"]["order_no"]
    assert completed.metadata["plan"] == resolved
    assert completed.metadata["approval_receipt"]["approved_by"] == str(business.reviewer.user_id)
    assert completed.metadata["runtime_context"]["_actor_authorization"]["user_id"] == str(
        actor.user_id
    )
    _reconcile_sql_and_download(business, completed)
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        stored = db.get(ApprovalRequest, request_id)
        assert stored.applicant_id == actor.user_id
        assert stored.approved_by == business.reviewer.user_id != actor.user_id
        snapshot = json.loads(stored.business_data)["durable_workflow_snapshot"]
        assert snapshot["plan"] == frozen
        assert snapshot["plan_sha256"] == plan_fingerprint(plan)
        assert completed.metadata["approval_receipt"]["plan_sha256"] == snapshot["plan_sha256"]
        assert db.query(ApprovalRecord).filter_by(request_id=request_id).count() == 1
        assert json.loads(stored.business_data)["agent_execution_claim"] == {
            "agent_run_id": run.run_id,
            "approved_step_id": "sale",
            "approved_by": str(business.reviewer.user_id),
        }
        from app.application.approval_workspace_app_service import _request_to_dict

        current = _request_to_dict(stored)["workflow_execution"]
        assert current["success"] is True, current
    original_calls = [call.to_dict() for call in fresh.get(run.run_id).tool_calls]
    with tenant_scope(actor.tenant_id):
        duplicate = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
    assert duplicate.status_code == 400
    assert [call.to_dict() for call in fresh.get(run.run_id).tool_calls] == original_calls
    _reconcile_sql_and_download(business, fresh.get(run.run_id))
    return request_id, completed


def test_separate_reviewer_resumes_original_approval_then_delivers_reconciled_order(
    business, monkeypatch
):
    from app.application.approval_workspace_app_service import _request_to_dict
    from app.db.models.agent import AgentRunRecord

    request_id, completed = _assert_workspace_approval_delivery(
        business, monkeypatch, configured=False
    )
    actor = business.requester
    with actor.factory() as db:
        original = db.get(AgentRunRecord, completed.run_id).payload_json
    # Preserve the run identity while corrupting both its graph and step. Only
    # references resolved from the original approved plan may change parameters.
    changes = (
        ("params", {**completed.steps[2].params, "order_no": "UNRELATED-ORDER"}),
        ("depends_on", ["sale"]),
    )
    try:
        for field, value in changes:
            tampered = json.loads(original)
            tampered["metadata"]["plan"]["nodes"][2][field] = value
            tampered["steps"][2][field] = value
            with actor.factory.begin() as db:
                db.get(AgentRunRecord, completed.run_id).payload_json = json.dumps(tampered)
            with tenant_scope(actor.tenant_id), actor.factory() as db:
                receipt = _request_to_dict(db.get(ApprovalRequest, request_id))[
                    "workflow_execution"
                ]
                assert receipt["success"] is False, receipt
                assert receipt["code"] == "outcome_unknown", receipt
                assert receipt["requires_reconciliation"] is True
                assert receipt["retryable"] is False
    finally:
        with actor.factory.begin() as db:
            db.get(AgentRunRecord, completed.run_id).payload_json = original
    _reconcile_sql_and_download(business, business.repository.get(completed.run_id))


def test_configured_reviewer_delivers_original_order_without_database_lock(business, monkeypatch):
    _assert_workspace_approval_delivery(business, monkeypatch, configured=True)


@pytest.mark.parametrize("configured", [False, True])
def test_workflow_rejection_cancels_original_run_before_any_business_write(business, configured):
    from app.application.approval_workspace_app_service import reject_request

    actor = business.requester
    run = _start(business, workspace=True)
    original_plan = deepcopy(run.metadata["plan"])
    request_id, _ = _workspace_approval(business, run, configured=configured)
    with tenant_scope(actor.tenant_id):
        rejected = reject_request(
            request_id,
            business.reviewer.request,
            body={"reason": "Do not execute the original business order"},
            x_user_id=None,
        )
        assert isinstance(rejected, dict) and rejected["success"] is True, rejected
        stored_run = SQLAlchemyAgentRunRepository(session_factory=actor.factory).get(run.run_id)
        assert stored_run.status == "cancelled", stored_run.to_dict()
        assert stored_run.metadata["plan"] == original_plan
        assert not stored_run.tool_calls
        assert rejected["data"]["workflow_execution"]["agent_run_id"] == run.run_id
        repeated = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
        assert repeated.status_code == 400
        with actor.factory() as db:
            assert db.get(ApprovalRequest, request_id).status == "rejected"
            assert (
                db.query(ApprovalRecord).filter_by(request_id=request_id, action="reject").count()
                == 1
            )
    _no_effect(business)


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize(
    "target,node_type,min_approvals",
    [("node", "serial", 2), ("node", "countersign", 1), ("flow", "parallel", 1)],
)
def test_unsupported_approval_policy_keeps_original_run_waiting_without_writes(
    business, configured, target, node_type, min_approvals
):
    actor = business.requester
    run = _start(business, workspace=True)
    request_id, _ = _workspace_approval(business, run, configured=configured)
    with tenant_scope(actor.tenant_id):
        with actor.factory.begin() as db:
            stored = db.get(ApprovalRequest, request_id)
            if target == "flow":
                stored.flow.node_type = node_type
            else:
                node = stored.current_node or stored.flow.nodes[0]
                node.node_type = node_type
                node.min_approvals = min_approvals
        response = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
        _no_effect(business)
        assert response.status_code == 409
        assert json.loads(response.body)["code"] == "unsupported_approval_policy"
        assert business.repository.get(run.run_id).to_dict() == run.to_dict()
        with actor.factory() as db:
            stored = db.get(ApprovalRequest, request_id)
            assert stored.status == "pending"
            assert "agent_execution_claim" not in json.loads(stored.business_data)
            assert db.query(ApprovalRecord).filter_by(request_id=request_id).count() == 0


@pytest.mark.parametrize("target", ["flow", "node", "count"])
def test_unsupported_approval_configuration_is_rejected_before_saving(
    business, trusted_actor, target
):
    from app.application.approval_workspace_app_service import create_flow, update_flow
    from app.db.models.approval import ApprovalFlow

    administrator = trusted_actor(role="admin", tier="admin")
    body = {
        "flow": {"flow_key": "review-policy", "flow_name": "Review policy"},
        "nodes": [{"approver_ids": [business.reviewer.user_id]}],
    }
    unsupported = deepcopy(body)
    if target == "flow":
        unsupported["flow"]["node_type"] = "countersign"
    elif target == "node":
        unsupported["nodes"][0]["node_type"] = "parallel"
    else:
        unsupported["nodes"][0]["min_approvals"] = 2
    with tenant_scope(business.requester.tenant_id):
        rejected = create_flow(administrator.request, body=unsupported, x_user_id=None)
        assert rejected.status_code == 409
        with business.requester.factory() as db:
            assert db.query(ApprovalFlow).filter_by(flow_key="review-policy").count() == 0
        created = create_flow(administrator.request, body=body, x_user_id=None)
        assert created["success"] is True
        flow_id = created["data"]["id"]
        rejected = update_flow(
            flow_id,
            administrator.request,
            body={"node_type": "countersign"},
            x_user_id=None,
        )
        assert rejected.status_code == 409
        with business.requester.factory() as db:
            assert db.get(ApprovalFlow, flow_id).node_type == "serial"


@pytest.mark.parametrize("decision", ["reject", "withdraw"])
def test_execution_claim_blocks_opposite_decision_before_business_write(
    business, monkeypatch, trusted_actor, decision
):
    from app.application.approval_workspace_app_service import reject_request, withdraw_request

    actor = business.requester
    rejector = trusted_actor(role="admin") if decision == "reject" else actor
    decide = reject_request if decision == "reject" else withdraw_request
    run = _start(business, workspace=True)
    request_id, _ = _workspace_approval(business, run, configured=decision == "withdraw")
    original_execute = business.executor.execute
    rejected = []

    def reject_during_execution(*args, **kwargs):
        if not rejected:
            with actor.factory() as db:
                stored = db.get(ApprovalRequest, request_id)
                assert json.loads(stored.business_data)["agent_execution_claim"]
            _no_effect(business)
            rejected.append(
                decide(
                    request_id,
                    rejector.request,
                    body={
                        "reason": "A later opposite decision must not change a consumed approval"
                    },
                    x_user_id=None,
                )
            )
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(business.executor, "execute", reject_during_execution)
    with tenant_scope(actor.tenant_id):
        response = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
    assert len(rejected) == 1
    assert getattr(rejected[0], "status_code", 200) == 409, rejected[0]
    assert isinstance(response, dict) and response["success"] is True, response
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        stored = db.get(ApprovalRequest, request_id)
        assert stored.status == "approved"
        assert stored.approved_by == business.reviewer.user_id
        assert (
            db.query(ApprovalRecord).filter_by(request_id=request_id, action=decision).count() == 0
        )
    _reconcile_sql_and_download(business, business.repository.get(run.run_id))


@pytest.mark.parametrize("claim_after_read", [False, True])
@pytest.mark.parametrize("decision", ["reject", "withdraw"])
def test_rejection_and_execution_claim_are_mutually_exclusive(
    business, monkeypatch, trusted_actor, claim_after_read, decision
):
    from app.application import approval_workspace_app_service as workspace
    from app.application.approval_workspace.repository import ApprovalRepository
    from app.application.workflow.approval_persistence import claim_agent_approval

    actor = business.requester
    rejector = trusted_actor(role="admin") if decision == "reject" else actor
    decide = workspace.reject_request if decision == "reject" else workspace.withdraw_request
    run = _start(business, workspace=True)
    request_id, request_no = _workspace_approval(business, run, configured=decision == "withdraw")
    read_request = ApprovalRepository.request
    claimed = []

    def interrupted(*_args, **_kwargs):
        raise SystemExit("claim committed while the opposite reviewer holds an older request")

    def read_then_claim(db, object_id):
        req = read_request(db, object_id)
        if object_id == request_id and claim_after_read and not claimed:
            assert req.status == "pending"
            assert "agent_execution_claim" not in json.loads(req.business_data)
            claimed.append(True)
            with monkeypatch.context() as patch:
                patch.setattr(AgentOrchestrator, "continue_run", interrupted)
                with pytest.raises(SystemExit):
                    approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
        return req

    monkeypatch.setattr(ApprovalRepository, "request", staticmethod(read_then_claim))
    with tenant_scope(actor.tenant_id):
        rejected = decide(
            request_id, rejector.request, body={"reason": "Opposite decision"}, x_user_id=None
        )
        assert not claim_agent_approval(
            request_no,
            agent_run_id=run.run_id,
            approved_step_id="sale",
            approved_by=str(business.reviewer.user_id),
        )
        retry = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
    if claim_after_read:
        assert claimed == [True]
        assert getattr(rejected, "status_code", 200) == 409, rejected
        assert retry.status_code == 409
        assert business.repository.get(run.run_id).to_dict() == run.to_dict()
    else:
        assert isinstance(rejected, dict) and rejected["success"] is True
        assert retry.status_code == 400
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        stored = db.get(ApprovalRequest, request_id)
        expected_status = "rejected" if decision == "reject" else "withdrawn"
        assert stored.status == ("pending" if claim_after_read else expected_status)
        assert ("agent_execution_claim" in json.loads(stored.business_data)) is claim_after_read
        assert stored.approved_by == (
            business.reviewer.user_id
            if claim_after_read
            else rejector.user_id
            if decision == "reject"
            else None
        )
        assert db.query(ApprovalRecord).filter_by(request_id=request_id).count() == (
            0 if claim_after_read else 1
        )
    _no_effect(business)


@pytest.mark.parametrize("after_claim", [False, True])
def test_workspace_approval_interruption_preserves_original_plan_and_decision(
    business, monkeypatch, after_claim
):
    from app.db.models.user import User

    actor = business.requester
    run = _start(business, workspace=True)
    original = deepcopy(run.to_dict())
    request_id, _ = _workspace_approval(business, run)

    def interrupted(*_args, **_kwargs):
        raise SystemExit("approval process interrupted before business execution")

    with tenant_scope(actor.tenant_id), monkeypatch.context() as patch:
        if after_claim:
            patch.setattr(AgentOrchestrator, "continue_run", interrupted)
        else:
            patch.setattr(
                "app.application.approval_workspace_app_service._resume_pending_ai_workflow_after_approval",
                interrupted,
            )
        with pytest.raises(SystemExit):
            approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
    _no_effect(business)
    assert business.repository.get(run.run_id).to_dict() == original
    assert business.queue.get(run.run_id) is None
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        stored = db.get(ApprovalRequest, request_id)
        assert stored.status == "pending"
        assert stored.approved_by == (business.reviewer.user_id if after_claim else None)
        assert bool(stored.approved_at) is after_claim
        assert db.query(ApprovalRecord).filter_by(request_id=request_id).count() == 0
        data = json.loads(stored.business_data)
        assert data["durable_workflow_snapshot"]["plan"] == original["metadata"]["plan"]
        assert ("agent_execution_claim" in data) is after_claim
        if after_claim:
            assert data["agent_execution_claim"]["approved_by"] == str(business.reviewer.user_id)
    monkeypatch.setattr(
        "app.application.workflow.approval_service._approval_service", ApprovalService()
    )
    with tenant_scope(actor.tenant_id):
        for denied in (business.unauthorized, business.foreign_reviewer):
            response = approve_request(request_id, denied.request, body={}, x_user_id=None)
            assert response.status_code == 403
            _no_effect(business)
        with actor.factory.begin() as db:
            db.get(User, business.reviewer.user_id).role = "user"
        response = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
        assert response.status_code == 403
        _no_effect(business)
        with actor.factory.begin() as db:
            db.get(User, business.reviewer.user_id).role = "admin"
        retry = approve_request(request_id, business.reviewer.request, body={}, x_user_id=None)
    if after_claim:
        assert retry.status_code == 409
        assert business.repository.get(run.run_id).to_dict() == original
        _no_effect(business)
    else:
        assert isinstance(retry, dict) and retry["success"] is True
        completed = business.repository.get(run.run_id)
        assert completed.metadata["approval_receipt"]["approved_by"] == str(
            business.reviewer.user_id
        )
        _reconcile_sql_and_download(business, completed)


@pytest.mark.parametrize("corrupt", [False, True])
def test_approved_worker_delivers_once_and_rejects_wrong_money_in_valid_workbook(
    business, monkeypatch, corrupt
):
    actor = business.requester
    run = _start(business, workspace=False)
    business.queue.enqueue_waiting_approval(run, approver=str(actor.user_id))
    grant = issue_approval_grant(run, principal_id=str(actor.user_id))
    assert grant is not None
    with pytest.raises(ApprovalGrantError, match="无权审批"):
        approve_and_enqueue(
            business.repository,
            business.queue,
            run_id=run.run_id,
            token=grant["grant"],
            principal_id=str(business.unauthorized.user_id),
            runtime_context={},
        )
    _no_effect(business)
    if corrupt:
        original = ReportService.export_to_excel

        def wrong_amount(service, report_type, data, filename):
            result = original(service, report_type, data, filename)
            book = load_workbook(BytesIO(result["data"]))
            try:
                book["sales"]["C2"] = 1
                altered = BytesIO()
                book.save(altered)
                result["data"] = altered.getvalue()
            finally:
                book.close()
            return result

        monkeypatch.setattr(ReportService, "export_to_excel", wrong_amount)
    queued = approve_and_enqueue(
        business.repository,
        business.queue,
        run_id=run.run_id,
        token=grant["grant"],
        principal_id=str(actor.user_id),
        runtime_context={},
        authenticated_binding=actor.principal.mod_authorization,
    )
    assert queued.status == "queued"
    _no_effect(business)
    # Recreate the SQL repositories/worker after durable approval, before execution.
    fresh = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=fresh,
        lease_seconds=30,
        orchestrator_factory=lambda repo: AgentOrchestrator(
            repository=repo, tool_executor=business.executor
        ),
    )
    # Use the real coordinator so long business execution keeps its original
    # lease through production heartbeats instead of a direct worker shortcut.
    deadline = time.monotonic() + 120
    dispatcher.start()
    try:
        while queue.get(run.run_id).state in {"queued", "running"}:
            assert time.monotonic() < deadline, dispatcher.snapshot()
            time.sleep(0.05)
    finally:
        dispatcher.stop()
    assert queue.get(run.run_id).execution_count == 1
    assert queue.get(run.run_id).recovery_count == 0
    completed = fresh.get(run.run_id)
    if corrupt:
        assert completed.status != "completed", completed.to_dict()
        assert queue.get(run.run_id).state != "succeeded"
        export = next(call for call in completed.tool_calls if call.node_id == "export")
        assert export.metadata["verification"]["accepted"] is False
        # The sale committed once; a bad deliverable must not replay it.
        with _sql(business) as db:
            assert db.execute("SELECT count(*) FROM inventory_transactions").fetchone() == (1,)
            assert db.execute("SELECT count(*) FROM journal_entries").fetchone() == (1,)
    else:
        _reconcile_sql_and_download(business, completed)
        assert queue.get(run.run_id).state == "succeeded"
    assert queue.claim("restarted-worker", run_id=run.run_id, lease_seconds=30) is None
    with pytest.raises(ApprovalGrantError):
        approve_and_enqueue(
            fresh,
            queue,
            run_id=run.run_id,
            token=grant["grant"],
            principal_id=str(actor.user_id),
            runtime_context={},
            authenticated_binding=actor.principal.mod_authorization,
        )
