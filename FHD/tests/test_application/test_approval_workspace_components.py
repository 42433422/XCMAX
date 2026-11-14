"""Behavior at the approval workspace's authorization and execution boundaries."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from fastapi.responses import JSONResponse

from app.application import approval_workspace_app_service as service
from app.db.models.approval import ApprovalFlowNode, ApprovalRequest, ApprovalStatus


@pytest.mark.parametrize("with_node", [False, True])
def test_final_ai_approval_requires_confirmed_execution(monkeypatch, with_node):
    """A missing or contradictory executor receipt must never approve or notify."""
    node = ApprovalFlowNode(
        id=10,
        flow_id=1,
        node_name="Approval",
        node_order=1,
        approver_ids="[7]",
        is_active=True,
    )
    req = ApprovalRequest(
        id=1,
        request_no="pending-1",
        tenant_id=1,
        flow_id=1,
        business_type="workflow_tool",
        business_data="{}",
        applicant_id=7,
        title="Write after approval",
        status=ApprovalStatus.PENDING.value,
        current_node_order=1,
    )
    req.current_node = node if with_node else None
    db = MagicMock()
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = req
    db.query.return_value = query

    @contextmanager
    def session():
        yield db

    notify = MagicMock()
    monkeypatch.setattr(service, "get_db", session)
    monkeypatch.setattr(service, "_resolve_actor", lambda *args, **kwargs: 7)
    monkeypatch.setattr(service, "_can_review_ai_workflow_request", lambda *args: True)
    monkeypatch.setattr(service, "_ordered_nodes", lambda *args: [node])
    monkeypatch.setattr(service, "_ai_workflow_audit_node", lambda *args: node)
    monkeypatch.setattr(service, "_has_pending_ai_workflow", lambda *args: True)
    monkeypatch.setattr(service, "_audit", MagicMock())
    monkeypatch.setattr(service, "notify_mobile_user", notify)
    monkeypatch.setattr(
        service,
        "_resume_pending_ai_workflow_after_approval",
        lambda **kwargs: None if with_node else {"success": True, "workflow_executed": False},
    )

    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(1):
        result = service.approve_request(1, MagicMock(), body={})
    filters = [clause for invocation in query.filter.call_args_list for clause in invocation.args]
    assert any(clause.compare(ApprovalRequest.id == req.id) for clause in filters)
    assert any(clause.compare(ApprovalRequest.tenant_id == req.tenant_id) for clause in filters)
    payload = json.loads(result.body) if isinstance(result, JSONResponse) else result

    assert payload["success"] is False
    assert req.status == ApprovalStatus.CANCELLED.value
    outcome = json.loads(req.business_data)["workflow_execution"]
    assert outcome["success"] is False
    assert outcome["workflow_executed"] is False
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    notify.assert_not_called()
    if not with_node:
        db.add.assert_not_called()


def test_roster_fallback_uses_the_public_product_query(monkeypatch):
    from app import application
    from app.application.product_app_service import ProductApplicationService

    products = MagicMock(spec=ProductApplicationService)
    products.get_products.return_value = {
        "success": True,
        "data": [{"id": 19, "product_name": "Roster member"}],
    }
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(service, "get_db", session)
    monkeypatch.setattr(application, "get_product_app_service", lambda: products)

    result = service.get_approval_users()

    assert result == {
        "success": True,
        "count": 1,
        "data": [{"id": 19, "name": "Roster member", "source": "roster"}],
    }
    products.get_products.assert_called_once_with(page=1, per_page=50)


def test_reused_query_component_resolves_current_mod_database_and_tenant(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.db_base import Base
    from app.db.models.approval import ApprovalFlow, ApprovalRecord
    from app.db.models.user import User
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import (
        get_request_active_mod_id,
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    engines = {name: create_engine("sqlite://") for name in ("mod-a", "mod-b")}
    try:
        for mod_id, engine in engines.items():
            Base.metadata.create_all(
                engine,
                tables=[
                    model.__table__
                    for model in (
                        User,
                        ApprovalFlow,
                        ApprovalFlowNode,
                        ApprovalRequest,
                        ApprovalRecord,
                    )
                ],
            )
            with Session(engine) as db:
                db.add(User(id=7, username="applicant", password="test"))
                db.add(ApprovalFlow(id=1, flow_key="review", flow_name="Review"))
                db.add_all(
                    [
                        ApprovalRequest(
                            id=tenant,
                            request_no=f"{mod_id}-{tenant}",
                            tenant_id=tenant,
                            flow_id=1,
                            applicant_id=7,
                            business_type="general",
                            title=f"{mod_id} tenant {tenant}",
                            status="pending",
                        )
                        for tenant in (1, 2)
                    ]
                )
                db.commit()

        # Construct before replacing get_db: the repository must defer session creation.
        queries = service._queries()

        @contextmanager
        def scoped_session():
            with Session(engines[get_request_active_mod_id()]) as db:
                yield db

        monkeypatch.setattr(service, "get_db", scoped_session)
        monkeypatch.delenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", raising=False)
        for mod_id in engines:
            token = set_request_active_mod_id(mod_id)
            try:
                for tenant in (1, 2):
                    with tenant_scope(tenant):
                        result = queries.list_requests(None, None, None, None, 1, 50)
                        assert [item["title"] for item in result["data"]] == [
                            f"{mod_id} tenant {tenant}"
                        ]
                        assert result["pagination"]["total"] == 1
                        assert queries.get_request_detail(3 - tenant).status_code == 404
                with tenant_scope(None):
                    result = queries.list_requests(None, None, None, None, 1, 50)
                    assert result["data"] == []
                    assert result["pagination"]["total"] == 0
            finally:
                reset_request_active_mod_id(token)
    finally:
        for engine in engines.values():
            engine.dispose()


def test_bridge_preserves_bound_context_and_resolves_backend_per_call(monkeypatch):
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    contexts = [
        {
            "tenant_id": str(index),
            "mod_id": f"mod-{index}",
            "_mod_authorization": {
                "session_row_id": index,
                "user_id": "7",
                "mod_id": f"mod-{index}",
            },
            "_approval_agent_run_required": True,
        }
        for index in (1, 2)
    ]
    approvals = [MagicMock(), MagicMock()]
    snapshots = {}
    runs = {}
    for index, (backend, context) in enumerate(zip(approvals, contexts, strict=True), 1):
        run_id = f"run-{index}"
        plan = PlanGraph(
            plan_id=f"plan-{index}",
            intent="delete_customer",
            metadata={"approval_required_node_ids": ["delete_customer"]},
            nodes=[
                WorkflowNode(
                    node_id="delete_customer",
                    tool_id="customers",
                    action="delete",
                    params={"id": index},
                    risk="high",
                    idempotent=False,
                )
            ],
        )
        step = AgentStep(
            node_id="delete_customer",
            tool_id="customers",
            action="delete",
            params={"id": index},
            risk="high",
            idempotent=False,
            step_id=f"step-{index}",
            status="waiting_user",
        )
        run = AgentRun(
            user_id="7",
            message="delete customer",
            run_id=run_id,
            status="waiting_user",
            plan_id=plan.plan_id,
            steps=[step],
            metadata={"plan": plan_to_dict(plan)},
        )
        runs[run_id] = run
        workflow = {
            "runtime_context": context,
            "agent_run_id": run_id,
            "approved_step_id": step.step_id,
            "plan": plan,
        }
        backend.get_pending_workflow.return_value = workflow
        snapshots[f"request-{index}"] = {
            **workflow,
            "plan": plan,
            "tenant_id": context["tenant_id"],
        }
    current = [approvals[0]]
    agent = MagicMock()
    agent.continue_run.side_effect = lambda run_id, **kwargs: SimpleNamespace(
        run_id=run_id,
        status="completed",
        plan_id=runs[run_id].plan_id,
        intent="delete_customer",
        steps=[SimpleNamespace(status="completed")],
        tool_calls=[],
    )
    monkeypatch.setattr(
        "app.application.workflow.approval_persistence.claim_agent_approval", lambda **kwargs: True
    )
    bridge = WorkflowApprovalBridge(
        WorkflowBackends(
            approvals=lambda: current[0],
            pending_snapshot=lambda _request_id: None,
            execution_snapshot=lambda request_id: snapshots.get(request_id),
            agent=lambda: agent,
            load_run=lambda run_id: runs.get(run_id),
        ),
        (RuntimeError,),
        logging.getLogger(__name__),
    )

    for index, backend in enumerate(approvals, 1):
        current[0] = backend
        result = bridge.resume(request_no=f"request-{index}", opinion="approved", approved_by="7")
        assert result["success"] is True, result
        backend.approve.assert_called_once_with(f"request-{index}", "approved")
        backend.remove_pending_workflow.assert_called_once_with(f"request-{index}")
    executor_calls = agent.continue_run.call_args_list
    assert [item.kwargs["runtime_context"] for item in executor_calls] == contexts
    assert all(
        item.kwargs["runtime_context"] is context
        for item, context in zip(executor_calls, contexts, strict=True)
    )
    assert agent.continue_run.call_args_list == [
        call(
            f"run-{index}",
            approved_by="7",
            approved_step_id=f"step-{index}",
            approval_request_id=f"request-{index}",
            runtime_context=context,
        )
        for index, context in enumerate(contexts, 1)
    ]


def test_missing_agent_link_never_runs_legacy_plan():
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import (
        WorkflowApprovalBridge,
    )

    approvals = MagicMock()
    approvals.get_pending_workflow.return_value = {
        "plan": SimpleNamespace(plan_id="plan", intent="test", nodes=[]),
        "runtime_context": {"_approval_agent_run_required": True},
    }
    bridge = WorkflowApprovalBridge(
        WorkflowBackends(
            approvals=lambda: approvals,
            pending_snapshot=lambda _request_id: None,
            execution_snapshot=lambda _request_id: None,
            agent=MagicMock(),
            load_run=MagicMock(),
        ),
        (RuntimeError,),
        logging.getLogger(__name__),
    )
    result = bridge.resume(request_no="req", opinion="同意", approved_by="7")
    assert result["success"] is False
    assert result["code"] == "agent_run_unavailable"


def test_invalid_approved_plan_does_not_resume_agent():
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="p",
        intent="test",
        nodes=[
            WorkflowNode(node_id="n", tool_id="products", action="query", depends_on=["missing"])
        ],
    )
    approvals = MagicMock()
    approvals.get_pending_workflow.return_value = {
        "agent_run_id": "run",
        "approved_step_id": "n",
        "plan": plan,
        "runtime_context": {"_approval_agent_run_required": True},
    }
    agent = MagicMock()
    waiting = SimpleNamespace(status="waiting_user", node_id="n", step_id="n")
    bridge = WorkflowApprovalBridge(
        WorkflowBackends(
            approvals=lambda: approvals,
            pending_snapshot=lambda _request_id: None,
            execution_snapshot=lambda _request_id: None,
            agent=lambda: agent,
            load_run=lambda _: SimpleNamespace(status="waiting_user", steps=[waiting]),
        ),
        (RuntimeError,),
        logging.getLogger(__name__),
    )
    result = bridge.resume(request_no="req", opinion="同意", approved_by="7")
    assert result["success"] is False
    agent.continue_run.assert_not_called()


def test_removed_approved_tool_does_not_resume_agent():
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="p",
        intent="test",
        nodes=[WorkflowNode(node_id="n", tool_id="removed_tool", action="execute")],
    )
    approvals = MagicMock()
    approvals.get_pending_workflow.return_value = {
        "agent_run_id": "run",
        "approved_step_id": "n",
        "plan": plan,
        "runtime_context": {"_approval_agent_run_required": True},
    }
    agent = MagicMock()
    waiting = SimpleNamespace(
        status="waiting_user",
        node_id="n",
        step_id="n",
        tool_id="removed_tool",
        action="execute",
        params={},
    )
    bridge = WorkflowApprovalBridge(
        WorkflowBackends(
            approvals=lambda: approvals,
            pending_snapshot=lambda _request_id: None,
            execution_snapshot=lambda _request_id: None,
            agent=lambda: agent,
            load_run=lambda _: SimpleNamespace(status="waiting_user", steps=[waiting]),
        ),
        (RuntimeError,),
        logging.getLogger(__name__),
    )
    result = bridge.resume(request_no="req", opinion="同意", approved_by="7")
    assert result["success"] is False
    agent.continue_run.assert_not_called()


def test_langgraph_runtime_dispatches_registered_tool(monkeypatch):
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime

    calls = []

    def dispatch(tool_id, action, params):
        calls.append((tool_id, action))
        return {"success": True}

    plan = PlanGraph(
        plan_id="p",
        intent="test",
        nodes=[WorkflowNode(node_id="n", tool_id="products", action="query")],
    )
    result = XCAGILangGraphRuntime(tool_dispatcher=dispatch).run(plan)
    assert result.success
    assert calls == [("products", "query")]
