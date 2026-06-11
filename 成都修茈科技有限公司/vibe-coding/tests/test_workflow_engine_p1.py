"""Tests for P1 workflow engine features: conditions, retries, hooks, skips."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from vibe_coding import MockLLM
from vibe_coding.code_factory import NLCodeSkillFactory
from vibe_coding.runtime import CodeSkillRuntime, JsonCodeSkillStore
from vibe_coding.workflow_engine import (
    NodeRunOutcome,
    RunOptions,
    VibeWorkflowEngine,
)
from vibe_coding.workflow_factory import NLWorkflowFactory
from vibe_coding.workflow_models import (
    VibeWorkflowEdge,
    VibeWorkflowGraph,
    VibeWorkflowNode,
)


# ------------------------------------------------------------------ helpers


def _identity_skill_spec(skill_id: str, fn: str) -> str:
    return json.dumps(
        {
            "skill_id": skill_id,
            "name": skill_id,
            "domain": "",
            "function_name": fn,
            "purpose": "demo",
            "signature": {"params": ["x"], "return_type": "dict", "required_params": ["x"]},
            "dependencies": [],
            "test_cases": [
                {"case_id": "h", "input_data": {"x": 1}, "expected_output": {"value": 1}}
            ],
            "quality_gate": {"required_keys": ["value"]},
            "domain_keywords": [],
        }
    )


def _identity_code(fn: str) -> str:
    return json.dumps(
        {"source_code": f"def {fn}(x):\n    return {{'value': x}}\n"}
    )


def _build_skill(store: JsonCodeSkillStore, llm: MockLLM, skill_id: str, fn: str) -> str:
    NLCodeSkillFactory(llm, store).generate("brief", skill_id=skill_id)
    return store.list_code_skills()[-1].skill_id


def _two_node_graph_with_condition(condition: str) -> VibeWorkflowGraph:
    return VibeWorkflowGraph(
        workflow_id="cond-wf",
        nodes=[
            VibeWorkflowNode(node_id="start", node_type="start"),
            VibeWorkflowNode(
                node_id="n1",
                node_type="eskill",
                layer="code",
                code_skill_ref="skill-a",
                config={"input_mapping": {"x": "x"}, "output_var": "n1_out"},
            ),
            VibeWorkflowNode(
                node_id="n2",
                node_type="eskill",
                layer="code",
                code_skill_ref="skill-b",
                config={"input_mapping": {"x": "n1_out.value"}, "output_var": "n2_out"},
            ),
            VibeWorkflowNode(node_id="end", node_type="end"),
        ],
        edges=[
            VibeWorkflowEdge(source_node_id="start", target_node_id="n1"),
            VibeWorkflowEdge(source_node_id="n1", target_node_id="n2", condition=condition),
            VibeWorkflowEdge(source_node_id="n2", target_node_id="end"),
            # Add a fallback edge from n1 directly to end so end stays reachable
            # when the n1->n2 edge is skipped.
            VibeWorkflowEdge(source_node_id="n1", target_node_id="end"),
        ],
    )


def _make_runtime(tmp_path) -> tuple[CodeSkillRuntime, JsonCodeSkillStore, MockLLM]:
    store = JsonCodeSkillStore(tmp_path / "code.json")
    llm = MockLLM(
        [
            _identity_skill_spec("skill-a", "fa"),
            _identity_code("fa"),
            _identity_skill_spec("skill-b", "fb"),
            _identity_code("fb"),
        ]
    )
    _build_skill(store, llm, "skill-a", "fa")
    _build_skill(store, llm, "skill-b", "fb")
    runtime = CodeSkillRuntime(store)
    return runtime, store, llm


# ------------------------------------------------------------------ tests


def test_edge_condition_true_runs_downstream(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)
    graph = _two_node_graph_with_condition("n1_out.value > 0")
    engine = VibeWorkflowEngine(code_runtime=runtime)
    result = engine.run(graph, {"x": 1})
    assert result.success, result.error
    n2_outcome = next(o for o in result.outcomes if o.node_id == "n2")
    assert n2_outcome.stage != "skipped"


def test_edge_condition_false_skips_downstream(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)
    graph = _two_node_graph_with_condition("n1_out.value > 999")
    engine = VibeWorkflowEngine(code_runtime=runtime)
    result = engine.run(graph, {"x": 1})
    assert result.success, result.error  # End is reachable via the unconditional fallback edge.
    n2_outcome = next(o for o in result.outcomes if o.node_id == "n2")
    assert n2_outcome.stage == "skipped"
    assert "no active incoming" in n2_outcome.skipped_reason


def test_invalid_condition_treated_as_false(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)
    # Reference an undefined name → ConditionError → edge inactive
    graph = _two_node_graph_with_condition("undefined_name == 'x'")
    engine = VibeWorkflowEngine(code_runtime=runtime)
    result = engine.run(graph, {"x": 1})
    n2_outcome = next(o for o in result.outcomes if o.node_id == "n2")
    assert n2_outcome.stage == "skipped"


def test_retry_count_reattempts_on_failure(tmp_path) -> None:
    """Configure a node to fail the first call but succeed on retry."""
    store = JsonCodeSkillStore(tmp_path / "code.json")
    llm = MockLLM([_identity_skill_spec("flaky", "fn"), _identity_code("fn")])
    NLCodeSkillFactory(llm, store).generate("brief", skill_id="flaky")

    runtime = CodeSkillRuntime(store)
    engine = VibeWorkflowEngine(code_runtime=runtime)

    # Capture call count via monkeypatch on runtime.run
    call_log: list[int] = []
    original_run = runtime.run

    def flaky_run(*args, **kwargs):
        call_log.append(1)
        if len(call_log) == 1:
            raise RuntimeError("transient")
        return original_run(*args, **kwargs)

    runtime.run = flaky_run  # type: ignore[assignment]

    graph = VibeWorkflowGraph(
        workflow_id="retry-wf",
        nodes=[
            VibeWorkflowNode(node_id="start", node_type="start"),
            VibeWorkflowNode(
                node_id="n1",
                node_type="eskill",
                layer="code",
                code_skill_ref="flaky",
                config={"retry_count": 2, "retry_backoff_s": 0.0, "input_mapping": {"x": "x"}, "output_var": "n1_out"},
            ),
            VibeWorkflowNode(node_id="end", node_type="end"),
        ],
        edges=[
            VibeWorkflowEdge(source_node_id="start", target_node_id="n1"),
            VibeWorkflowEdge(source_node_id="n1", target_node_id="end"),
        ],
    )
    result = engine.run(graph, {"x": 1})
    assert result.success, result.error
    n1 = next(o for o in result.outcomes if o.node_id == "n1")
    assert n1.attempts == 2
    assert n1.error == ""


def test_per_node_timeout(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)

    def slow_run(*args, **kwargs):
        time.sleep(2.0)
        return None

    runtime.run = slow_run  # type: ignore[assignment]

    engine = VibeWorkflowEngine(code_runtime=runtime)
    graph = VibeWorkflowGraph(
        workflow_id="timeout-wf",
        nodes=[
            VibeWorkflowNode(node_id="start", node_type="start"),
            VibeWorkflowNode(
                node_id="n1",
                node_type="eskill",
                layer="code",
                code_skill_ref="skill-a",
                config={"timeout_s": 0.2, "input_mapping": {"x": "x"}, "output_var": "n1_out"},
            ),
            VibeWorkflowNode(node_id="end", node_type="end"),
        ],
        edges=[
            VibeWorkflowEdge(source_node_id="start", target_node_id="n1"),
            VibeWorkflowEdge(source_node_id="n1", target_node_id="end"),
        ],
    )
    result = engine.run(graph, {"x": 1})
    assert not result.success
    assert "timeout" in result.error.lower()


def test_hooks_called_in_order(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)
    graph = _two_node_graph_with_condition("")
    engine = VibeWorkflowEngine(code_runtime=runtime)
    events: list[tuple[str, str]] = []

    def on_start(node, _outcome, _ctx):
        events.append(("start", node.node_id))

    def on_complete(node, outcome, _ctx):
        events.append(("complete", node.node_id))
        assert isinstance(outcome, NodeRunOutcome)

    result = engine.run(
        graph,
        {"x": 1},
        options=RunOptions(on_node_start=on_start, on_node_complete=on_complete),
    )
    assert result.success
    # Both n1 and n2 fire start+complete
    assert ("start", "n1") in events
    assert ("complete", "n1") in events
    assert ("start", "n2") in events
    assert ("complete", "n2") in events


def test_skip_hook_fires_when_condition_false(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)
    graph = _two_node_graph_with_condition("False")
    engine = VibeWorkflowEngine(code_runtime=runtime)
    skipped: list[str] = []

    def on_skip(node, _outcome, _ctx):
        skipped.append(node.node_id)

    engine.run(graph, {"x": 1}, options=RunOptions(on_node_skip=on_skip))
    assert "n2" in skipped


def test_fail_fast_off_continues_past_failure(tmp_path) -> None:
    runtime, _, _ = _make_runtime(tmp_path)

    call_log: list[str] = []
    original_run = runtime.run

    def selective_run(skill_id: str, *args, **kwargs):
        call_log.append(skill_id)
        if skill_id == "skill-a":
            raise RuntimeError("expected_failure")
        return original_run(skill_id, *args, **kwargs)

    runtime.run = selective_run  # type: ignore[assignment]

    graph = _two_node_graph_with_condition("")
    # Tweak: skill-b's input mapping refers to n1_out which won't exist if n1 fails.
    # Update n2's input mapping to map directly from "x" to make it independent.
    n2 = next(n for n in graph.nodes if n.node_id == "n2")
    n2.config["input_mapping"] = {"x": "x"}

    engine = VibeWorkflowEngine(code_runtime=runtime)
    result = engine.run(graph, {"x": 1}, options=RunOptions(fail_fast=False))
    # Result should not be success but engine kept running.
    assert not result.success
    assert "skill-a" in call_log
    # n2 was skipped because its only incoming edge (from n1) is no longer
    # active after n1 failed.
    n2_outcome = next(o for o in result.outcomes if o.node_id == "n2")
    assert n2_outcome.stage == "skipped"


def test_legacy_run_signature_still_works(tmp_path) -> None:
    """Ensure ``run(graph, data)`` (no options) keeps the original behaviour."""
    runtime, _, _ = _make_runtime(tmp_path)
    graph = _two_node_graph_with_condition("")
    engine = VibeWorkflowEngine(code_runtime=runtime)
    result = engine.run(graph, {"x": 1})  # No RunOptions
    assert result.success
