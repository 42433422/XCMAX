from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    LLMCall,
    ToolCall,
)
from app.application.workflow.types import PlanGraph, WorkflowNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(user_id: str = "u1", message: str = "hello") -> AgentRun:
    run = AgentRun(user_id=user_id, message=message)
    run.metadata.setdefault("cost_units_total", 0)
    run.metadata.setdefault("ai_cost_units_total", 0)
    return run


def _make_step(
    node_id: str = "n1",
    tool_id: str = "tool_a",
    action: str = "run",
    *,
    risk: str = "low",
    idempotent: bool = True,
    status: str = "pending",
    depends_on: list[str] | None = None,
) -> AgentStep:
    step = AgentStep(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        risk=risk,
        idempotent=idempotent,
        status=status,  # type: ignore[arg-type]
        depends_on=depends_on or [],
    )
    return step


def _make_plan(nodes: list[WorkflowNode] | None = None, plan_id: str = "p1") -> PlanGraph:
    return PlanGraph(
        plan_id=plan_id,
        intent="test intent",
        nodes=nodes or [],
        metadata={},
    )


def _make_orchestrator(repo: MagicMock | None = None, executor: MagicMock | None = None):
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    repo = repo or MagicMock()
    executor = executor or MagicMock()
    repo.save.side_effect = lambda run: run  # return the run unchanged
    return AgentOrchestrator(repository=repo, tool_executor=executor), repo, executor


# ---------------------------------------------------------------------------
# Line 65: start_run with auto_execute=False skips _execute_ready_steps
# ---------------------------------------------------------------------------


@patch("app.application.agent_orchestrator.orchestrator.apply_ai_budget_metadata")
@patch("app.application.agent_orchestrator.orchestrator.AgentToolExecutor")
def test_start_run_auto_execute_false_skips_execution(mock_exec_cls, mock_budget):
    """auto_execute=False must not call _execute_ready_steps (line 65 branch)."""
    orch, repo, executor = _make_orchestrator()

    plan = _make_plan()
    with (
        patch.object(orch, "_plan", return_value=plan),
        patch.object(orch, "_apply_plan"),
        patch.object(orch, "_execute_ready_steps") as mock_exec_steps,
    ):
        orch.start_run(user_id="u1", message="msg", auto_execute=False)
        mock_exec_steps.assert_not_called()


# ---------------------------------------------------------------------------
# Line 100: start_run_from_plan with auto_execute=False
# ---------------------------------------------------------------------------


@patch("app.application.agent_orchestrator.orchestrator.apply_ai_budget_metadata")
def test_start_run_from_plan_auto_execute_false(mock_budget):
    """auto_execute=False in start_run_from_plan skips _execute_ready_steps (line 100)."""
    orch, repo, executor = _make_orchestrator()
    plan = _make_plan()
    with (
        patch.object(orch, "_apply_plan"),
        patch.object(orch, "_execute_ready_steps") as mock_exec_steps,
    ):
        orch.start_run_from_plan(user_id="u1", message="msg", plan=plan, auto_execute=False)
        mock_exec_steps.assert_not_called()


# ---------------------------------------------------------------------------
# Line 121-122: continue_run when run is None
# ---------------------------------------------------------------------------


def test_continue_run_run_not_found_returns_none():
    """continue_run returns None when run not found (lines 121-122)."""
    orch, repo, _ = _make_orchestrator()
    repo.get.return_value = None

    result = orch.continue_run("nonexistent_run_id")
    assert result is None


# ---------------------------------------------------------------------------
# Line 125-126: continue_run when no waiting step found
# ---------------------------------------------------------------------------


@patch("app.application.agent_orchestrator.orchestrator.apply_ai_budget_metadata")
def test_continue_run_no_waiting_step(mock_budget):
    """continue_run emits run.continue_ignored when no waiting step (lines 125-126)."""
    orch, repo, _ = _make_orchestrator()
    run = _make_run()
    run.steps = [_make_step(status="completed")]
    repo.get.return_value = run

    result = orch.continue_run(run.run_id, approved_step_id="")
    assert result is not None
    event_types = [e.event_type for e in result.events]
    assert "run.continue_ignored" in event_types


# ---------------------------------------------------------------------------
# Line 222-223: _apply_plan when run.steps is empty → "blocked"
# ---------------------------------------------------------------------------


def test_apply_plan_empty_nodes_sets_blocked():
    """_apply_plan with no nodes sets status=blocked and adds planner.blocked event (lines 222-223)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    plan = _make_plan(nodes=[])

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_tool_action_spec",
            return_value=None,
        ),
        patch("app.application.agent_orchestrator.orchestrator.ingest_artifact_to_dataset"),
    ):
        orch._apply_plan(run, plan)

    assert run.status == "blocked"
    assert run.error != ""
    event_types = [e.event_type for e in run.events]
    assert "planner.blocked" in event_types


# ---------------------------------------------------------------------------
# Lines 247-253: _find_waiting_step — status != "waiting_user" (248-249)
#                and wanted but not matched (250-251)
# ---------------------------------------------------------------------------


def test_find_waiting_step_status_not_waiting_user_skipped():
    """Steps with status != 'waiting_user' are skipped (lines 248-249)."""
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    run = _make_run()
    step = _make_step(node_id="n1", status="pending")
    run.steps = [step]

    result = AgentOrchestrator._find_waiting_step(run, approved_step_id="")
    assert result is None


def test_find_waiting_step_wanted_not_matched():
    """When wanted is set but doesn't match step_id or node_id, skip (lines 250-251)."""
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    run = _make_run()
    step = _make_step(node_id="n1", status="waiting_user")
    run.steps = [step]

    # Request a specific step_id that doesn't match anything
    result = AgentOrchestrator._find_waiting_step(run, approved_step_id="no_such_id")
    assert result is None


def test_find_waiting_step_wanted_matches_node_id():
    """When wanted matches node_id, returns the step (line 252)."""
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    run = _make_run()
    step = _make_step(node_id="n1", status="waiting_user")
    run.steps = [step]

    result = AgentOrchestrator._find_waiting_step(run, approved_step_id="n1")
    assert result is step


# ---------------------------------------------------------------------------
# Line 273-274: _execute_ready_steps skips already completed steps
# ---------------------------------------------------------------------------


def test_execute_ready_steps_skips_completed_step():
    """Completed steps are skipped in _execute_ready_steps (lines 273-274)."""
    orch, repo, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(status="completed")
    run.steps = [step]
    run.metadata["cost_units_total"] = 0
    run.metadata["ai_cost_units_total"] = 0

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.budget_exceeded_payload",
            return_value=None,
        ),
        patch("app.application.agent_orchestrator.orchestrator.refresh_ai_budget_metadata"),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_tool_action_spec",
            return_value=None,
        ),
    ):
        orch._execute_ready_steps(run, runtime_context={})

    assert run.status == "completed"


# ---------------------------------------------------------------------------
# Line 275-276: step blocked due to unsatisfied dependencies
# ---------------------------------------------------------------------------


def test_execute_ready_steps_blocks_on_unmet_dependency():
    """Step with unmet dependency is skipped and run set to blocked (lines 275-276)."""
    orch, repo, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(node_id="n2", depends_on=["n1"])
    run.steps = [step]
    run.metadata["cost_units_total"] = 0
    run.metadata["ai_cost_units_total"] = 0

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.budget_exceeded_payload",
            return_value=None,
        ),
        patch("app.application.agent_orchestrator.orchestrator.refresh_ai_budget_metadata"),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_tool_action_spec",
            return_value=None,
        ),
    ):
        orch._execute_ready_steps(run, runtime_context={})

    assert run.status == "blocked"
    assert step.status == "skipped"


# ---------------------------------------------------------------------------
# Line 500-501: _record_tool_usage_entry when cost_units <= 0
# ---------------------------------------------------------------------------


def test_record_tool_usage_entry_zero_cost_units_skips_billing():
    """cost_units<=0 sets usage_ledger to 'not_required' and returns True (lines 500-501)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    tool_call = ToolCall(step_id="s1", node_id="n1", tool_id="tool_a", action="run", cost_units=0)
    result = orch._record_tool_usage_entry(run, tool_call)
    assert result is True
    assert tool_call.metadata["usage_ledger"]["status"] == "not_required"


# ---------------------------------------------------------------------------
# Line 503-504: _record_tool_usage_entry when usage_ledger already set
# ---------------------------------------------------------------------------


def test_record_tool_usage_entry_already_set_returns_true():
    """If usage_ledger is already a dict, return True immediately (lines 503-504)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    tool_call = ToolCall(step_id="s1", node_id="n1", tool_id="tool_a", action="run", cost_units=5)
    tool_call.metadata["usage_ledger"] = {"status": "recorded", "usage_id": "uid_1"}
    result = orch._record_tool_usage_entry(run, tool_call)
    assert result is True


# ---------------------------------------------------------------------------
# Lines 552-554: wallet_debit is truthy → set metadata
# ---------------------------------------------------------------------------


def test_record_tool_usage_entry_wallet_debit_set_in_metadata():
    """When wallet_debit is truthy dict, it is stored in tool_call.metadata (lines 552-554)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    tool_call = ToolCall(step_id="s1", node_id="n1", tool_id="tool_a", action="run", cost_units=3)
    wallet_debit_data = {"amount": 3, "status": "debited"}
    fake_entry = {
        "usage_id": "uid_1",
        "usage_key": "key_1",
        "entry_type": "tool_call",
        "billing_status": "debited",
        "billing_source": "wallet",
        "cost_units": 3,
        "wallet_debit": wallet_debit_data,
    }
    billing_mod = MagicMock()
    billing_mod.record_tool_usage = MagicMock(return_value=fake_entry)
    with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": billing_mod}):
        result = orch._record_tool_usage_entry(run, tool_call)

    assert result is True
    assert tool_call.metadata.get("wallet_debit") == wallet_debit_data


# ---------------------------------------------------------------------------
# Line 580-581: billing_status == "insufficient_balance"
# ---------------------------------------------------------------------------


def test_record_tool_usage_entry_insufficient_balance_returns_false():
    """insufficient_balance billing_status marks run failed and returns False (lines 580-581)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    tool_call = ToolCall(step_id="s1", node_id="n1", tool_id="tool_a", action="run", cost_units=5)
    fake_entry = {
        "usage_id": "uid_1",
        "usage_key": "key_1",
        "entry_type": "tool_call",
        "billing_status": "insufficient_balance",
        "billing_source": "wallet",
        "cost_units": 5,
        "wallet_debit": {},
    }
    billing_mod = MagicMock()
    billing_mod.record_tool_usage = MagicMock(return_value=fake_entry)
    with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": billing_mod}):
        result = orch._record_tool_usage_entry(run, tool_call)

    assert result is False
    assert run.status == "failed"


# ---------------------------------------------------------------------------
# Line 626-627: refund dict is empty → early return
# ---------------------------------------------------------------------------


def test_record_tool_usage_refund_empty_refund_returns_early():
    """When refund entry is empty dict, method returns early (lines 626-627)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    tool_call = ToolCall(step_id="s1", node_id="n1", tool_id="tool_a", action="run", cost_units=5)
    tool_call.metadata["usage_ledger"] = {"usage_key": "key_1", "status": "recorded"}
    fake_entry = {"refund": {}}
    billing_mod = MagicMock()
    billing_mod.refund_tool_usage = MagicMock(return_value=fake_entry)
    with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": billing_mod}):
        orch._record_tool_usage_refund(run, tool_call, reason="failed")

    # No wallet_refund set (because refund was empty)
    assert "wallet_refund" not in tool_call.metadata


# ---------------------------------------------------------------------------
# Lines 837-841: _params_patch_from_repair picks first matching key
# ---------------------------------------------------------------------------


def test_params_patch_from_repair_uses_params_key():
    """'params' key is tried first and returned (lines 837-841)."""
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    override = {"params": {"x": 1}, "set_params": {"y": 2}}
    result = AgentOrchestrator._params_patch_from_repair(override)
    assert result == {"x": 1}


def test_params_patch_from_repair_falls_back_to_patch_params():
    """Falls back to 'patch_params' when 'params'/'set_params' absent (lines 839-841)."""
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    override = {"patch_params": {"z": 3}}
    result = AgentOrchestrator._params_patch_from_repair(override)
    assert result == {"z": 3}


def test_params_patch_from_repair_returns_empty_when_no_key():
    """Returns empty dict when no recognized key found (line 841)."""
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    result = AgentOrchestrator._params_patch_from_repair({"retry": True})
    assert result == {}


# ---------------------------------------------------------------------------
# Line 857-858: _prepare_repair_or_retry when billing_blocked
# ---------------------------------------------------------------------------


def test_prepare_repair_or_retry_billing_blocked_returns_false():
    """error_code=='tool_billing_blocked' causes immediate False return (lines 857-858)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(risk="low", idempotent=True)
    step.output = {"error_code": "tool_billing_blocked"}
    result = orch._prepare_repair_or_retry(run, step, runtime_context={})
    assert result is False


# ---------------------------------------------------------------------------
# Line 864-865: _prepare_repair_or_retry when not can_auto_execute
# ---------------------------------------------------------------------------


def test_prepare_repair_or_retry_not_auto_executable_returns_false():
    """Non-auto-executable step returns False (lines 864-865)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(risk="high", idempotent=False)
    step.output = {"error_code": "some_error"}
    result = orch._prepare_repair_or_retry(run, step, runtime_context={})
    assert result is False


# ---------------------------------------------------------------------------
# Line 871-872: repair limit exceeded
# ---------------------------------------------------------------------------


def test_prepare_repair_or_retry_limit_exceeded_returns_false():
    """Repair limit exceeded → returns False (lines 871-872)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    run.metadata["plan"] = {
        "metadata": {"repair_overrides": {"n1": {"max_attempts": 1, "params": {"k": "v"}}}}
    }
    step = _make_step(node_id="n1", risk="low", idempotent=True)
    step.output = {"error_code": "some_error"}
    step.max_repair_attempts = 1
    # Already one repair attempt → limit reached
    step.repair_history.append({"attempt_count": 1})

    result = orch._prepare_repair_or_retry(run, step, runtime_context={})
    assert result is False


# ---------------------------------------------------------------------------
# Line 939-940: _prepare_llm_repair_or_retry when LLM repair disabled
# ---------------------------------------------------------------------------


def test_prepare_llm_repair_or_retry_llm_disabled_returns_false():
    """is_llm_repair_enabled=False → returns False immediately (lines 939-940)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(risk="low", idempotent=True)

    with patch(
        "app.application.agent_orchestrator.orchestrator.is_llm_repair_enabled",
        return_value=False,
    ):
        result = orch._prepare_llm_repair_or_retry(run, step, runtime_context={})
    assert result is False


# ---------------------------------------------------------------------------
# Line 968-969: _record_repair_llm_call when LLM call failed
# (request_llm_repair raises → returns False)
# ---------------------------------------------------------------------------


def test_prepare_llm_repair_or_retry_request_fails_returns_false():
    """When request_llm_repair raises, event is emitted and False returned (lines 968-969)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(risk="low", idempotent=True)
    step.max_repair_attempts = 2

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.is_llm_repair_enabled",
            return_value=True,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.llm_repair_attempt_limit",
            return_value=2,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.request_llm_repair",
            side_effect=RuntimeError("LLM timeout"),
        ),
    ):
        result = orch._prepare_llm_repair_or_retry(run, step, runtime_context={})

    assert result is False
    event_types = [e.event_type for e in run.events]
    assert "step.llm_repair_failed" in event_types


# ---------------------------------------------------------------------------
# Line 983-984: params_patch empty after LLM success → returns False
# ---------------------------------------------------------------------------


def test_prepare_llm_repair_params_patch_empty_returns_false():
    """Empty params_patch after advice.success returns False (lines 983-984)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(risk="low", idempotent=True)
    step.max_repair_attempts = 2

    advice = {"success": True, "params_patch": {}, "llm_call": None}

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.is_llm_repair_enabled",
            return_value=True,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.llm_repair_attempt_limit",
            return_value=2,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.request_llm_repair",
            return_value=advice,
        ),
        patch.object(orch, "_record_repair_llm_call", return_value=True),
    ):
        result = orch._prepare_llm_repair_or_retry(run, step, runtime_context={})

    assert result is False


# ---------------------------------------------------------------------------
# Line 989-990: validation fails after params_patch
# ---------------------------------------------------------------------------


def test_prepare_llm_repair_validation_fails_returns_false():
    """Validation failure after params_patch returns False (lines 989-990)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(node_id="n1", tool_id="tool_a", action="run", risk="low", idempotent=True)
    step.params = {"a": 1}
    step.max_repair_attempts = 2

    advice = {"success": True, "params_patch": {"b": 2}, "llm_call": None}
    bad_validation = MagicMock(ok=False, error_code="invalid_param", message="bad param")

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.is_llm_repair_enabled",
            return_value=True,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.llm_repair_attempt_limit",
            return_value=2,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.request_llm_repair",
            return_value=advice,
        ),
        patch.object(orch, "_record_repair_llm_call", return_value=True),
        patch(
            "app.application.agent_orchestrator.orchestrator.validate_tool_call",
            return_value=bad_validation,
        ),
    ):
        result = orch._prepare_llm_repair_or_retry(run, step, runtime_context={})

    assert result is False
    event_types = [e.event_type for e in run.events]
    assert "step.repair_rejected" in event_types


# ---------------------------------------------------------------------------
# Line 1004-1005: params unchanged after patch → returns False
# ---------------------------------------------------------------------------


def test_prepare_llm_repair_params_unchanged_returns_false():
    """When next_params == previous_params, returns False (lines 1004-1005)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step(node_id="n1", tool_id="tool_a", action="run", risk="low", idempotent=True)
    step.params = {"a": 1}
    step.max_repair_attempts = 2

    # params_patch that doesn't change anything
    advice = {"success": True, "params_patch": {"a": 1}, "llm_call": None}
    good_validation = MagicMock(ok=True)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.is_llm_repair_enabled",
            return_value=True,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.llm_repair_attempt_limit",
            return_value=2,
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.request_llm_repair",
            return_value=advice,
        ),
        patch.object(orch, "_record_repair_llm_call", return_value=True),
        patch(
            "app.application.agent_orchestrator.orchestrator.validate_tool_call",
            return_value=good_validation,
        ),
    ):
        result = orch._prepare_llm_repair_or_retry(run, step, runtime_context={})

    assert result is False


# ---------------------------------------------------------------------------
# Line 1060-1061: _record_repair_llm_call when call is not LLMCall → returns True
# ---------------------------------------------------------------------------


def test_record_repair_llm_call_no_llm_call_returns_true():
    """advice without LLMCall instance returns True (lines 1060-1061)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step()

    advice = {"llm_call": None, "success": True}
    result = orch._record_repair_llm_call(run, step, advice)
    assert result is True


def test_record_repair_llm_call_non_llmcall_object_returns_true():
    """Non-LLMCall object in advice returns True (lines 1060-1061)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    step = _make_step()

    advice = {"llm_call": {"not": "a real llm call"}, "success": True}
    result = orch._record_repair_llm_call(run, step, advice)
    assert result is True


# ---------------------------------------------------------------------------
# Line 1085-1086: _record_repair_llm_call when call.status == "failed" → False
# ---------------------------------------------------------------------------


def test_record_repair_llm_call_failed_status_returns_false():
    """LLMCall with status='failed' causes _record_repair_llm_call to return False (lines 1085-1086)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    run.metadata["cost_units_total"] = 0
    run.metadata["ai_cost_units_total"] = 0
    step = _make_step()

    llm_call = LLMCall(
        provider_id="test_provider",
        provider="openai",
        model="gpt-4",
        status="failed",
        cost_units=0,
    )
    advice = {"llm_call": llm_call}

    with (
        patch("app.application.agent_orchestrator.orchestrator.refresh_ai_budget_metadata"),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_tool_action_spec",
            return_value=None,
        ),
    ):
        result = orch._record_repair_llm_call(run, step, advice)

    assert result is False


# ---------------------------------------------------------------------------
# Line 1170-1174: _refresh_llm_metadata when llm_calls not empty
# ---------------------------------------------------------------------------


def test_refresh_llm_metadata_with_llm_calls():
    """_refresh_llm_metadata populates llm_provider and llm_model when calls exist (lines 1170-1174)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()
    run.metadata["cost_units_total"] = 0
    run.metadata["ai_cost_units_total"] = 0
    call = LLMCall(
        provider_id="prov_1",
        provider="openai",
        model="gpt-4o",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_units=3,
    )
    run.llm_calls.append(call)

    with (
        patch("app.application.agent_orchestrator.orchestrator.refresh_ai_budget_metadata"),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_tool_action_spec",
            return_value=None,
        ),
    ):
        orch._refresh_llm_metadata(run)

    assert run.metadata["llm_provider"] == "openai"
    assert run.metadata["llm_model"] == "gpt-4o"
    assert run.metadata["llm_call_count"] == 1
    assert run.metadata["llm_cost_units_total"] == 3


# ---------------------------------------------------------------------------
# Line 1225-1226: _attach_artifacts_from_payload when artifacts is a dict
# ---------------------------------------------------------------------------


def test_attach_artifacts_from_payload_dict_artifact():
    """A dict 'artifacts' value is treated as a single artifact (lines 1225-1226)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()

    payload = {
        "artifacts": {"artifact_type": "image", "name": "photo.png", "uri": "s3://bucket/photo"}
    }

    with patch("app.application.agent_orchestrator.orchestrator.ingest_artifact_to_dataset"):
        orch._attach_artifacts_from_payload(run, payload, source="test")

    assert len(run.artifacts) == 1
    assert run.artifacts[0].artifact_type == "image"


# ---------------------------------------------------------------------------
# Line 1234-1235: artifact.artifact_type is empty → skip
# ---------------------------------------------------------------------------


def test_attach_artifacts_from_payload_empty_artifact_type_skipped():
    """Artifacts without artifact_type are skipped (lines 1234-1235)."""
    orch, _, _ = _make_orchestrator()
    run = _make_run()

    payload = {
        "artifacts": [
            {"artifact_type": "", "name": "empty.txt"},
            {"artifact_type": "document", "name": "valid.pdf"},
        ]
    }

    with patch("app.application.agent_orchestrator.orchestrator.ingest_artifact_to_dataset"):
        orch._attach_artifacts_from_payload(run, payload, source="test")

    assert len(run.artifacts) == 1
    assert run.artifacts[0].artifact_type == "document"
