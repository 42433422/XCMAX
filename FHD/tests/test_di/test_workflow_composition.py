"""Composition contracts: selection, isolated stores, dispatch, and cleanup."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.di.registry import ServiceContainer


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    packages = Path(__file__).resolve().parents[2] / "packages"
    for name in [
        "xcagi_langgraph_core",
        "xcagi_langgraph_prebuilt",
        "xcagi_langgraph_checkpoint",
        "xcagi_langgraph_sdk",
        "xcagi_langgraph_checkpoint_backends/checkpoint-sqlite",
        "xcagi_langgraph_checkpoint_backends/checkpoint-postgres",
    ]:
        monkeypatch.syspath_prepend(str(packages / name))
    entered, closed, builds = [], [], []

    @contextmanager
    def checkpoint(path, **scope):
        value = SimpleNamespace(path=path, **scope)
        entered.append(value)
        try:
            yield value
        finally:
            closed.append(value)

    def build(**kwargs):
        pair = (object(), object())
        builds.append((kwargs, pair))
        return pair

    dispatch = Mock(return_value={"success": True, "data": ["real-delegate"]})
    router = Mock(side_effect=lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs))
    monkeypatch.setattr(
        "app.infrastructure.workflow.checkpoint_bridge.LanggraphCheckpointBridge.from_sqlite_path",
        checkpoint,
    )
    monkeypatch.setattr("app.infrastructure.workflow.runtime_selector.build_runtime_pair", build)
    monkeypatch.setattr("app.application.workflow.runtime.shadow_canary.ShadowCanaryRouter", router)
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setenv("XCAGI_LG_CANARY_RATIO", "0.37")
    return entered, closed, builds, dispatch, router


@pytest.mark.parametrize("mode", ["legacy", "primary", "canary", "shadow"])
def test_runtime_composition_and_cleanup(wiring, monkeypatch, mode):
    entered, closed, builds, dispatch, router = wiring
    monkeypatch.setenv("XCAGI_LG_RUNTIME", mode)
    container = ServiceContainer()
    try:
        runtime = container.workflow_runtime
        assert container.workflow_runtime is runtime
        assert container.workflow_checkpointer is entered[0]
        assert [(v.tenant_id, v.run_namespace) for v in entered] == [
            ("default", "serving"),
            ("default", "shadow"),
        ]
        assert entered[0].path.endswith("/xcagi-langgraph-checkpoints.sqlite3")
        assert entered[1].path.endswith("/xcagi-langgraph-shadow-checkpoints.sqlite3")
        assert len(builds) == (2 if mode == "shadow" else 1)
        assert builds[0][0]["tool_dispatcher"]("products", "query", {"keyword": "x"}) == {
            "success": True,
            "data": ["real-delegate"],
        }
        dispatch.assert_called_once_with("products", "query", {"keyword": "x"})
        if mode in {"legacy", "primary"}:
            assert runtime is builds[0][1][int(mode == "primary")]
            router.assert_not_called()
        elif mode == "canary":
            router.assert_called_once_with(*builds[0][1], mode="canary", canary_ratio=0.37)
        else:
            router.assert_called_once_with(
                builds[0][1][0],
                builds[1][1][1],
                mode="shadow",
                shadow_safe=True,
                shadow_checkpointer=entered[1],
            )
            assert "state_event_publisher" not in builds[1][0]
        assert not closed
    finally:
        container.close_workflow_resources()
    assert closed == list(reversed(entered))


def test_invalid_runtime_closes_resources_and_can_retry(wiring, monkeypatch):
    entered, closed, *_ = wiring
    container = ServiceContainer()
    monkeypatch.setenv("XCAGI_LG_RUNTIME", "invalid")
    with pytest.raises(ValueError):
        _ = container.workflow_runtime
    assert closed == list(reversed(entered))
    monkeypatch.setenv("XCAGI_LG_RUNTIME", "legacy")
    try:
        assert container.workflow_runtime is not None
        assert len(entered) == 4
    finally:
        container.close_workflow_resources()


@pytest.mark.parametrize(
    "spec,allowed",
    [
        (SimpleNamespace(risk=" LOW ", idempotent=True), True),
        (SimpleNamespace(risk="high", idempotent=True), False),
        (SimpleNamespace(risk="low", idempotent=False), False),
        (SimpleNamespace(risk=None, idempotent=True), False),
        (SimpleNamespace(risk="low"), False),
        (None, False),
    ],
)
def test_shadow_dispatch_rejects_unsafe_or_unknown_actions(wiring, monkeypatch, spec, allowed):
    _, _, builds, dispatch, _ = wiring
    monkeypatch.setenv("XCAGI_LG_RUNTIME", "shadow")
    lookup = Mock(return_value=spec)
    monkeypatch.setattr("app.application.agent_orchestrator.tool_spec.get_tool_action_spec", lookup)
    container = ServiceContainer()
    try:
        _ = container.workflow_runtime
        shadow_dispatch = builds[1][0]["tool_dispatcher"]
        if allowed:
            assert shadow_dispatch("products", "query", {"id": 7})["success"] is True
            dispatch.assert_called_once_with("products", "query", {"id": 7})
        else:
            with pytest.raises(RuntimeError, match="read-only dispatcher"):
                shadow_dispatch("products", "query", {"id": 7})
            dispatch.assert_not_called()
        lookup.assert_called_once_with("products", "query")
    finally:
        container.close_workflow_resources()


def test_checkpointer_first_and_reload_release_previous_resources(wiring, monkeypatch):
    entered, closed, builds, *_ = wiring
    monkeypatch.setenv("XCAGI_LG_RUNTIME", "legacy")
    container = ServiceContainer()
    try:
        first_store = container.workflow_checkpointer
        first_runtime = container.workflow_runtime
        assert first_store is entered[0]
        assert len(builds) == 1
        replacement = container.reload_workflow_runtime()
        assert replacement is not first_runtime
        assert container.workflow_checkpointer is entered[2]
        assert closed == [entered[1], entered[0]]
        assert len(builds) == 2
    finally:
        container.close_workflow_resources()
    assert closed == [entered[1], entered[0], entered[3], entered[2]]
