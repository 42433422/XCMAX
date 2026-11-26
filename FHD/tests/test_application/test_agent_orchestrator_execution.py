"""Orchestrator execution, billing and tool contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.test_application.test_agent_orchestrator import (
    _isolated_agent_usage_ledger as _isolated_agent_usage_ledger,
)


def test_agent_orchestrator_blocks_approved_step_when_budget_exceeded():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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

    with (
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
        patch(
            "app.application.agent_orchestrator.tool_permission.actor_tool_denial",
            return_value=None,
        ),
    ):
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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
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
    from app.application.workflow.workflow_types import WorkflowNode

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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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


def test_agent_orchestrator_rejects_missing_required_params_before_tool_execution():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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

    assert run.status == "blocked"
    assert run.steps[0].status == "pending"
    assert run.error.startswith("执行前计划审核未通过")
    assert run.tool_calls == []
    mock_execute.assert_not_called()


def test_agent_orchestrator_rejects_invalid_multistep_plan_before_first_side_effect():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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

    assert run.status == "blocked"
    assert run.error.startswith("执行前计划审核未通过")
    assert run.tool_calls == []
    mock_execute.assert_not_called()

    event_types = [event.event_type for event in run.events]
    assert "workflow.plan_audit_rejected" in event_types
    assert "tool.started" not in event_types
    assert "step.repair_applied" not in event_types


def test_agent_orchestrator_executes_three_ordered_tools_in_one_conversation():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="p-first-order-three-tools",
        intent="first_order_multistep",
        nodes=[
            WorkflowNode(
                node_id="find_customer",
                tool_id="business_db",
                action="read",
                params={"entity": "customers", "keyword": "新手演示客户"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="find_product",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "新手演示商品"},
                risk="low",
                idempotent=True,
                depends_on=["find_customer"],
            ),
            WorkflowNode(
                node_id="create_first_order",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "shipment_records",
                    "operation": "create",
                    "payload": {
                        "unit_name": "新手演示客户",
                        "products": [{"product_name": "新手演示商品", "quantity_tins": 1}],
                        "product_source_node": "find_product",
                    },
                },
                risk="medium",
                idempotent=False,
                depends_on=["find_product"],
            ),
        ],
    )

    def fake_execute(_tool_id: str, _action: str, params: dict):
        node_id = params["_runtime_context"]["node_id"]
        outputs = params["_runtime_context"]["node_outputs"]
        if node_id == "find_customer":
            return {"success": True, "data": [{"customer_id": 10}]}
        if node_id == "find_product":
            assert outputs["find_customer"]["data"][0]["customer_id"] == 10
            return {
                "success": True,
                "data": [
                    {"product_id": 20, "name": "新手演示商品", "specification": 1, "price": 99}
                ],
            }
        assert outputs["find_product"]["data"][0]["product_id"] == 20
        return {"success": True, "data": {"shipment_id": 30}}

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=fake_execute,
    ):
        repository = InMemoryAgentRunRepository()
        orchestrator = AgentOrchestrator(repository=repository)
        waiting = orchestrator.start_run_from_plan(
            user_id="u1",
            message="查询演示客户和商品，然后创建第一张演示出货单",
            plan=plan,
            runtime_context={"source": "first-order-acceptance"},
        )
        assert waiting.status == "waiting_user"
        payload = waiting.steps[-1].params["payload"]
        assert "product_source_node" not in payload
        assert payload["products"][0]["tin_spec"] == 1
        assert payload["products"][0]["unit_price"] == 99
        frozen = waiting.metadata["plan"]["nodes"][-1]
        assert frozen["params"] == waiting.steps[-1].params
        assert [call.node_id for call in waiting.tool_calls] == ["find_customer", "find_product"]
        run = orchestrator.continue_run(waiting.run_id, approved_by="u1")

    assert run is not None
    assert run.status == "blocked", (run.error, [step.to_dict() for step in run.steps])
    assert [call.node_id for call in run.tool_calls] == [
        "find_customer",
        "find_product",
        "create_first_order",
    ]
    assert run.metadata["tool_call_count"] == 3
    assert run.tool_calls[-1].output["data"]["shipment_id"] == 30
    assert run.metadata["verification"]["accepted"] is False


def test_agent_orchestrator_skips_llm_repair_for_invalid_plan(tmp_path, monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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

    with (
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

    assert run.status == "blocked"
    assert run.error.startswith("执行前计划审核未通过")
    assert run.tool_calls == []
    assert run.llm_calls == []
    mock_execute.assert_not_called()


def test_unverified_pickup_token_is_not_a_verified_download_after_approval():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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
            "app.application.workflow.tool_profile.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch(
            "app.domain.shared_services.kitten_ai_document.generate.generate_office_file",
            return_value=(b"content", "contract.docx"),
        ),
        patch(
            "app.domain.shared_services.kitten_ai_document.pickup.store_document_pickup",
            return_value="doc-token",
        ),
        patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
        patch(
            "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
            return_value=(None, None),
        ),
        patch(
            "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
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
    assert run.status == "blocked"
    assert run.steps[0].risk == "medium"
    assert run.steps[0].idempotent is False
    assert not run.artifacts
    assert run.metadata["verification"]["accepted"] is False
    assert "artifact.attached" not in [event.event_type for event in run.events]


def test_approval_resume_without_durable_snapshot_fails_closed():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id="shipment-export-test",
        intent="business_db_write",
        metadata={"approval_required_node_ids": ["shipment"]},
        nodes=[
            WorkflowNode(
                node_id="shipment",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "shipment_records",
                    "operation": "create",
                    "payload": {
                        "unit_name": "测试客户",
                        "products": [
                            {
                                "product_name": "测试商品",
                                "quantity_tins": 1,
                                "tin_spec": 1,
                                "unit_price": 1,
                            }
                        ],
                    },
                },
                risk="high",
            ),
            WorkflowNode(
                node_id="export",
                tool_id="business_db",
                action="read",
                params={"entity": "shipment_records"},
                risk="low",
                idempotent=True,
                depends_on=["shipment"],
            ),
        ],
    )
    observed = []

    def execute(_tool, _action, params):
        context = params["_runtime_context"]
        observed.append(context["node_id"])
        if context["node_id"] == "export":
            assert context["node_outputs"]["shipment"]["data"]["id"] == 42
            return {"success": True, "data": [{"id": 42}]}
        return {"success": True, "data": {"id": 42}}

    with (
        patch(
            "app.application.agent_orchestrator.AgentOrchestrator",
            return_value=orchestrator,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=execute,
        ),
    ):
        waiting = orchestrator.start_run_from_plan(
            user_id="u1",
            message="出库并导出",
            plan=plan,
            runtime_context={"message": "出库并导出"},
        )
        assert waiting.status == "waiting_user" and observed == []
        run_id = waiting.run_id
        completed = orchestrator.continue_run(
            run_id, approved_by="reviewer", approved_step_id="shipment"
        )
    assert completed is not None and completed.status == "blocked", (
        completed.error,
        [(s.node_id, s.status, s.error, s.output) for s in completed.steps],
    )
    assert completed.error == "持久化审批与当前完整执行计划不匹配"
    assert observed == []


def test_in_memory_approval_snapshot_cannot_resume_protected_plan():
    import logging

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    agent = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id="two-approvals",
        intent="test",
        nodes=[
            WorkflowNode(
                "first",
                "business_db",
                "read",
                params={"entity": "products"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                "second",
                "business_db",
                "read",
                params={"entity": "customers"},
                risk="low",
                idempotent=True,
                depends_on=["first"],
            ),
            WorkflowNode(
                "third",
                "business_db",
                "read",
                params={"entity": "products"},
                risk="low",
                idempotent=True,
                depends_on=["second"],
            ),
        ],
    )

    class Approvals:
        def __init__(self):
            self.items = {}
            self.counter = 0

        def create_approval_request(
            self, *, plan_id, node, runtime_context, plan, require_persistence, request_id=None
        ):
            self.counter += 1
            request_id = request_id or f"request-{self.counter}"
            self.items[request_id] = {"plan": plan, "runtime_context": runtime_context}
            return SimpleNamespace(request_id=request_id)

        def attach_pending_agent_run(self, request_id, *, agent_run_id, approved_step_id):
            self.items[request_id].update(
                agent_run_id=agent_run_id, approved_step_id=approved_step_id
            )
            return True

        def get_request_metadata(self, request_id):
            return {"request_no": request_id}

        def get_pending_workflow(self, request_id):
            return self.items.get(request_id)

        def remove_pending_workflow(self, request_id):
            return self.items.pop(request_id, None)

        def approve(self, request_id, comment):
            return request_id in self.items

    approvals = Approvals()

    def execution_snapshot(request_id):
        return approvals.items.get(request_id)

    bridge = WorkflowApprovalBridge(
        WorkflowBackends(
            approvals=lambda: approvals,
            pending_snapshot=lambda _request_id: None,
            execution_snapshot=execution_snapshot,
            agent=lambda: agent,
            load_run=repo.get,
        ),
        (RuntimeError,),
        logging.getLogger(__name__),
    )
    calls = []

    def execute(_tool, _action, params):
        calls.append(params["_runtime_context"]["node_id"])
        return {"success": True, "data": []}

    with (
        patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=agent),
        patch(
            "app.application.workflow.approval_persistence.claim_agent_approval", return_value=True
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=execute,
        ),
    ):
        plan.metadata["approval_required_node_ids"] = ["first", "second"]
        waiting = agent.start_run_from_plan(user_id="u1", message="顺序执行", plan=plan)
        assert waiting.status == "waiting_user" and calls == []
        first = approvals.create_approval_request(
            plan_id=plan.plan_id,
            node=plan.nodes[0],
            runtime_context={},
            plan=plan,
            require_persistence=False,
        ).request_id
        run_id = waiting.run_id
        approvals.attach_pending_agent_run(first, agent_run_id=run_id, approved_step_id="first")
        first_result = bridge.resume(request_no=first, opinion="同意", approved_by="7")
        assert first_result["success"] is False
        assert first_result.get("waiting_approval") is not True
        assert calls == []
        run = repo.get(run_id)
        assert run.status == "waiting_user"
        assert run.tool_calls == []
        assert "审批" in first_result.get("message", "") or first_result.get("success") is False


def test_unknown_nested_tool_receipt_blocks_repair_followups_and_refund(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.infrastructure.billing.model_usage import get_model_wallet, set_model_wallet_balance

    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    set_model_wallet_balance("u1", 3, reason="uncertain-tool-test")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-uncertain-tool",
        intent="business_db_read",
        metadata={"repair_overrides": {"read": {"retry": True, "max_attempts": 2}}},
        nodes=[
            WorkflowNode(
                node_id=node,
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003"},
                risk="low",
                idempotent=True,
                depends_on=[] if node == "read" else ["read"],
            )
            for node in ("read", "followup")
        ],
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={
            "success": True,
            "data": [{"model_number": "5003"}],
            "request_id": "original-request",
            "result": {"outputs": [{"outcome_unknown": True, "action_id": "original-action"}]},
        },
    ) as dispatch:
        run = AgentOrchestrator(repository=repo).start_run_from_plan(
            user_id="u1", message="查产品后继续核对", plan=plan
        )
        assert run.status == "blocked" and run.metadata["non_retryable"] is True
        assert run.metadata["recovery"]["state"] == "manual_reconciliation_required"
        assert len(run.tool_calls) == 1 and run.steps[0].status == "failed"
        assert run.steps[0].repair_history == [] and run.steps[1].status == "pending"
        assert run.tool_calls[0].output["outcome"] == "unknown"
        assert not run.tool_calls[0].metadata.get("wallet_refund")
        assert get_model_wallet("u1")["balance_units"] == 2
        reopened = AgentOrchestrator(repository=repo).continue_run(run.run_id, approved_by="u1")
        assert reopened is not None and reopened.status == "blocked"
        assert reopened.tool_calls[0].output["outcome"] == "unknown"
        dispatch.assert_called_once()
