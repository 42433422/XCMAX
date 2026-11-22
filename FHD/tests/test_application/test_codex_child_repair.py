"""Frozen Codex children retain exact retry identity across repair entry points."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator.repair_advisor import is_llm_repair_enabled
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repair import RunRepair
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_spec import validate_tool_call


def repair_case(binding="source", override=None, output=None):
    repository = InMemoryAgentRunRepository()
    parent = AgentRun(user_id="owner", message="read", status="running")
    parent.metadata["runtime_type"] = "codex"
    repository.save(parent)
    context = (
        {"source": "codex_runtime"}
        if binding == "source"
        else {"parent_run_id": parent.run_id}
        if binding == "parent"
        else {}
    )
    step = AgentStep(
        node_id="read",
        tool_id="excel_analysis",
        action="read",
        params={"file_path": "original.xlsx"},
        risk="low",
        idempotent=True,
        status="failed",
        output=output or {"success": False, "error": "temporary"},
    )
    run = AgentRun(user_id="owner", message="read", status="failed", steps=[step])
    run.metadata.update(
        runtime_context=context,
        plan={
            "metadata": {
                "repair_policy": {"mode": "llm", "max_attempts": 2},
                "repair_overrides": {"read": override} if override else {},
            }
        },
    )
    request = Mock(return_value={"success": True, "params_patch": {"file_path": "changed.xlsx"}})
    repair = RunRepair(
        repository,
        SimpleNamespace(
            refresh_repair_metadata=Mock(), record_repair_llm_call=Mock(return_value=True)
        ),
        SimpleNamespace(
            repair_enabled=is_llm_repair_enabled,
            repair_limit=lambda *args: 2,
            request_repair=request,
            validate=validate_tool_call,
        ),
    )
    return run, step, repair, request, context


@pytest.mark.parametrize("binding", ["source", "parent"])
def test_frozen_child_cannot_enable_a_second_model_loop(binding):
    run, step, repair, request, context = repair_case(binding)
    assert (
        repair.prepare_repair_or_retry(
            run, step, runtime_context={**context, "llm_repair_enabled": True}
        )
        is False
    )
    assert (
        repair.prepare_llm_repair_or_retry(
            run, step, runtime_context={"repair_policy": {"mode": "auto"}}
        )
        is False
    )
    request.assert_not_called()
    assert step.params == {"file_path": "original.xlsx"}
    assert step.repair_history == []


def test_frozen_child_can_retry_the_exact_same_read_but_cannot_patch_its_request():
    run, step, repair, request, context = repair_case(override={"retry": True})
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is True
    assert step.status == "pending" and run.status == "retrying"
    assert step.params == {"file_path": "original.xlsx"}
    saved = repair.repository.get(run.run_id)
    assert saved.steps[0].params == step.params
    request.assert_not_called()
    run, step, repair, request, context = repair_case(
        override={"params": {"file_path": "other.xlsx"}, "retry": True}
    )
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is False
    assert step.params == {"file_path": "original.xlsx"}
    request.assert_not_called()


@pytest.mark.parametrize(
    "output", [{"outcome": "unknown"}, {"reconciliation_required": True}, {"retryable": False}]
)
def test_uncertain_child_is_not_retried_even_by_deterministic_policy(output):
    run, step, repair, request, context = repair_case(override={"retry": True}, output=output)
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is False
    assert repair.prepare_llm_repair_or_retry(run, step, runtime_context=context) is False
    assert step.status == "failed" and step.repair_history == []
    request.assert_not_called()


def test_existing_native_workflow_repair_contract_is_unchanged():
    run, step, repair, request, context = repair_case(binding="native")
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is True
    request.assert_called_once()
    assert step.params == {"file_path": "changed.xlsx"}
