from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.application.workflow.runtime.shadow_canary import (
    ReadOnlyToolDispatcher,
    ShadowCanaryRouter,
)
from app.application.workflow.runtime.shadow_canary_diff import (
    compute_normalized_diff,
    deterministic_canary_selected,
    normalize_context,
)
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowRunResult,
)


def _result(plan_id: str = "p", *, value: int = 1) -> WorkflowRunResult:
    return WorkflowRunResult(
        plan_id=plan_id,
        success=True,
        node_results=[NodeExecutionResult("n", True, "tool", "read")],
        final_context={"value": value, "timestamp": "volatile"},
    )


class _Runtime:
    def __init__(self, result: WorkflowRunResult | None = None, *, dispatch: Any = None):
        self.result = result or _result()
        self._dispatch = dispatch
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.error: Exception | None = None

    def _call(self, name: str, *args: Any, **kwargs: Any) -> WorkflowRunResult:
        self.calls.append((name, args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result

    def run(self, *args: Any, **kwargs: Any) -> WorkflowRunResult:
        return self._call("run", *args, **kwargs)

    def resume_run(self, *args: Any, **kwargs: Any) -> WorkflowRunResult:
        return self._call("resume", *args, **kwargs)

    def replay_run(self, *args: Any, **kwargs: Any) -> WorkflowRunResult:
        return self._call("replay", *args, **kwargs)


class _Kind(Enum):
    A = "a"


@dataclass
class _Payload:
    value: int


class _Opaque:
    pass


def test_normalize_context_canonicalizes_supported_values() -> None:
    raw = {
        "timestamp": "drop",
        "nested": {"Trace_ID": "drop", 2: "two"},
        "sequence": (1, _Kind.A),
        "unordered": {"b", "a"},
        "frozen": frozenset({2, 1}),
        "dataclass": _Payload(3),
        "dataclass_type": _Payload,
        "datetime": datetime(2026, 1, 2, 3, 4, 5),
        "date": date(2026, 1, 2),
        "time": time(3, 4, 5),
        "bytes": b"\x01\x02",
        "scalar": [None, True, 1, 1.5, "x"],
        "opaque": _Opaque(),
    }

    normalized = normalize_context(raw)

    assert "timestamp" not in normalized
    assert normalized["nested"] == {"2": "two"}
    assert normalized["sequence"] == [1, "a"]
    assert normalized["unordered"] == ["a", "b"]
    assert normalized["frozen"] == [1, 2]
    assert normalized["dataclass"] == {"value": 3}
    assert normalized["dataclass_type"] == {"__xcagi_object__": "type"}
    assert normalized["datetime"] == "2026-01-02T03:04:05"
    assert normalized["date"] == "2026-01-02"
    assert normalized["time"] == "03:04:05"
    assert normalized["bytes"] == "0102"
    assert normalized["opaque"] == {"__xcagi_object__": "_Opaque"}
    assert normalize_context({"keep": 1, "custom": 2}, volatile_keys=("custom",)) == {"keep": 1}


@pytest.mark.parametrize("ratio", [True, "0.5", float("nan"), -0.1, 1.1])
def test_canary_ratio_rejects_invalid_values(ratio: Any) -> None:
    with pytest.raises(ValueError):
        deterministic_canary_selected("tenant-plan", ratio)


def test_canary_selection_boundaries_and_stability() -> None:
    assert deterministic_canary_selected("x", 0.0) is False
    assert deterministic_canary_selected("x", 1.0) is True
    assert deterministic_canary_selected("stable", 0.5) == deterministic_canary_selected(
        "stable", 0.5
    )


def test_diff_compares_nodes_and_normalized_context() -> None:
    assert compute_normalized_diff(_result(), _result()).equal is True
    changed = _result(value=2)
    diff = compute_normalized_diff(_result(), changed, operation="resume", langgraph_error="e")
    assert diff.equal is False
    assert diff.operation == "resume"
    assert diff.langgraph_error == "e"
    changed.node_results = []
    assert compute_normalized_diff(_result(), changed).equal is False


def test_read_only_dispatcher_allows_only_explicit_reads() -> None:
    delegate = MagicMock(return_value={"success": True})
    empty = ReadOnlyToolDispatcher(delegate)
    with pytest.raises(RuntimeError):
        empty("orders", "write", {"x": 1})
    delegate.assert_not_called()
    assert empty.calls == [("orders", "write", {"x": 1})]

    allowed = ReadOnlyToolDispatcher(delegate, {("orders", "list")})
    assert allowed("orders", "list", {}) == {"success": True}
    predicate = ReadOnlyToolDispatcher(delegate, lambda tool, action: action == "view")
    assert predicate("orders", "view", {})["success"] is True
    with pytest.raises(RuntimeError):
        predicate("orders", "delete", {})


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "bad"}, "无效模式"),
        ({"mode": "shadow"}, "shadow_safe"),
        ({"canary_ratio": True}, "不能是 bool"),
        ({"canary_ratio": "0.2"}, "必须是实数"),
        ({"canary_ratio": float("inf")}, "有限实数"),
        ({"canary_ratio": -0.1}, "闭区间"),
        ({"canary_ratio": 1.1}, "闭区间"),
    ],
)
def test_router_rejects_invalid_configuration(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ShadowCanaryRouter(_Runtime(), _Runtime(), **kwargs)
    runtime = _Runtime()
    with pytest.raises(ValueError, match="不同对象"):
        ShadowCanaryRouter(runtime, runtime)


def test_router_legacy_primary_and_canary_paths() -> None:
    plan = PlanGraph("p", "intent")
    legacy = _Runtime(_result(value=1))
    langgraph = _Runtime(_result(value=2))

    assert ShadowCanaryRouter(legacy, langgraph).run(plan).final_context["value"] == 1
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="primary").run(plan).final_context["value"] == 2
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="canary", canary_ratio=1).run(
            plan, {"tenant_id": 7, "run_id": "r"}
        )
        is langgraph.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="canary", canary_ratio=0).run(plan, {})
        is legacy.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="canary", canary_ratio=1).resume_run(
            plan, "cp", checkpointer="prod"
        )
        is langgraph.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="canary", canary_ratio=0).resume_run(
            plan, "cp", checkpointer="prod"
        )
        is legacy.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="canary", canary_ratio=1).replay_run(
            "p", "cp", checkpointer="prod"
        )
        is langgraph.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="canary", canary_ratio=0).replay_run(
            "p", None, checkpointer="prod"
        )
        is legacy.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph, mode="primary").resume_run(
            plan, "cp", checkpointer="prod"
        )
        is langgraph.result
    )
    assert (
        ShadowCanaryRouter(legacy, langgraph).replay_run("p", checkpointer="prod") is legacy.result
    )


def _shadow_pair(*, sink: Any = None, shadow_store: Any = None):
    delegate = MagicMock(return_value={"success": True})
    dispatcher = ReadOnlyToolDispatcher(delegate, {("tool", "read")})
    legacy = _Runtime(_result(value=1))
    langgraph = _Runtime(_result(value=2), dispatch=dispatcher)
    router = ShadowCanaryRouter(
        legacy,
        langgraph,
        mode="shadow",
        shadow_safe=True,
        diff_sink=sink,
        shadow_checkpointer=shadow_store,
    )
    return router, legacy, langgraph


def test_shadow_run_isolated_context_and_diff_sink() -> None:
    diffs: list[Any] = []
    shadow_store = object()
    router, legacy, langgraph = _shadow_pair(sink=diffs.append, shadow_store=shadow_store)
    context = {"nested": {"value": 1}}
    result = router.run(PlanGraph("p", "intent"), context, checkpointer=object())

    assert result is legacy.result
    assert diffs and diffs[0].equal is False
    legacy_context = legacy.calls[0][1][1]
    shadow_context = langgraph.calls[0][1][1]
    assert legacy_context == shadow_context == context
    assert legacy_context is not shadow_context
    assert langgraph.calls[0][1][-2] is shadow_store
    assert langgraph.calls[0][1][-1] is None


def test_shadow_fail_closed_and_fail_soft_paths() -> None:
    plan = PlanGraph("p", "intent")
    unsafe = ShadowCanaryRouter(_Runtime(), _Runtime(), mode="shadow", shadow_safe=True)
    with pytest.raises(RuntimeError, match="ReadOnlyToolDispatcher"):
        unsafe.run(plan)

    store = object()
    router, legacy, langgraph = _shadow_pair(shadow_store=store)
    with pytest.raises(ValueError, match="不能是同一对象"):
        router.run(plan, checkpointer=store)

    langgraph.error = RuntimeError("shadow down")
    assert router.run(plan) is legacy.result

    legacy.error = RuntimeError("serving down")
    with pytest.raises(RuntimeError, match="serving down"):
        router.run(plan)


def test_shadow_resume_replay_and_sink_failure_do_not_change_serving_result() -> None:
    sink = MagicMock(side_effect=RuntimeError("sink down"))
    router, legacy, _langgraph = _shadow_pair(sink=sink, shadow_store=object())
    plan = PlanGraph("p", "intent")

    assert router.resume_run(plan, "cp", checkpointer=object()) is legacy.result
    assert router.replay_run("p", "cp", checkpointer=object()) is legacy.result
    assert sink.call_count == 2

    no_sink, legacy2, _ = _shadow_pair()
    assert no_sink.run(plan, None) is legacy2.result
