"""Single LangGraph composition and checkpoint lifecycle contracts."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.di.registry import ServiceContainer


@pytest.fixture
def wiring(monkeypatch, tmp_path):
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
        value = SimpleNamespace(**kwargs)
        builds.append(value)
        return value

    dispatch = Mock(return_value={"success": True})
    monkeypatch.setattr(
        "app.infrastructure.workflow.checkpoint_bridge.LanggraphCheckpointBridge.from_sqlite_path",
        checkpoint,
    )
    monkeypatch.setattr("app.infrastructure.workflow.langgraph_runtime.XCAGILangGraphRuntime", build)
    monkeypatch.setattr("app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    return entered, closed, builds, dispatch


@pytest.mark.parametrize("legacy_setting", ["legacy", "shadow", "canary", "primary"])
def test_single_runtime_and_cleanup(wiring, monkeypatch, legacy_setting):
    entered, closed, builds, dispatch = wiring
    monkeypatch.setenv("XCAGI_LG_RUNTIME", legacy_setting)
    container = ServiceContainer()
    try:
        runtime = container.workflow_runtime
        assert runtime is container.workflow_runtime is builds[0]
        assert container.workflow_checkpointer is entered[0]
        assert [(v.tenant_id, v.run_namespace) for v in entered] == [
            ("default", "serving"), ("default", "shadow")
        ]
        assert runtime.tool_dispatcher("products", "query", {"keyword": "x"}) == {"success": True}
        dispatch.assert_called_once_with("products", "query", {"keyword": "x"})
    finally:
        container.close_workflow_resources()
    assert closed == list(reversed(entered))


def test_reload_releases_previous_resources(wiring):
    entered, closed, builds, _ = wiring
    container = ServiceContainer()
    try:
        first = container.workflow_runtime
        replacement = container.reload_workflow_runtime()
        assert replacement is not first
        assert replacement is builds[1]
        assert closed == [entered[1], entered[0]]
    finally:
        container.close_workflow_resources()
    assert closed == [entered[1], entered[0], entered[3], entered[2]]
