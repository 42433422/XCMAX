"""Real SQLite and HTTP ownership checks for employee run history."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.employee_runtime import run_ledger
from app.db.models.employee_run_log import EmployeeRunLog


@pytest.fixture
def ledger(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    EmployeeRunLog.__table__.create(engine)

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(run_ledger, "get_db", database)
    yield run_ledger
    engine.dispose()


def test_run_ownership_covers_reads_completion_and_missing_tenant(ledger):
    first = ledger.create_employee_run_log(employee_id="same", tenant_id=1)
    second = ledger.create_employee_run_log(employee_id="same", tenant_id=2)
    ledger.finish_employee_run_log(first, tenant_id=2, status="success", error="cross-tenant")
    assert ledger.list_employee_run_logs("same", tenant_id=1)[0]["status"] == "running"
    ledger.finish_employee_run_log(first, tenant_id=1, status="failed", error="tenant-one-private")
    assert [r["id"] for r in ledger.list_employee_run_logs("same", tenant_id=2)] == [second]
    assert ledger.list_employee_run_logs("same", tenant_id=2)[0]["error"] == ""
    for tenant in (None, 0, -1, True, "1"):
        with pytest.raises(ValueError):
            ledger.list_employee_run_logs("same", tenant_id=tenant)
        with pytest.raises(ValueError):
            ledger.create_employee_run_log(employee_id="same", tenant_id=tenant)
        with pytest.raises(ValueError):
            ledger.finish_employee_run_log(first, tenant_id=tenant, status="success")


def test_http_run_history_is_scoped_even_for_admin(ledger, monkeypatch):
    from app.application import session_account_meta
    from app.fastapi_routes.domains.misc import helpers
    from app.fastapi_routes.xcmax_admin import local_employee_runs
    from app.infrastructure.auth import dependencies

    for tenant in (1, 2):
        run = ledger.create_employee_run_log(employee_id="same", tenant_id=tenant)
        ledger.finish_employee_run_log(
            run, tenant_id=tenant, status="failed", error=f"private-{tenant}"
        )
    monkeypatch.setattr(
        helpers, "_session_id_from_request", lambda request: request.headers.get("x-session")
    )
    monkeypatch.setattr(
        dependencies,
        "resolve_session_user",
        lambda request: SimpleNamespace(tenant_id=int(request.headers["x-session"]), tier="admin"),
    )
    monkeypatch.setattr(
        session_account_meta,
        "enrich_session_meta_with_tenant",
        lambda sid, user: {"tenant_id": user.tenant_id},
    )
    app = FastAPI()
    app.add_api_route("/runs/{employee_id}", local_employee_runs, methods=["GET"])
    with TestClient(app) as client:
        for tenant in (1, 2):
            response = client.get(
                "/runs/same", headers={"x-session": str(tenant)}, params={"tenant_id": 3 - tenant}
            )
            assert response.status_code == 200
            assert [r["error"] for r in response.json()["data"]] == [f"private-{tenant}"]
        assert client.get("/runs/same").status_code == 401
        assert client.get("/runs/same", headers={"x-session": "0"}).status_code == 403


@pytest.mark.parametrize(
    "outcome, expected",
    [
        ({"success": False, "retryable": False, "error": "denied"}, "failed"),
        ({"success": False, "status": "unknown", "error": "receipt lost"}, "unknown"),
        ({"success": False, "result": {"outputs": [{"execution_state": "unknown"}]}}, "unknown"),
        ({"success": False, "pending_approval": True}, "awaiting_approval"),
        (None, "unknown"),
    ],
)
def test_http_execution_does_not_replay_or_accept_body_identity(
    ledger, monkeypatch, outcome, expected
):
    from unittest.mock import Mock

    from app.application import auth_permission_resolver, session_account_meta
    from app.application.employee_runtime import executor, result_verifier
    from app.fastapi_routes.domains.misc import helpers
    from app.fastapi_routes.xcmax_admin import local_employee_execute
    from app.infrastructure.auth import dependencies

    monkeypatch.setattr(helpers, "_session_id_from_request", lambda request: "trusted-session")
    monkeypatch.setattr(
        dependencies, "resolve_session_user", lambda request: SimpleNamespace(id=7, tenant_id=1)
    )
    monkeypatch.setattr(
        session_account_meta,
        "enrich_session_meta_with_tenant",
        lambda sid, user: {"tenant_id": 1, "account_kind": "admin"},
    )
    monkeypatch.setattr(auth_permission_resolver, "require_allowed", lambda **kwargs: None)
    execute = Mock(return_value=outcome)
    monkeypatch.setattr(executor, "execute_employee_task_local", execute)
    monkeypatch.setattr(
        result_verifier, "verify_employee_run_result", lambda *args: (False, "failed")
    )
    app = FastAPI()
    app.add_api_route("/execute/{employee_id}", local_employee_execute, methods=["POST"])
    with TestClient(app) as client:
        response = client.post(
            "/execute/same",
            json={
                "task": "write",
                "retry_max": 5,
                "user_id": 999,
                "session_id": "other",
                "input_data": {
                    "user_id": 999,
                    "session_id": "other",
                    "tenant_id": 2,
                    "_runtime_context": {"tenant_id": 2},
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["attempts"] == 1
    assert execute.call_count == 1
    assert execute.call_args.kwargs["user_id"] == 7
    assert execute.call_args.kwargs["session_id"] == "trusted-session"

    assert ledger.list_employee_run_logs("same", tenant_id=1)[0]["status"] == expected
    payload = execute.call_args.args[2]
    assert payload["user_id"] == 7 and payload["session_id"] == "trusted-session"
    assert payload["tenant_id"] == 1 and "_runtime_context" not in payload
    assert payload["run_id"] == response.json()["run_id"]
