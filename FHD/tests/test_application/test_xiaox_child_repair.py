"""Frozen Xiaox children retain exact retry identity across repair entry points."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repair import RunRepair
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_spec import validate_tool_call


def repair_case(binding="source", override=None, output=None, runtime_type="xiaox"):
    repository = InMemoryAgentRunRepository()
    parent = AgentRun(user_id="owner", message="read", status="running")
    parent.metadata["runtime_type"] = runtime_type
    repository.save(parent)
    context = (
        {"source": f"{runtime_type}_runtime"}
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
    if binding == "root":
        run.metadata["runtime_type"] = runtime_type
    repair = RunRepair(
        repository,
        SimpleNamespace(refresh_repair_metadata=Mock()),
        SimpleNamespace(
            action_spec=lambda *args: None,
            validate=validate_tool_call,
        ),
    )
    return run, step, repair, context


@pytest.mark.parametrize("binding", ["source", "parent"])
def test_frozen_child_cannot_enable_a_second_model_loop(binding):
    run, step, repair, context = repair_case(binding)
    assert (
        repair.prepare_repair_or_retry(
            run, step, runtime_context={**context, "llm_repair_enabled": True}
        )
        is False
    )
    assert not hasattr(repair, "prepare_llm_repair_or_retry")
    assert step.params == {"file_path": "original.xlsx"}
    assert step.repair_history == []


@pytest.mark.parametrize("runtime_type", ["codex", "xiaox"])
@pytest.mark.parametrize("binding", ["source", "parent", "root"])
def test_frozen_child_can_retry_the_exact_same_read_but_cannot_patch_its_request(
    binding, runtime_type
):
    run, step, repair, context = repair_case(
        binding=binding, runtime_type=runtime_type, override={"retry": True}
    )
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is True
    assert step.status == "pending" and run.status == "retrying"
    assert step.params == {"file_path": "original.xlsx"}
    saved = repair.repository.get(run.run_id)
    assert saved.steps[0].params == step.params
    run, step, repair, context = repair_case(
        binding=binding,
        runtime_type=runtime_type,
        override={"params": {"file_path": "other.xlsx"}, "retry": True},
    )
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is False
    assert step.params == {"file_path": "original.xlsx"}
    assert step.repair_history == []


@pytest.mark.parametrize(
    "output", [{"outcome": "unknown"}, {"reconciliation_required": True}, {"retryable": False}]
)
def test_uncertain_child_is_not_retried_even_by_deterministic_policy(output):
    run, step, repair, context = repair_case(override={"retry": True}, output=output)
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is False
    assert not hasattr(repair, "prepare_llm_repair_or_retry")
    assert step.status == "failed" and step.repair_history == []


def test_formal_workflow_keeps_explicit_validated_repair_policy():
    run, step, repair, context = repair_case(
        binding="formal", override={"params": {"file_path": "changed.xlsx"}, "retry": True}
    )
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is True
    assert step.params == {"file_path": "changed.xlsx"}


def test_formal_workflow_cannot_reactivate_retired_model_repair():
    run, step, repair, context = repair_case(binding="formal")
    assert repair.prepare_repair_or_retry(run, step, runtime_context=context) is False
    assert step.params == {"file_path": "original.xlsx"}
    assert not hasattr(repair, "prepare_llm_repair_or_retry")
