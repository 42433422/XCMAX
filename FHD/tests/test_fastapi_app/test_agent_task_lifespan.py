# mypy: disable-error-code="func-returns-value"
from __future__ import annotations

import importlib

from fastapi import FastAPI

from app.application.agent_orchestrator import task_dispatcher

lifespan_module = importlib.import_module("app.fastapi_app.lifespan")


def test_agent_task_dispatcher_starts_and_stops_with_active_app(monkeypatch) -> None:
    app = FastAPI()
    dispatcher = object()
    started: list[bool] = []
    stopped: list[bool] = []
    monkeypatch.setattr(lifespan_module, "passive_node_enabled", lambda: False)
    monkeypatch.setattr(
        task_dispatcher,
        "start_agent_task_dispatcher",
        lambda: started.append(True) or dispatcher,
    )
    monkeypatch.setattr(
        task_dispatcher,
        "stop_agent_task_dispatcher",
        lambda: stopped.append(True),
    )

    lifespan_module._start_agent_tasks(app)

    assert started == [True]
    assert app.state.agent_task_dispatcher is dispatcher

    lifespan_module._stop_agent_tasks(app)

    assert stopped == [True]
    assert not hasattr(app.state, "agent_task_dispatcher")


def test_passive_app_does_not_start_task_dispatcher(monkeypatch) -> None:
    app = FastAPI()
    monkeypatch.setattr(lifespan_module, "passive_node_enabled", lambda: True)
    monkeypatch.setattr(
        task_dispatcher,
        "start_agent_task_dispatcher",
        lambda: (_ for _ in ()).throw(AssertionError("must not start")),
    )

    lifespan_module._start_agent_tasks(app)

    assert not hasattr(app.state, "agent_task_dispatcher")
