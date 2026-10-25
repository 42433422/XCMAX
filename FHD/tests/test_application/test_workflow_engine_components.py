"""Composition boundaries that must survive workflow engine extraction."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.application.workflow.checkpointer import WorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.engine_decisions import AgentDecisionClient
from app.application.workflow.workflow_types import (
    Branch,
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
)


def _plan(*node_ids):
    return PlanGraph(
        plan_id="boundary",
        intent="component_contract",
        nodes=[
            WorkflowNode(node_id=node_id, tool_id=node_id, action="query", idempotent=True)
            for node_id in node_ids
        ],
    )


@pytest.mark.parametrize("parallel", [False, True])
def test_shared_engine_keeps_overlapping_run_callbacks_isolated(parallel):
    first_entered, second_entered, first_finished = Event(), Event(), Event()
    default_events, first_events, second_events = [], [], []

    def dispatch(tool_id, action, params):
        if tool_id == "first":
            first_entered.set()
            assert second_entered.wait(5)
        elif tool_id == "second":
            second_entered.set()
            assert first_finished.wait(5)
        return {"success": True}

    engine = WorkflowEngine(dispatch, state_event_callback=default_events.append)

    def first_run():
        try:
            return engine.run(
                _plan("first"), parallel=parallel, state_event_callback=first_events.append
            )
        finally:
            first_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_run)
        assert first_entered.wait(5)
        second = executor.submit(
            engine.run,
            _plan("second"),
            parallel=parallel,
            state_event_callback=second_events.append,
        )
        assert first.result(timeout=10).success
        assert second.result(timeout=10).success
    assert engine.run(_plan("default"), parallel=False).success
    assert [event["node_id"] for event in first_events] == ["first"]
    assert [event["node_id"] for event in second_events] == ["second"]
    assert [event["node_id"] for event in default_events] == ["default"]


@pytest.mark.parametrize("parallel", [False, True])
def test_nested_run_inherits_callback_and_restores_explicit_override(parallel):
    default_events, outer_events, inner_events = [], [], []

    def dispatch(tool_id, action, params):
        if tool_id == "outer":
            assert engine.run(_plan("inherited"), parallel=False).success
            assert engine.run(
                _plan("overridden"), parallel=False, state_event_callback=inner_events.append
            ).success
            assert engine.run(_plan("inherited_again"), parallel=False).success
        return {"success": True}

    engine = WorkflowEngine(dispatch, state_event_callback=default_events.append)
    assert engine.run(
        _plan("outer"), parallel=parallel, state_event_callback=outer_events.append
    ).success
    assert engine.run(_plan("default"), parallel=False).success
    assert [event["node_id"] for event in outer_events] == ["inherited", "inherited_again", "outer"]
    assert [event["node_id"] for event in inner_events] == ["overridden"]
    assert [event["node_id"] for event in default_events] == ["default"]


def test_run_restores_callback_after_batch_raises():
    default_events, overridden_events = [], []
    engine = WorkflowEngine(
        lambda **kwargs: {"success": True}, state_event_callback=default_events.append
    )
    with patch.object(engine, "_run_batch", side_effect=RuntimeError("interrupted")):
        with pytest.raises(RuntimeError, match="interrupted"):
            engine.run(_plan("interrupted"), state_event_callback=overridden_events.append)
    assert engine.run(_plan("default"), parallel=False).success
    assert [event["node_id"] for event in default_events] == ["default"]
    assert overridden_events == []


@pytest.mark.parametrize("agentic", [False, True])
def test_retry_parameter_preparation_preserves_execution_mode(agentic):
    observed = []

    def dispatch(tool_id, action, params):
        observed.append(dict(params))
        params["dispatch_marker"] = "retained"
        return {"success": len(observed) == 2, "message": "retry"}

    engine = WorkflowEngine(dispatch)
    context = {"message": "steel"}
    params = {"source": "original"}
    if agentic:
        result = engine._run_single_tool("products", "query", params, context, max_retries=1)
    else:
        node = WorkflowNode("planned", "products", "query", params=params)
        result = engine._run_node(node, context, max_retries=1)
    assert result.success
    assert result.retries == 1
    assert result.node_id == ("agent_products_query" if agentic else "planned")
    assert result.params == params == {"source": "original"}
    assert [attempt["success"] for attempt in result.attempts] == [False, True]
    assert all(attempt["_runtime_context"] is context for attempt in observed)
    assert ("dispatch_marker" in observed[1]) is agentic
    assert ("keyword" in observed[0]) is (not agentic)


@pytest.mark.parametrize("agentic", [False, True])
def test_retry_keeps_last_output_and_propagates_programming_errors(agentic):
    failure = {"success": False, "requires_token": True, "token_name": "RETRY_TOKEN"}
    engine = WorkflowEngine(lambda **kwargs: failure)

    def execute():
        if agentic:
            return engine._run_single_tool("products", "query", {}, {}, max_retries=1)
        return engine._run_node(WorkflowNode("planned", "products", "query"), {}, max_retries=1)

    with patch.object(engine, "_dispatch", side_effect=[failure, RuntimeError("offline")]):
        result = execute()
    assert not result.success
    assert result.output is failure
    assert result.error == "offline"
    assert result.retries == 1
    assert len(result.attempts) == 2
    assert "RETRY_TOKEN" in result.recovery_hint
    with patch.object(engine, "_dispatch", side_effect=TypeError("programming error")):
        with pytest.raises(TypeError, match="programming error"):
            execute()


def test_clarification_policy_is_only_applied_to_planned_nodes():
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    engine = WorkflowEngine(dispatch)
    node = WorkflowNode("approval", "clarify", "confirm", risk="high", params={"question": "OK?"})
    result = engine._run_node(node, {})
    assert calls == []
    assert result.action == "ask"
    assert result.retryable
    assert result.output["requires_confirmation"]
    direct = engine._run_single_tool("clarify", "confirm", node.params, {}, 0, retryable=False)
    assert len(calls) == 1
    assert direct.action == "confirm"
    assert not direct.retryable


@pytest.mark.parametrize("on_class", [False, True])
def test_scheduler_resolves_node_hook_after_engine_construction(on_class):
    engine = WorkflowEngine(lambda **kwargs: pytest.fail("dispatcher must not run"))
    replacement = NodeExecutionResult("patched", True, "patched", "query", output={"success": True})
    with patch.object(
        WorkflowEngine if on_class else engine, "_run_node", return_value=replacement
    ):
        result = engine.run(_plan("patched"))
    assert result.success
    assert result.node_results == [replacement]
    assert result.final_context["node_outputs"]["patched"] == {"success": True}


def test_public_branch_policy_and_state_hooks_remain_replaceable():
    engine = WorkflowEngine(lambda **kwargs: {"success": True, "route": "original"})
    plan = _plan("router", "original", "alternative")
    plan.nodes[0].branches = [
        Branch("original", {"key": "route", "equals": "original"}),
        Branch("alternative", {"key": "route", "equals": "alternative"}),
    ]
    with (
        patch.object(WorkflowEngine, "evaluate_branch", return_value="alternative"),
        patch.object(engine, "_append_node_trace", wraps=engine._append_node_trace) as append_trace,
        patch.object(
            engine, "_merge_state_schema", wraps=engine._merge_state_schema
        ) as merge_schema,
    ):
        result = engine.run(plan)
    assert result.success
    assert [node.node_id for node in result.node_results] == ["router", "alternative"]
    assert append_trace.call_count == merge_schema.call_count == 2


def test_partial_read_failure_checkpoints_progress_then_resume_uses_default_events():
    calls, default_events, run_events = [], [], []
    should_fail = True

    def dispatch(tool_id, action, params):
        calls.append(tool_id)
        return {"success": not (tool_id == "retry" and should_fail), "message": tool_id}

    engine = WorkflowEngine(dispatch, state_event_callback=default_events.append)
    plan = _plan("read", "retry", "write")
    plan.nodes[-1].depends_on = ["read", "retry"]
    plan.nodes[-1].risk = "high"
    plan.nodes[-1].idempotent = False
    store = WorkflowCheckpointer()
    failed = engine.run(
        plan, max_retries=0, checkpointer=store, state_event_callback=run_events.append
    )
    assert not failed.success
    assert set(calls) == {"read", "retry"}
    assert [result.node_id for result in failed.node_results] == ["read", "retry"]
    checkpoint = store.latest_checkpoint(plan.plan_id)
    assert checkpoint["executed_nodes"] == ["read"]
    assert [event["node_id"] for event in run_events] == ["read", "retry"]
    assert default_events == []

    should_fail = False
    resumed = engine.resume_run(plan, checkpoint["checkpoint_id"], checkpointer=store)
    assert resumed.success
    assert [result.node_id for result in resumed.node_results] == ["retry", "write"]
    assert calls.count("read") == 1
    assert [event["node_id"] for event in default_events] == ["retry", "write"]
    assert [trace["node_id"] for trace in resumed.final_context["workflow_trace"]] == [
        "read",
        "retry",
        "retry",
        "write",
    ]
    calls_before_replay = list(calls)
    replayed = engine.replay_run(plan.plan_id, checkpointer=store)
    assert replayed.success
    assert calls == calls_before_replay
    assert [event["node_id"] for event in default_events] == ["retry", "write"]


def test_incomplete_router_checkpoint_never_guesses_a_write_branch():
    store = WorkflowCheckpointer()
    plan = _plan("router", "write")
    plan.nodes[0].next = "write"
    plan.nodes[1].risk = "high"
    checkpoint_id = store.save_checkpoint(plan.plan_id, 1, {}, ["router"])
    engine = WorkflowEngine(lambda **kwargs: pytest.fail("incomplete router must block dispatch"))
    result = engine.resume_run(plan, checkpoint_id, checkpointer=store)
    assert not result.success
    assert result.node_results == []
    assert result.final_context["workflow_status"]["state"] == "blocked"
    assert result.final_context["workflow_status"]["unresolved_nodes"] == ["write"]


def test_decision_component_uses_injected_factories_without_a_workflow_engine():
    requests = []
    settings = SimpleNamespace(
        api_key="initial", api_url="https://model.invalid/chat", model="test"
    )

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"execute","tool_id":"products","action_name":"query","params":{"keyword":"steel"}}'
                        }
                    }
                ]
            },
        )

    decision = AgentDecisionClient(
        lambda: settings, lambda: SimpleNamespace(post=post), SimpleNamespace(warning=pytest.fail)
    )
    result = decision.decide("find steel", {}, {}, [], None)
    assert result == {
        "action": "execute",
        "tool_id": "products",
        "action_name": "query",
        "params": {"keyword": "steel"},
        "reasoning": "",
    }
    settings.api_key = "refreshed"
    assert decision.decide("find steel", {}, {}, [], None) == result
    assert [request[1]["headers"]["Authorization"] for request in requests] == [
        "Bearer initial",
        "Bearer refreshed",
    ]
