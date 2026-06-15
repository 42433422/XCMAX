"""Tests for the advanced workflow executor — parallel / spawn / event."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from vibe_coding.agent.workflow_advanced import (
    AdvancedNode,
    AdvancedWorkflow,
    AdvancedWorkflowExecutor,
    AsyncWorkflowExecutor,
    DynamicSpawn,
    EventBus,
    NodeKind,
    ParallelGroup,
    TriggerSpec,
)
from vibe_coding.agent.workflow_advanced.executor import RunOptions
from vibe_coding.agent.workflow_advanced.graph import AdvancedEdge


# ---------------------------------------------------------------- linear DAG


def test_linear_workflow_runs_in_topological_order() -> None:
    order: list[str] = []

    def make(name: str):
        def runner(kwargs, execution):  # noqa: ARG001
            order.append(name)
            return {"name": name}

        return runner

    wf = AdvancedWorkflow(
        workflow_id="linear",
        nodes=[
            AdvancedNode(id="a", runner=make("a")),
            AdvancedNode(id="b", runner=make("b")),
            AdvancedNode(id="c", runner=make("c")),
        ],
        edges=[
            AdvancedEdge(source="a", target="b"),
            AdvancedEdge(source="b", target="c"),
        ],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    assert result.success is True
    assert order == ["a", "b", "c"]
    assert {n.node_id for n in result.nodes if n.status == "done"} == {"a", "b", "c"}


# ---------------------------------------------------------------- parallel


def test_parallel_group_all_runs_concurrently() -> None:
    started: list[float] = []
    finished: list[float] = []
    lock = threading.Lock()

    def make(name: str, delay: float):
        def runner(kwargs, execution):  # noqa: ARG001
            with lock:
                started.append(time.perf_counter())
            time.sleep(delay)
            with lock:
                finished.append(time.perf_counter())
            return {"name": name}

        return runner

    children = [
        AdvancedNode(id="c1", runner=make("c1", 0.05)),
        AdvancedNode(id="c2", runner=make("c2", 0.05)),
        AdvancedNode(id="c3", runner=make("c3", 0.05)),
    ]
    wf = AdvancedWorkflow(
        workflow_id="par",
        nodes=[
            AdvancedNode(
                id="grp",
                kind=NodeKind.parallel,
                parallel=ParallelGroup(children=children, mode="all"),
            )
        ],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    assert result.success is True
    assert len(started) == 3
    # Concurrency check: all three started within 30ms of the first.
    assert max(started) - min(started) < 0.04
    grp_outcome = next(n for n in result.nodes if n.node_id == "grp")
    assert set(grp_outcome.children) == {"c1", "c2", "c3"}
    assert set(grp_outcome.output["completed"]) == {"c1", "c2", "c3"}


def test_parallel_group_any_finishes_after_first_success() -> None:
    def fast(kwargs, execution):  # noqa: ARG001
        return {"v": "fast"}

    def slow(kwargs, execution):  # noqa: ARG001
        time.sleep(0.5)
        return {"v": "slow"}

    wf = AdvancedWorkflow(
        workflow_id="any",
        nodes=[
            AdvancedNode(
                id="g",
                kind=NodeKind.parallel,
                parallel=ParallelGroup(
                    mode="any",
                    children=[
                        AdvancedNode(id="fast", runner=fast),
                        AdvancedNode(id="slow", runner=slow),
                    ],
                ),
            )
        ],
    )
    t0 = time.perf_counter()
    result = AdvancedWorkflowExecutor().run(wf)
    elapsed = time.perf_counter() - t0
    grp = next(n for n in result.nodes if n.node_id == "g")
    assert grp.status == "done"
    assert "fast" in grp.output["completed"]
    # Finished well before the slow child would have.
    assert elapsed < 0.4


def test_parallel_group_at_least_threshold() -> None:
    def good(kwargs, execution):  # noqa: ARG001
        return {"ok": True}

    def bad(kwargs, execution):  # noqa: ARG001
        raise RuntimeError("nope")

    wf = AdvancedWorkflow(
        workflow_id="th",
        nodes=[
            AdvancedNode(
                id="g",
                kind=NodeKind.parallel,
                parallel=ParallelGroup(
                    mode="at_least",
                    threshold=2,
                    children=[
                        AdvancedNode(id="a", runner=good),
                        AdvancedNode(id="b", runner=good),
                        AdvancedNode(id="c", runner=bad),
                    ],
                    fail_fast=False,
                ),
            )
        ],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    grp = next(n for n in result.nodes if n.node_id == "g")
    assert grp.status == "done"
    assert len(grp.output["completed"]) >= 2


# ---------------------------------------------------------------- spawn


def test_dynamic_spawn_inserts_followups() -> None:
    visited: list[str] = []

    def planner(kwargs, execution):  # noqa: ARG001
        # The planner's output carries new nodes via ``__spawn__``.
        children = [
            AdvancedNode(
                id=f"task-{i}",
                runner=(lambda i=i: lambda kw, ex: visited.append(f"task-{i}") or {})(),
            )
            for i in range(3)
        ]
        return {"plan": "split into 3", "__spawn__": children}

    wf = AdvancedWorkflow(
        workflow_id="spawn",
        nodes=[
            AdvancedNode(
                id="planner",
                kind=NodeKind.spawn,
                runner=planner,
                spawn=DynamicSpawn(),
            )
        ],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    assert sorted(visited) == ["task-0", "task-1", "task-2"]
    planner_node = next(n for n in result.nodes if n.node_id == "planner")
    assert sorted(planner_node.children) == ["task-0", "task-1", "task-2"]


# ---------------------------------------------------------------- event


def test_event_node_blocks_until_published() -> None:
    bus = EventBus()
    seen_payload = []

    def downstream(kwargs, execution):
        seen_payload.append(kwargs)
        return {}

    wf = AdvancedWorkflow(
        workflow_id="evt",
        nodes=[
            AdvancedNode(
                id="wait",
                kind=NodeKind.event,
                trigger=TriggerSpec(topic="user_clicked_approve", timeout_s=1.0),
            ),
            AdvancedNode(
                id="continue",
                runner=downstream,
                inputs={"payload": "wait.event_payload"},
            ),
        ],
        edges=[AdvancedEdge(source="wait", target="continue")],
    )
    executor = AdvancedWorkflowExecutor(event_bus=bus)

    def trigger() -> None:
        time.sleep(0.05)
        bus.publish("user_clicked_approve", payload={"user": "alice"})

    threading.Thread(target=trigger).start()
    result = executor.run(wf)
    assert result.success is True
    assert seen_payload[0]["payload"] == {"user": "alice"}


def test_event_node_timeout_records_failure() -> None:
    wf = AdvancedWorkflow(
        workflow_id="timeout",
        nodes=[
            AdvancedNode(
                id="wait",
                kind=NodeKind.event,
                trigger=TriggerSpec(topic="never", timeout_s=0.05),
            )
        ],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    assert result.success is False
    wait_node = next(n for n in result.nodes if n.node_id == "wait")
    assert wait_node.status == "failed"
    assert "not received" in wait_node.error


# ---------------------------------------------------------------- retries / timeout


def test_retries_kick_in_on_failure() -> None:
    counts = {"n": 0}

    def flaky(kwargs, execution):  # noqa: ARG001
        counts["n"] += 1
        if counts["n"] < 2:
            raise RuntimeError("flaky")
        return {"ok": True}

    wf = AdvancedWorkflow(
        workflow_id="r",
        nodes=[AdvancedNode(id="x", runner=flaky, retries=2)],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    assert result.success is True
    node = next(n for n in result.nodes if n.node_id == "x")
    assert node.attempts == 2


def test_node_timeout_marks_failure() -> None:
    def hang(kwargs, execution):  # noqa: ARG001
        time.sleep(0.5)
        return {}

    wf = AdvancedWorkflow(
        workflow_id="t",
        nodes=[AdvancedNode(id="x", runner=hang, timeout_s=0.05)],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    node = next(n for n in result.nodes if n.node_id == "x")
    assert node.status == "failed"


# ---------------------------------------------------------------- conditional


def test_conditional_edge_skips_downstream_when_false() -> None:
    def upstream(kwargs, execution):  # noqa: ARG001
        return {"go": False}

    def downstream(kwargs, execution):  # noqa: ARG001
        raise AssertionError("should not run")

    wf = AdvancedWorkflow(
        workflow_id="cond",
        nodes=[
            AdvancedNode(id="up", runner=upstream),
            AdvancedNode(id="down", runner=downstream),
        ],
        edges=[AdvancedEdge(source="up", target="down", condition="up.go == True")],
    )
    result = AdvancedWorkflowExecutor().run(wf)
    down = next(n for n in result.nodes if n.node_id == "down")
    assert down.status == "skipped"


# ---------------------------------------------------------------- async


def test_async_executor_runs_to_completion() -> None:
    def step(kwargs, execution):  # noqa: ARG001
        return {"v": kwargs.get("seed", 0) + 1}

    wf = AdvancedWorkflow(
        workflow_id="a",
        nodes=[
            AdvancedNode(id="x", runner=step),
            AdvancedNode(id="y", runner=step, inputs={"seed": "x.v"}),
        ],
        edges=[AdvancedEdge(source="x", target="y")],
    )
    executor = AsyncWorkflowExecutor()
    result = asyncio.run(executor.run(wf))
    assert result.success is True
    y = next(n for n in result.nodes if n.node_id == "y")
    assert y.output["v"] == 2


# ---------------------------------------------------------------- bus


def test_event_bus_history_filters_by_topic() -> None:
    bus = EventBus(history=10)
    bus.publish("a", payload=1)
    bus.publish("b", payload=2)
    bus.publish("a", payload=3)
    rows = bus.history(topic="a")
    assert [r.payload for r in rows] == [1, 3]


def test_event_bus_filter_fn_rejects_non_matching() -> None:
    bus = EventBus()
    bus.publish("topic", payload={"branch": "feature"})
    bus.publish("topic", payload={"branch": "main"})

    def keep_main(p: Any) -> bool:
        return isinstance(p, dict) and p.get("branch") == "main"

    event = bus.wait_for("topic", filter_fn=keep_main, timeout_s=0.1)
    assert event is not None
    assert event.payload["branch"] == "main"
