from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.fastapi_routes.domains.agent import route_support


class _Orchestrator:
    def __init__(self, runs: list[Any]) -> None:
        self.runs = runs
        self.get_run_calls = 0

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[Any]:
        return self.runs

    def get_run(self, run_id: str) -> Any:
        self.get_run_calls += 1
        return next(run for run in self.runs if run.run_id == run_id)


def _run(run_id: str, *, user_id: str = "u1", mod_id: str = "") -> Any:
    return SimpleNamespace(
        run_id=run_id,
        user_id=user_id,
        metadata={"runtime_context": {"_mod_authorization": {"mod_id": mod_id}}},
    )


def _principal(mod_id: str = "") -> Any:
    return SimpleNamespace(user_id="u1", tenant_id="t1", mod_authorization={"mod_id": mod_id})


def test_task_scope_uses_listed_runs_without_refetching(monkeypatch) -> None:
    monkeypatch.setattr(route_support, "tenant_id_of_run", lambda run: "t1")
    orchestrator = _Orchestrator([_run(f"r{i}") for i in range(20)])
    task = SimpleNamespace(user_id="u1", tenant_id="t1", task_id="task-1")

    assert route_support.task_scope_matches(orchestrator, task, _principal())
    assert orchestrator.get_run_calls == 0


def test_task_scope_still_rejects_runs_bound_to_another_mod(monkeypatch) -> None:
    monkeypatch.setattr(route_support, "tenant_id_of_run", lambda run: "t1")
    orchestrator = _Orchestrator([_run("r1"), _run("r2", mod_id="other-mod")])
    task = SimpleNamespace(user_id="u1", tenant_id="t1", task_id="task-1")

    assert not route_support.task_scope_matches(orchestrator, task, _principal("my-mod"))
