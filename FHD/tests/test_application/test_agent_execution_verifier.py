from __future__ import annotations

from unittest.mock import patch


def test_query_receipt_accepts_verified_empty_result() -> None:
    from app.application.agent_orchestrator.execution_verifier import (
        verify_tool_execution,
    )
    from app.application.agent_orchestrator.tool_spec import validate_tool_result

    output = {"success": True, "data": []}
    contract = validate_tool_result("business_db", "read", output)
    result = verify_tool_execution(
        "business_db",
        "read",
        {"entity": "products", "keyword": "missing"},
        output,
    )

    assert contract.ok is True
    assert result.accepted is True
    assert result.verified is True
    assert result.status == "verified"
    assert result.evidence["data"] == {"count": 0}


def test_write_without_business_receipt_is_inconclusive() -> None:
    from app.application.agent_orchestrator.execution_verifier import (
        verify_tool_execution,
    )

    result = verify_tool_execution(
        "business_db",
        "write",
        {"entity": "customers", "operation": "create", "payload": {"unit_name": "A"}},
        {"success": True, "message": "客户已写入"},
    )

    assert result.accepted is True
    assert result.verified is False
    assert result.status == "inconclusive"
    assert "业务回执" in result.reason


def test_product_delete_receipt_is_verified() -> None:
    from app.application.agent_orchestrator.execution_verifier import (
        verify_tool_execution,
    )

    result = verify_tool_execution(
        "products",
        "delete",
        {"id": 7},
        {
            "success": True,
            "record_id": 7,
            "deleted": 1,
            "data": {"id": 7, "exists_after": False},
        },
    )

    assert result.accepted is True
    assert result.verified is True
    assert result.status == "verified"
    assert result.evidence["record_id"] == 7
    assert result.evidence["deleted"] == 1


def test_employee_success_envelope_still_requires_semantic_output() -> None:
    from app.application.agent_orchestrator.execution_verifier import (
        verify_tool_execution,
    )

    result = verify_tool_execution(
        "employee",
        "execute",
        {"employee_id": "demo", "task": "生成报表"},
        {"success": True, "result": {}},
    )

    assert result.accepted is False
    assert result.verified is False
    assert result.status == "failed"


def test_employee_list_uses_query_receipt_contract() -> None:
    from app.application.agent_orchestrator.execution_verifier import (
        verify_tool_execution,
    )
    from app.application.agent_orchestrator.tool_spec import validate_tool_result

    output = {
        "success": True,
        "message": "已发现 1 个可调用员工",
        "data": {
            "employee_pack_tools": [{"employee_id": "quote-agent"}],
            "installed_employee_pack_count": 1,
        },
    }

    contract = validate_tool_result("employee", "list", output)
    verification = verify_tool_execution("employee", "list", {}, output)

    assert contract.ok is True
    assert verification.verifier == "query_receipt"
    assert verification.verified is True


def test_agent_run_records_verified_goal_and_task_ledger() -> None:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="plan-verified",
        intent="business_db_read",
        metadata={"planner": "llm", "planner_mode": "autonomous"},
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
        run = AgentOrchestrator(
            repository=InMemoryAgentRunRepository(),
        ).start_run_from_plan(
            user_id="u1",
            message="查询产品 5003",
            plan=plan,
            runtime_context={"dynamic_workflow": True},
        )

    assert run.status == "completed"
    assert run.metadata["goal_verified"] is True
    assert run.final_output["goal_verified"] is True
    assert run.final_output["task_ledger"]["goal"] == "查询产品 5003"
    assert run.final_output["task_ledger"]["planner_mode"] == "autonomous"
    event_types = [event.event_type for event in run.events]
    assert "verification.verified" in event_types
    assert "ledger.updated" in event_types


def test_generic_fallback_blocks_instead_of_guessing_a_product_query() -> None:
    from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry

    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("plan-degraded", "随便问问", get_tool_registry())

    assert plan.intent == "clarification_required"
    assert plan.nodes == []
    assert plan.metadata["planner_mode"] == "degraded"
    assert plan.metadata["execution_policy"] == "blocked_no_safe_action"
