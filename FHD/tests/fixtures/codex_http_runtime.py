"""Natural-language HTTP tasks share the durable fixed-executor entry."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import AgentOrchestrator, set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import (
    AgentTaskDispatcher,
    set_agent_task_dispatcher_for_tests,
    stop_agent_task_dispatcher,
)
from app.application.agent_orchestrator.task_execution_repository import (
    set_task_execution_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_runtime import gateway
from app.fastapi_routes.domains.agent.agent_routes import router
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def runtime_entry(trusted_actor, tmp_path, monkeypatch):
    actor = trusted_actor(role="admin")
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(repository)
    set_task_execution_repository_for_tests(queue)
    set_agent_task_dispatcher_for_tests(None)
    route = ModelRoute(
        base_url="http://127.0.0.1:19112/v1",
        model="test-fixture-model",
        provider_id="fixture",
        upstream_vendor="test-fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    qualification = tmp_path / "fixture-qualification.json"
    qualification.write_text(
        json.dumps(
            {
                "schema": "xcmax.runtime-qualification.v1",
                "route_identity": route.identity,
                "codex_version": CODEX_VERSION,
                "model_kind": "real",
                "evidence_refs": ["test-only-fixture"],
                "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
            }
        )
    )
    state = SimpleNamespace(
        actor=actor,
        repository=repository,
        queue=queue,
        calls=[],
        servers=[],
        settings=RuntimeSettings(
            engine="codex",
            route=route,
            runtime_root=tmp_path / "runtime",
            qualification_file=qualification,
        ),
    )

    class Server:
        url = "http://127.0.0.1:19113"

        def __init__(self, app):
            state.servers.append(app)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    async def runtime(**kwargs):
        # Only external runtime I/O is replaced. SQL admission, authentication,
        # generation fencing and HTTP lifecycle handlers remain production code.
        state.calls.append(kwargs)
        store, run_id = kwargs["binding_store"], kwargs["run_id"]
        grant = store.create(run_id, runtime_config=kwargs["runtime_config"])
        result = {
            "handler": "agent",
            "runtime": "codex",
            "run_id": run_id,
            "ok": True,
            "business_completed": False,
            "verified_operations": False,
            "execution_state": "completed",
            "exit_status": "completed",
            "output": "库存表示可用产品的数量。",
        }

        def complete(parent, _metadata):
            parent.status = "completed"
            parent.final_output["codex_result"] = dict(result)
            parent.add_event("run.completed", "普通说明已完成")

        store.update(run_id, complete)
        store.close(run_id, "completed", generation=grant.binding.metadata["generation"])
        return result

    monkeypatch.setattr(gateway, "runtime_settings", lambda: state.settings)
    monkeypatch.setattr(gateway, "LocalRuntimeServer", Server)
    monkeypatch.setattr(gateway, "run_codex_agent", runtime)
    monkeypatch.setattr(
        AgentOrchestrator, "start_run", lambda *a, **kw: pytest.fail("retired native entry")
    )

    def drain(run_id):
        owner = "http-fixture-worker"
        execution = queue.claim(owner, lease_seconds=120)
        assert execution is not None and execution.run_id == run_id
        AgentTaskDispatcher(execution_repository=queue, run_repository=repository)._execute_claim(
            execution, owner
        )
        return repository.get(run_id)

    state.drain = drain
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, headers=actor.headers) as client:
        state.client = client
        yield state
    set_agent_run_repository_for_tests(None)
    set_task_execution_repository_for_tests(None)
    stop_agent_task_dispatcher(timeout=0)
    set_agent_task_dispatcher_for_tests(None)
