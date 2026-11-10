from __future__ import annotations

import json

import pytest

from evals import run_agent_eval as eval_module
from evals.run_agent_eval import DEFAULT_TASKS_PATH, run_eval


def test_agent_eval_harness_baseline_passes(monkeypatch) -> None:
    from app.application.agent_orchestrator import orchestrator

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    original_executor = orchestrator.AgentToolExecutor
    result = run_eval(DEFAULT_TASKS_PATH)

    assert orchestrator.AgentToolExecutor is original_executor
    assert result["execution_mode"] == "fixture_local"
    assert result["failed"] == 0, [case for case in result["results"] if not case["passed"]]
    assert result["passed"] == 123
    assert len(result["results"]) == 123
    assert result["score"] == 1.0
    missing_spec = next(
        row
        for row in result["results"]
        if row["id"] == "business_shipment_create_missing_spec_rejects_before_publish"
    )
    assert missing_spec["details"]["response"]["error_code"] == "SHIPMENT_SPEC_REQUIRED"
    assert missing_spec["details"]["publish_call_count"] == 0


@pytest.mark.parametrize("fail_task", [False, True])
def test_eval_owns_real_approval_queue_and_restores_it(monkeypatch, fail_task) -> None:
    from app.application.agent_orchestrator import task_execution_repository as queues
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    original_queue = queues._task_execution_repository
    original_open = queues._OPEN_REPOSITORIES
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def run_task(_task):
        repository = queues.get_task_execution_repository()
        assert isinstance(repository, queues.SQLAlchemyTaskExecutionRepository)
        assert repository is not original_queue
        run = AgentRun(user_id="7", message="requires approval")
        run.metadata["runtime_context"] = {"tenant_id": "7", "task_id": run.run_id}
        repository.enqueue(run)
        assert repository.claim("fixture-worker", lease_seconds=30) is not None
        repository.request_approval(run.run_id, "fixture-manager")
        result = AgentToolExecutor().execute(
            AgentStep(
                node_id="create",
                tool_id="customers",
                action="create",
                params={"unit_name": "Blocked fixture customer"},
            ),
            runtime_context={"tenant_id": "7", "task_id": run.run_id, "run_id": run.run_id},
        )
        assert result["success"] is False
        assert result["reason"] == "approval_required", result
        if fail_task:
            raise RuntimeError("evaluation failure")
        return {"passed": True}

    monkeypatch.setattr(eval_module, "load_tasks", lambda _path: [{}])
    monkeypatch.setattr(eval_module, "run_task", run_task)
    if fail_task:
        with pytest.raises(RuntimeError, match="evaluation failure"):
            run_eval()
    else:
        assert run_eval()["passed"] == 1
    assert queues._task_execution_repository is original_queue
    assert queues._OPEN_REPOSITORIES is original_open


def test_agent_eval_cli_prints_only_public_summary(monkeypatch, capsys) -> None:
    result = {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "score": 1.0,
        "results": [{"api_key": "must-not-be-printed", "passed": True}],
    }
    monkeypatch.setattr(eval_module, "run_eval", lambda _path: result)

    assert eval_module.main([]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "suite": "agent_platform_minimum",
        "execution_mode": "fixture_local",
        "tasks_path": str(DEFAULT_TASKS_PATH),
        "total": 1,
        "passed": 1,
        "failed": 0,
        "score": 1.0,
    }
    assert "must-not-be-printed" not in output


def test_route_fixture_uses_real_session_and_restores_auth_boundary() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app import db as host_db
    from app.db.models.user import User
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.utils.security.password_hash import check_password_hash

    app = FastAPI()

    @app.post("/fixture-write")
    def write(principal=Depends(require_agent_principal)):
        return {"tenant_id": principal.tenant_id, "sealed": bool(principal.actor_authorization)}

    with TestClient(app) as client:
        original_factory = host_db.HostSessionLocal
        assert client.post("/fixture-write").status_code == 401
        with eval_module._authenticated_route_fixture(client):
            with host_db.HostSessionLocal() as db:
                stored = db.query(User).one().password
                assert stored.startswith("pbkdf2:sha256:")
                assert not check_password_hash(stored, "unused")
            assert client.post("/fixture-write").json() == {"tenant_id": "7", "sealed": True}
            assert (
                client.post("/fixture-write", headers={"X-Session-ID": "forged"}).status_code == 401
            )
        assert host_db.HostSessionLocal is original_factory
        assert "X-Session-ID" not in client.headers
        assert client.post("/fixture-write").status_code == 401


def test_legacy_shipment_fixture_does_not_admit_enterprise_tenant(monkeypatch) -> None:
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes import shipment_orders

    app = FastAPI()
    app.include_router(shipment_orders.router)
    service = Mock()
    monkeypatch.setattr(shipment_orders, "_svc", lambda: service)
    with TestClient(app) as client, eval_module._authenticated_route_fixture(client, tenant_id=7):
        response = client.delete("/api/orders/clear-all")
    assert response.status_code == 403
    assert "租户数据隔离" in response.json()["detail"]
    assert not service.mock_calls
