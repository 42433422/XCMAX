from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_agent_usage_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def _planner_fallback_patches():
    return (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch(
            "app.application.workflow.planner.LLMWorkflowPlanner._plan_with_react_multiagent",
            return_value=None,
        ),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
    )


def test_agent_orchestrator_executes_low_risk_tool_and_records_events():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    patches = _planner_fallback_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "XG-5003"}]},
        ) as mock_execute,
    ):
        run = AgentOrchestrator(repository=repo).start_run(
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


def test_agent_orchestrator_waits_for_user_on_medium_risk_step():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    patches = _planner_fallback_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
        run = AgentOrchestrator(repository=repo).start_run(
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


def test_agent_orchestrator_continues_waiting_run_after_approval():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    patches = _planner_fallback_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run(
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
            runtime_context={"source": "approval-test"},
        )
        mock_execute.assert_not_called()
        mock_execute.return_value = {"success": True, "message": "客户已写入"}
        completed = orchestrator.continue_run(waiting.run_id, approved_by="tester")

    assert completed is not None
    assert completed.status == "completed"
    assert completed.steps[0].status == "completed"
    assert completed.tool_calls[0].status == "completed"
    assert completed.tool_calls[0].cost_units == 2
    assert completed.metadata["cost_units_total"] == 2
    assert completed.final_output["node_outputs"][completed.steps[0].node_id]["success"] is True
    assert "step.approved" in [event.event_type for event in completed.events]
    assert "tool.completed" in [event.event_type for event in completed.events]
    mock_execute.assert_called_once()
    tool_id, action, params = mock_execute.call_args.args
    assert tool_id == "business_db"
    assert action == "write"
    assert params["_runtime_context"]["run_id"] == waiting.run_id
    assert params["_runtime_context"]["source"] == "approval-test"


def test_agent_orchestrator_blocks_approved_step_when_budget_exceeded():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-budget",
        intent="business_db_write",
        metadata={"ai_cost_budget_units": 1},
        nodes=[
            WorkflowNode(
                node_id="write_customer",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "Acme Trading"},
                },
                risk="low",
                idempotent=True,
            )
        ],
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool"
    ) as mock_execute:
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(
            user_id="u1",
            message="写入客户",
            plan=plan,
            runtime_context={"source": "budget-test"},
        )
        blocked = orchestrator.continue_run(waiting.run_id, approved_by="tester")

    assert waiting.status == "waiting_user"
    assert blocked is not None
    assert blocked.status == "failed"
    assert blocked.error == "AI cost budget exceeded"
    assert blocked.steps[0].status == "failed"
    assert blocked.steps[0].error == "AI cost budget exceeded"
    assert blocked.tool_calls == []
    assert blocked.metadata["tool_call_count"] == 0
    assert blocked.metadata["cost_units_total"] == 0
    assert blocked.metadata["ai_cost_units_total"] == 0
    assert blocked.metadata["ai_cost_budget_units"] == 1
    assert blocked.metadata["ai_cost_budget_remaining_units"] == 1
    assert blocked.metadata["ai_cost_budget_exceeded"] is True
    assert blocked.final_output["ai_cost_budget_exceeded"] is True
    assert blocked.final_output["ai_cost_budget_units"] == 1
    assert blocked.final_output["error"] == "AI cost budget exceeded"
    assert "budget.exceeded" in [event.event_type for event in blocked.events]
    budget_event = next(event for event in blocked.events if event.event_type == "budget.exceeded")
    assert budget_event.data["additional_cost_units"] == 2
    assert budget_event.data["projected_units"] == 2
    mock_execute.assert_not_called()


def test_agent_orchestrator_blocks_tool_execution_when_wallet_insufficient(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-tool-wallet-block",
        intent="business_db_write",
        nodes=[
            WorkflowNode(
                node_id="write_customer",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "Wallet Blocked Trading"},
                },
                risk="low",
                idempotent=True,
            )
        ],
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool"
    ) as mock_execute:
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(
            user_id="u1",
            message="写入客户但钱包不足",
            plan=plan,
            runtime_context={"source": "tool-wallet-test"},
        )
        blocked = orchestrator.continue_run(waiting.run_id, approved_by="tester")

    assert waiting.status == "waiting_user"
    assert blocked is not None
    assert blocked.status == "failed"
    assert blocked.error == "AI tool wallet balance insufficient"
    assert blocked.steps[0].status == "failed"
    assert blocked.steps[0].error == "AI tool wallet balance insufficient"
    assert len(blocked.tool_calls) == 1
    assert blocked.tool_calls[0].status == "failed"
    assert blocked.tool_calls[0].metadata["billing_status"] == "insufficient_balance"
    assert blocked.tool_calls[0].metadata["wallet_debit"]["shortfall_units"] == 2
    assert blocked.metadata["tool_usage_entry_count"] == 1
    assert blocked.metadata["tool_usage_cost_units_total"] == 2
    assert blocked.metadata["tool_usage_ledger_status"] == "recorded"
    assert blocked.final_output["tool_usage_entry_count"] == 1
    assert blocked.final_output["error"] == "AI tool wallet balance insufficient"
    assert "billing.insufficient_balance" in [event.event_type for event in blocked.events]
    assert "tool.failed" in [event.event_type for event in blocked.events]
    mock_execute.assert_not_called()


def test_agent_orchestrator_refunds_local_wallet_when_charged_tool_fails(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.infrastructure.billing.model_usage import get_model_wallet, set_model_wallet_balance

    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    set_model_wallet_balance("u1", 3, reason="tool-refund-test")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-tool-refund",
        intent="business_db_read",
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003"},
                risk="low",
                idempotent=True,
            )
        ],
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": False, "message": "temporary database error"},
    ) as mock_execute:
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1",
            message="查数据库产品 5003",
            plan=plan,
            runtime_context={"source": "tool-refund-test"},
        )

    assert run.status == "failed"
    assert run.error == "temporary database error"
    assert run.tool_calls[0].metadata["billing_status"] == "debited"
    assert run.tool_calls[0].metadata["wallet_debit"]["balance_after_units"] == 2
    assert run.tool_calls[0].metadata["wallet_refund"]["status"] == "refunded"
    assert run.tool_calls[0].metadata["wallet_refund"]["balance_after_units"] == 3
    assert run.metadata["tool_usage_entry_count"] == 1
    assert run.metadata["tool_usage_refund_count"] == 1
    assert run.metadata["tool_usage_refund_cost_units_total"] == 1
    assert run.metadata["tool_usage_refund_status"] == "refunded"
    assert run.metadata["model_wallet_balance_units"] == 3
    assert run.final_output["tool_usage_refund_count"] == 1
    assert get_model_wallet("u1")["balance_units"] == 3
    event_types = [event.event_type for event in run.events]
    assert "billing.debited" in event_types
    assert "billing.refunded" in event_types
    assert "tool.failed" in event_types
    mock_execute.assert_called_once()


def test_agent_orchestrator_refunds_market_wallet_when_charged_tool_fails(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.infrastructure.billing import model_usage

    class FakeMarketResponse:
        def __init__(self, body, status_code=200):
            self._body = body
            self.status_code = status_code
            self.text = str(body)

        def json(self):
            return self._body

    class FakeMarketClient:
        def __init__(self, *args, **kwargs):
            self._responses = responses

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers=None, json=None):
            market_calls.append({"url": url, "headers": headers or {}, "json": json or {}})
            return self._responses.pop(0)

    responses = [
        FakeMarketResponse(
            {
                "ok": True,
                "hold": {"hold_no": "AIH-MARKET", "amount": "0.02", "status": "held"},
                "balance": "9.98",
            }
        ),
        FakeMarketResponse(
            {
                "ok": True,
                "hold": {
                    "hold_no": "AIH-MARKET",
                    "amount": "0.02",
                    "settled_amount": "0.02",
                    "status": "settled",
                },
                "balance": "9.98",
            }
        ),
        FakeMarketResponse(
            {
                "ok": True,
                "refund": {"hold_no": "AIH-MARKET", "amount": "0.02", "status": "refunded"},
                "balance": "10.00",
            }
        ),
    ]
    market_calls = []
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "http://market.test")
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "market-token")
    monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.02")
    monkeypatch.setattr(model_usage.httpx, "Client", FakeMarketClient)
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-tool-market-refund",
        intent="business_db_read",
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003"},
                risk="low",
                idempotent=True,
            )
        ],
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": False, "message": "temporary database error"},
    ):
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1",
            message="查数据库产品 5003",
            plan=plan,
            runtime_context={"source": "tool-market-refund-test"},
        )

    assert run.status == "failed"
    assert run.tool_calls[0].metadata["billing_status"] == "debited"
    assert run.tool_calls[0].metadata["wallet_refund"]["status"] == "refunded"
    assert run.tool_calls[0].metadata["wallet_refund"]["amount_yuan"] == "0.02"
    assert run.metadata["tool_usage_refund_count"] == 1
    assert run.metadata["tool_usage_refund_status"] == "refunded"
    assert run.metadata["model_wallet_balance_yuan"] == "10.00"
    assert len(market_calls) == 3
    assert market_calls[0]["url"].endswith("/api/wallet/ai/preauthorize")
    assert market_calls[1]["url"].endswith("/api/wallet/ai/settle")
    assert market_calls[2]["url"].endswith("/api/wallet/ai/refund")
    assert market_calls[2]["json"]["refund_amount"] == "0.02"
    assert market_calls[2]["headers"]["Authorization"] == "Bearer market-token"
    event_types = [event.event_type for event in run.events]
    assert "billing.debited" in event_types
    assert "billing.refunded" in event_types
    assert "tool.failed" in event_types


def test_agent_orchestrator_uses_tool_spec_risk_over_planner_claim():
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.workflow.types import WorkflowNode

    node = WorkflowNode(
        node_id="write_customer",
        tool_id="business_db",
        action="write",
        params={"entity": "customers", "operation": "create", "payload": {"unit_name": "A"}},
        risk="low",
        idempotent=True,
    )

    step = AgentOrchestrator._step_from_node(node)

    assert step.action == "write"
    assert step.risk == "medium"
    assert step.idempotent is False


def test_agent_orchestrator_starts_from_existing_plan():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-existing",
        intent="business_db_read",
        metadata={
            "artifacts": [
                {
                    "artifact_type": "excel_records",
                    "name": "报价.xlsx",
                    "source": "test",
                    "summary": "输入表格",
                }
            ]
        },
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003"},
                risk="low",
                idempotent=True,
            )
        ],
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "data": [{"model_number": "5003"}]},
    ):
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1",
            message="查数据库产品 5003",
            plan=plan,
            runtime_context={"source": "test"},
        )

    assert run.status == "completed"
    assert run.plan_id == "p-existing"
    assert run.steps[0].status == "completed"
    assert run.events[1].data["source"] == "provided_plan"
    assert run.metadata["artifact_count"] == 1
    assert run.artifacts[0].artifact_type == "excel_records"
    assert run.final_output["artifacts"][0]["name"] == "报价.xlsx"
    assert "artifact.attached" in [event.event_type for event in run.events]


def test_agent_orchestrator_applies_controlled_repair_and_retries_low_risk_step():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-repair",
        intent="business_db_read",
        metadata={
            "repair_overrides": {
                "read_products": {
                    "params": {"entity": "products"},
                    "reason": "entity inferred from product lookup intent",
                }
            }
        },
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"keyword": "5003"},
                risk="low",
                idempotent=True,
            )
        ],
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "data": [{"model_number": "5003"}]},
    ) as mock_execute:
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1",
            message="查数据库产品 5003",
            plan=plan,
            runtime_context={"source": "repair-test"},
        )

    assert run.status == "completed"
    assert run.steps[0].status == "completed"
    assert run.steps[0].attempt_count == 2
    assert run.steps[0].max_repair_attempts == 1
    assert run.steps[0].params["entity"] == "products"
    assert len(run.steps[0].observations) == 2
    assert len(run.steps[0].repair_history) == 1
    assert run.steps[0].repair_history[0]["params_patch"] == {"entity": "products"}
    assert [call.status for call in run.tool_calls] == ["failed", "completed"]
    assert run.metadata["observation_count"] == 2
    assert run.metadata["repair_count"] == 1
    assert run.final_output["repair_count"] == 1
    assert mock_execute.call_count == 1
    assert mock_execute.call_args.args[2]["entity"] == "products"

    event_types = [event.event_type for event in run.events]
    assert "observation.recorded" in event_types
    assert "step.repair_applied" in event_types
    assert "step.retry_scheduled" in event_types
    assert "run.completed" in event_types


def test_agent_orchestrator_continues_multistep_run_after_second_step_repair():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-multistep-repair",
        intent="business_db_read_multistep",
        metadata={
            "repair_overrides": {
                "read_materials": {
                    "params": {"entity": "materials"},
                    "reason": "material lookup step requires entity",
                }
            }
        },
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="read_materials",
                tool_id="business_db",
                action="read",
                params={"keyword": "PVC"},
                risk="low",
                idempotent=True,
                depends_on=["read_products"],
            ),
        ],
    )

    def fake_execute(tool_id: str, action: str, params: dict):
        if params["entity"] == "products":
            return {"success": True, "data": [{"model_number": "5003"}]}
        assert (
            params["_runtime_context"]["node_outputs"]["read_products"]["data"][0]["model_number"]
            == "5003"
        )
        return {"success": True, "data": [{"material_name": "PVC"}]}

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=fake_execute,
    ) as mock_execute:
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1",
            message="先查产品 5003，再查 PVC 材料",
            plan=plan,
            runtime_context={"source": "multistep-repair-test"},
        )

    assert run.status == "completed"
    assert [step.status for step in run.steps] == ["completed", "completed"]
    assert [step.attempt_count for step in run.steps] == [1, 2]
    assert run.steps[1].params["entity"] == "materials"
    assert run.steps[1].repair_history[0]["params_patch"] == {"entity": "materials"}
    assert [call.status for call in run.tool_calls] == ["completed", "failed", "completed"]
    assert [call.node_id for call in run.tool_calls] == [
        "read_products",
        "read_materials",
        "read_materials",
    ]
    assert run.metadata["observation_count"] == 3
    assert run.metadata["repair_count"] == 1
    assert run.final_output["node_outputs"]["read_products"]["success"] is True
    assert run.final_output["node_outputs"]["read_materials"]["success"] is True
    assert run.final_output["repair_count"] == 1
    assert mock_execute.call_count == 2

    event_types = [event.event_type for event in run.events]
    assert "step.repair_applied" in event_types
    assert "step.retry_scheduled" in event_types
    assert "run.completed" in event_types


def test_agent_orchestrator_uses_llm_repair_for_low_risk_idempotent_step(tmp_path, monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import LLMCall
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("LLM_PROVIDER", "xcauto")
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-test")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-llm-repair",
        intent="business_db_read",
        metadata={"repair_policy": {"mode": "llm", "max_attempts": 1}},
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"keyword": "5003"},
                risk="low",
                idempotent=True,
            )
        ],
    )

    repair_call = LLMCall(
        provider_id="openai_compatible",
        provider="xcauto",
        model="xcauto-account",
        prompt_tokens=20,
        completion_tokens=10,
        total_tokens=30,
        cost_units=1,
        billing_status="metered",
        billing_source="estimated_token_units",
        metadata={"source": "agent_orchestrator.llm_repair"},
    )
    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.request_llm_repair",
            return_value={
                "success": True,
                "params_patch": {"entity": "products"},
                "reason": "business_db.read requires entity",
                "confidence": 0.91,
                "llm_call": repair_call,
            },
        ) as mock_repair,
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "5003"}]},
        ) as mock_execute,
    ):
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1",
            message="查数据库产品 5003",
            plan=plan,
            runtime_context={"source": "llm-repair-test"},
        )

    assert run.status == "completed"
    assert run.steps[0].attempt_count == 2
    assert run.steps[0].params["entity"] == "products"
    assert run.steps[0].repair_history[0]["source"] == "llm_repair"
    assert run.metadata["repair_count"] == 1
    assert run.metadata["llm_call_count"] == 1
    assert run.metadata["llm_provider"] == "xcauto"
    assert run.metadata["llm_model"] == "xcauto-account"
    assert run.metadata["model_usage_entry_count"] == 1
    assert run.final_output["llm_calls"][0]["provider"] == "xcauto"
    assert run.final_output["ai_cost_units_total"] == 3
    event_types = [event.event_type for event in run.events]
    assert "step.llm_repair_requested" in event_types
    assert "llm.completed" in event_types
    assert "billing.recorded" in event_types
    assert "step.repair_applied" in event_types
    assert "step.retry_scheduled" in event_types
    assert "run.completed" in event_types
    mock_repair.assert_called_once()
    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[2]["entity"] == "products"


def test_agent_orchestrator_generates_office_document_as_artifact_after_approval():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-doc",
        intent="generate_office_document",
        nodes=[
            WorkflowNode(
                node_id="make_contract",
                tool_id="generate_office_document",
                action="execute",
                params={"user_request": "生成测试合同", "output_format": "docx"},
                risk="low",
                idempotent=True,
            )
        ],
    )

    with (
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch(
            "app.services.kitten_ai_document.generate.generate_office_file",
            return_value=(b"content", "contract.docx"),
        ),
        patch(
            "app.services.kitten_ai_document.pickup.store_document_pickup",
            return_value="doc-token",
        ),
        patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
        patch(
            "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
            return_value=(None, None),
        ),
        patch(
            "app.application.employee_pack_runner.try_execute_employee_planner_tool",
            return_value=None,
        ),
    ):
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run_from_plan(
            user_id="u1",
            message="生成测试合同",
            plan=plan,
            runtime_context={"source": "test"},
        )
        run = orchestrator.continue_run(waiting.run_id, approved_by="tester")

    assert waiting.status == "waiting_user"
    assert run is not None
    assert run.status == "completed"
    assert run.steps[0].risk == "medium"
    assert run.steps[0].idempotent is False
    assert run.artifacts[0].artifact_type == "office_document"
    assert run.artifacts[0].name == "contract.docx"
    assert run.artifacts[0].uri == "/api/ai/kitten/document/pickup/doc-token"
    assert run.metadata["artifact_count"] == 1
    assert run.final_output["artifacts"][0]["mime_type"].endswith("wordprocessingml.document")
    assert "artifact.attached" in [event.event_type for event in run.events]
