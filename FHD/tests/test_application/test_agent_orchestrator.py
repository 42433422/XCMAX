from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_agent_usage_ledger(tmp_path, monkeypatch):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    # These formal graph/event tests mock dispatch in this interpreter; the real spawned
    # executor and tenant persistence are exercised by test_tool_process/tenant.
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.AgentToolExecutor",
        lambda: SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    # These orchestration tests use synthetic, unauthenticated actors and a
    # mocked dispatcher. Real authorization and tenant isolation are tested in
    # test_product_exists_readonly_contract and test_owned_business_tool_isolation.
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor._reviewed_query_tenant",
        lambda *_args: (None, None),
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def _business_plan(*, write=False):
    """Explicit business graph fixtures; natural-language execution belongs to Xiaox."""
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    node = (
        WorkflowNode(
            "write_customer",
            "business_db",
            "write",
            {"entity": "customers", "operation": "upsert", "payload": {"unit_name": "星光贸易"}},
            risk="medium",
            idempotent=False,
        )
        if write
        else WorkflowNode(
            "read_products",
            "business_db",
            "read",
            {"entity": "products", "keyword": "XG-5003"},
            risk="low",
            idempotent=True,
        )
    )
    return PlanGraph(
        plan_id="fixture-write" if write else "fixture-read",
        intent="business_db_write" if write else "business_db_read",
        todo_steps=[node.action],
        risk_level=node.risk,
        nodes=[node],
    )


def test_agent_orchestrator_persists_stable_error_codes_not_exception_details():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph

    secret = "Traceback: database password=do-not-expose"
    provided = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    with patch.object(provided, "_apply_plan", side_effect=RuntimeError(secret)):
        provided_run = provided.start_run_from_plan(
            user_id="u1",
            message="执行任务",
            plan=PlanGraph(plan_id="p1", intent="test"),
        )

    for run in (provided_run,):
        assert run.status == "failed"
        assert run.error == "agent_run_internal_error"
        assert secret not in str(run.to_dict())
    assert run.events[-1].data["error_code"] == "agent_run_internal_error"
    assert run.events[-1].data["harness"]["protocol"] == "xcagi.business-harness.v1"


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_agent_graph_exception_details_stay_in_server_logs(caplog, error_type):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    secret = "Traceback: database password=do-not-expose"
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="graph_failure",
        intent="read_products",
        nodes=[
            WorkflowNode(
                node_id="read", tool_id="business_db", action="read", params={"entity": "products"}
            )
        ],
    )
    with patch(
        "app.infrastructure.workflow.langgraph_runtime.XCAGILangGraphRuntime.run",
        side_effect=error_type(secret),
    ) as execute_graph:
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1", message="读取产品", plan=plan
        )
    execute_graph.assert_called_once()
    assert run.status == "blocked" and run.error == "计划图校验或执行失败"
    assert secret not in str(repo.get(run.run_id).to_dict())
    assert secret in caplog.text
    assert run.tool_calls == []
    assert any(event.event_type == "workflow.graph_rejected" for event in run.events)


def test_agent_orchestrator_executes_low_risk_tool_and_records_events():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "XG-5003"}]},
        ) as mock_execute,
    ):
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            plan=_business_plan(write=False),
            user_id="u1",
            message="查数据库产品 XG-5003",
            runtime_context={"source": "test"},
        )

    assert run.status == "completed"
    assert run.intent == "business_db_read"
    assert len(run.steps) == 1
    assert run.steps[0].status == "completed"
    assert run.steps[0].tool_id == "business_db"
    assert run.steps[0].action == "read"
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0].tool_id == "business_db"
    assert run.tool_calls[0].action == "read"
    assert run.tool_calls[0].status == "completed"
    assert run.tool_calls[0].cost_units == 1
    assert run.metadata["tool_call_count"] == 1
    assert run.metadata["cost_units_total"] == 1
    assert run.final_output["cost_units_total"] == 1
    assert run.final_output["node_outputs"][run.steps[0].node_id]["success"] is True
    assert repo.get(run.run_id) is not None

    mock_execute.assert_called_once()
    tool_id, action, params = mock_execute.call_args.args
    assert tool_id == "business_db"
    assert action == "read"
    assert params["_runtime_context"]["run_id"] == run.run_id
    assert params["_runtime_context"]["message"] == "查数据库产品 XG-5003"

    event_types = [event.event_type for event in run.events]
    assert "run.created" in event_types
    assert "planner.completed" in event_types
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    assert "run.completed" in event_types
    completed_event = next(event for event in run.events if event.event_type == "tool.completed")
    assert completed_event.data["call_id"] == run.tool_calls[0].call_id
    assert completed_event.data["cost_units"] == 1


def test_agent_tool_executor_restores_durable_purchase_tenant_scope():
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.infrastructure.tenant_scope import current_tenant_id

    observed_tenant_ids: list[int | None] = []

    def _execute(_tool_id, _action, _params):
        observed_tenant_ids.append(current_tenant_id())
        return {"success": True, "data": {"id": 7}}

    step = AgentStep(
        node_id="create_supplier",
        tool_id="purchase",
        action="create_supplier",
        params={"name": "XC 演示供应商"},
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=_execute,
    ) as mock_execute:
        result = AgentToolExecutor().execute(
            step,
            runtime_context={"tenant_id": "7", "idempotency_key": f"purchase:{step.step_id}"},
        )

    assert result["success"] is True
    assert observed_tenant_ids == [7]
    assert current_tenant_id() == 1
    mock_execute.assert_called_once()


@pytest.mark.parametrize("tenant_id", [True, 0, -1, 1.5, "1.5", "not-a-tenant"])
def test_agent_tool_executor_rejects_invalid_runtime_tenant_scope(tenant_id):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    step = AgentStep(
        node_id="read_customer",
        tool_id="business_db",
        action="read",
        params={"entity": "customers", "keyword": "XC 演示客户"},
    )
    with (
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
        result = AgentToolExecutor().execute(step, runtime_context={"tenant_id": tenant_id})

    assert result["success"] is False
    assert result["error_code"] == "invalid_tenant_context"
    mock_execute.assert_not_called()


@pytest.mark.parametrize("tenant_id", [7, "7", True, 1.5, "invalid"])
def test_inventory_tool_restores_and_validates_runtime_tenant(tenant_id):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.infrastructure.tenant_scope import current_tenant_id

    seen = []

    def execute(*args):
        seen.append(current_tenant_id())
        return {"success": True}

    step = AgentStep(
        node_id="in",
        tool_id="inventory",
        action="stock_in",
        params={"product_id": 1, "warehouse_id": 2, "quantity": 50},
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", side_effect=execute
    ):
        result = AgentToolExecutor().execute(
            step,
            runtime_context={
                "tenant_id": tenant_id,
                "idempotency_key": f"inventory:{step.step_id}",
            },
        )
    valid = tenant_id in (7, "7")
    assert result["success"] is valid
    assert seen == ([7] if valid else [])
    assert current_tenant_id() == 1


def test_agent_tool_executor_restores_tenant_scope_for_excel_read():
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.infrastructure.tenant_scope import current_tenant_id

    seen: list[int | None] = []

    def execute(*_args):
        seen.append(current_tenant_id())
        return {"success": True, "data": {"row_count": 1}}

    step = AgentStep(
        node_id="read_excel",
        tool_id="excel_analysis",
        action="read",
        params={"file_path": "upload-id"},
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", side_effect=execute
    ):
        result = AgentToolExecutor().execute(step, runtime_context={"tenant_id": "7"})

    assert result["success"] is True
    assert seen == [7]
    assert current_tenant_id() == 1


def test_agent_tool_executor_preserves_opaque_dataset_tenant_key():
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    step = AgentStep(
        node_id="query_dataset",
        tool_id="dataset_rag",
        action="query",
        params={"dataset_id": "platform-docs", "query": "Which model?"},
    )
    output = {
        "success": True,
        "dataset_id": "platform-docs",
        "query": "Which model?",
        "answer": "XCauto",
        "chunks": [{"chunk_id": "chunk-1", "text": "XCauto", "source": "policy"}],
        "citations": [{"index": 1, "source": "policy", "chunk_index": 0}],
    }
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value=output,
    ) as mock_execute:
        result = AgentToolExecutor().execute(step, runtime_context={"tenant_id": "tenant-a"})

    assert result == output
    assert mock_execute.call_args.args[2]["_runtime_context"]["tenant_id"] == "tenant-a"


def test_agent_orchestrator_waits_for_user_on_medium_risk_step():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            plan=_business_plan(write=True),
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
        )

    assert run.status == "waiting_user"
    assert run.steps[0].status == "waiting_user"
    assert run.steps[0].tool_id == "business_db"
    assert run.steps[0].action == "write"
    assert run.steps[0].risk == "medium"
    assert mock_execute.call_count == 0
    assert "step.waiting_user" in [event.event_type for event in run.events]


def test_approved_write_without_source_evidence_stays_blocked():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(
            plan=_business_plan(write=True),
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
            runtime_context={"source": "approval-test"},
        )
        mock_execute.assert_not_called()
        mock_execute.return_value = {"success": True, "message": "客户已写入"}
        completed = orchestrator.continue_run(waiting.run_id, approved_by="tester")

    assert completed is not None
    assert completed.status == "blocked", (
        completed.error,
        [(event.event_type, event.data) for event in completed.events[-5:]],
        [(step.status, step.error, step.output) for step in completed.steps],
    )
    assert completed.steps[0].status == "completed"
    assert completed.tool_calls[0].status == "completed"
    assert completed.tool_calls[0].cost_units == 2
    assert completed.metadata["cost_units_total"] == 2
    assert completed.tool_calls[0].output["success"] is True
    assert completed.metadata["verification"]["accepted"] is False
    assert "step.approved" in [event.event_type for event in completed.events]
    assert "tool.completed" not in [event.event_type for event in completed.events]
    mock_execute.assert_called_once()
    tool_id, action, params = mock_execute.call_args.args
    assert tool_id == "business_db"
    assert action == "write"
    assert params["_runtime_context"]["run_id"] == waiting.run_id
    assert params["_runtime_context"]["source"] == "approval-test"


def test_approved_sales_without_independent_receipt_stops_dependent_export():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="sales-then-export",
        intent="sales_write",
        nodes=[
            WorkflowNode(
                node_id="sales_execute_closed_loop",
                tool_id="sales",
                action="execute_closed_loop",
                params={"payload": {"order": {"customer_name": "测试客户 A"}}},
                risk="high",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="verify_sales_result",
                tool_id="sales",
                action="verify_closed_loop",
                params={"payload": {"order": {"customer_name": "测试客户 A"}}},
                risk="low",
                idempotent=True,
                depends_on=["sales_execute_closed_loop"],
            ),
            WorkflowNode(
                node_id="export_sales",
                tool_id="reports",
                action="export",
                params={"report_type": "sales"},
                risk="low",
                idempotent=True,
                depends_on=["verify_sales_result"],
            ),
        ],
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "message": "已完成"},
    ) as mock_execute:
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(user_id="u1", message="销售后导出", plan=plan)
        assert waiting.status == "waiting_user"
        assert [step.status for step in waiting.steps] == ["waiting_user", "pending", "pending"]
        assert waiting.steps[1].depends_on == ["sales_execute_closed_loop"]
        assert waiting.steps[2].depends_on == ["verify_sales_result"]
        mock_execute.assert_not_called()
        completed = orchestrator.continue_run(
            waiting.run_id,
            approved_by="approver",
            approved_step_id="sales_execute_closed_loop",
        )

    assert completed is not None
    assert completed.status == "blocked"
    assert [step.status for step in completed.steps] == ["completed", "pending", "pending"]
    assert [call.args[0:2] for call in mock_execute.call_args_list] == [
        ("sales", "execute_closed_loop"),
    ]


def test_changed_sale_quantity_cannot_reuse_the_approval():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="sales-tamper",
        intent="sales_write",
        nodes=[
            WorkflowNode(
                node_id="sales_execute_closed_loop",
                tool_id="sales",
                action="execute_closed_loop",
                params={"payload": {"order": {"items": [{"quantity": 10, "unit_price": 100}]}}},
                risk="high",
                idempotent=True,
            )
        ],
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True},
    ) as mock_execute:
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(user_id="u1", message="销售", plan=plan)
        waiting.steps[0].params["payload"]["order"]["items"][0]["quantity"] = 99
        repo.save(waiting)
        refused = orchestrator.continue_run(
            waiting.run_id, approved_by="approver", approved_step_id="sales_execute_closed_loop"
        )
    assert refused is not None
    assert refused.status == "blocked"
    assert mock_execute.call_count == 0
    assert "approval.resume_plan_rejected" in [event.event_type for event in refused.events]


def test_agent_orchestrator_ignores_continue_for_non_waiting_step():
    """A pending step cannot be continued through the approval route."""
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "message": "客户已写入"},
        ) as mock_execute,
    ):
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(
            plan=_business_plan(write=True), user_id="u1", message="请把客户 星光贸易 写入数据库"
        )
        waiting.status = "running"
        waiting.steps[0].status = "pending"
        repo.save(waiting)
        completed = orchestrator.continue_run(
            waiting.run_id,
            approved_by="route",
            approved_step_id=waiting.steps[0].node_id,
        )

    assert completed is not None
    assert completed.status == "running"
    assert completed.steps[0].status == "pending"
    assert completed.events[-1].event_type == "run.continue_ignored"
    mock_execute.assert_not_called()
