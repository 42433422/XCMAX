"""HTTP cron execution binds real session resolution, not request authority."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.admin_control.employees import LocalEmployees


@pytest.fixture
def cron_http(monkeypatch, tmp_path):
    from app.application import desktop_admin_gate, session_account_meta
    from app.application.employee_runtime import scheduler
    from app.fastapi_routes.domains.misc import helpers
    from app.infrastructure.auth import dependencies
    from app.infrastructure.tenant_scope import current_tenant_id

    users = {
        "valid-admin": SimpleNamespace(id=7, tenant_id=11, account_kind="admin"),
        "valid-enterprise": SimpleNamespace(
            id=9, tenant_id=11, account_kind="enterprise", role="enterprise_operator"
        ),
        "enterprise-viewer": SimpleNamespace(
            id=10, tenant_id=11, account_kind="enterprise", role="enterprise_viewer"
        ),
        "valid-personal": SimpleNamespace(id=8, tenant_id=11, account_kind="personal"),
        "no-tenant": SimpleNamespace(id=7, tenant_id=None, account_kind="admin"),
    }
    monkeypatch.setattr(helpers, "_session_id_from_request", lambda r: r.headers.get("x-session"))
    resolve = Mock(side_effect=lambda r: users.get(r.headers.get("x-session")))
    monkeypatch.setattr(dependencies, "resolve_session_user", resolve)
    monkeypatch.setattr(
        session_account_meta,
        "enrich_session_meta_with_tenant",
        lambda sid, user: {
            "tenant_id": user.tenant_id,
            "account_kind": user.account_kind,
        },
    )
    monkeypatch.setattr(desktop_admin_gate, "is_desktop_runtime", lambda: False)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    calls = []

    def execute(job_id, **kwargs):
        calls.append((job_id, kwargs, current_tenant_id()))
        return {
            "success": job_id != "missing",
            "error": "unknown employee cron job: missing",
        }

    monkeypatch.setattr(scheduler, "run_employee_cron_job", execute)
    app = FastAPI()
    handler = LocalEmployees(errors=SimpleNamespace())
    app.add_api_route("/cron/{job_id}", handler.local_employee_cron_job_run, methods=["POST"])
    with TestClient(app) as client:
        yield client, calls, resolve, str(tmp_path.resolve())


@pytest.mark.parametrize("session", [None, "forged", "expired"])
def test_cron_rejects_unresolved_session(cron_http, session):
    client, calls, resolve, _ = cron_http
    response = client.post(
        "/cron/daily", headers={"x-session": session} if session else {}, json={}
    )
    assert response.status_code == 401
    assert not calls
    assert resolve.call_count == (1 if session else 0)


def test_cron_rejects_missing_invoke_permission_and_tenant(cron_http):
    client, calls, _, _ = cron_http
    for session in ("valid-personal", "enterprise-viewer", "no-tenant"):
        assert (
            client.post("/cron/daily", headers={"x-session": session}, json={}).status_code == 403
        )
    assert not calls


def test_cron_rejects_foreign_top_level_root(cron_http):
    client, calls, _, root = cron_http
    response = client.post(
        "/cron/daily",
        headers={"x-session": "valid-admin"},
        json={"workspace_root": root + "-foreign"},
    )
    assert response.status_code == 403
    assert not calls


def test_cron_overwrites_nested_authority_and_preserves_work(cron_http):
    client, calls, _, root = cron_http
    response = client.post(
        "/cron/daily",
        headers={"x-session": "valid-admin"},
        json={
            "task": "safe task",
            "workspace_root": root,
            "user_id": 999,
            "session_id": "other-session",
            "input_data": {
                "message": "keep",
                "user_id": 999,
                "tenant_id": 999,
                "session_id": "other",
                "workspace_root": "/foreign",
                "employee_id": "other-employee",
                "_runtime_context": {"workspace_root": "/foreign"},
                "runtime_context": {"user_id": 999},
                "_actor_authorization": {"user_id": 999},
            },
        },
    )
    assert response.status_code == 200
    job, args, tenant = calls[0]
    assert job == "daily" and tenant == 11
    assert args["task"] == "safe task"
    assert args["user_id"] == 7 and args["session_id"] == "valid-admin"
    assert args["workspace_root"] == root
    assert args["input_data"] == {
        "message": "keep",
        "user_id": 7,
        "tenant_id": 11,
        "session_id": "valid-admin",
        "workspace_root": root,
    }


def test_cron_preserves_default_task_and_missing_job_status(cron_http):
    client, calls, _, _ = cron_http
    assert (
        client.post("/cron/daily", headers={"x-session": "valid-admin"}, json={}).status_code == 200
    )
    assert calls[0][1]["task"] is None
    assert (
        client.post("/cron/missing", headers={"x-session": "valid-admin"}, json={}).status_code
        == 404
    )


def test_cron_rejects_non_object_input(cron_http):
    client, calls, _, _ = cron_http
    assert (
        client.post(
            "/cron/daily", headers={"x-session": "valid-admin"}, json={"input_data": []}
        ).status_code
        == 400
    )
    assert not calls


def test_desktop_enterprise_can_invoke_but_viewer_and_admin_cannot(cron_http, monkeypatch):
    from app.application import desktop_admin_gate

    client, calls, _, root = cron_http
    monkeypatch.setattr(desktop_admin_gate, "is_desktop_runtime", lambda: True)
    response = client.post(
        "/cron/daily", headers={"x-session": "valid-enterprise"}, json={"task": "desktop work"}
    )
    assert response.status_code == 200
    assert calls[0][1]["user_id"] == 9
    assert calls[0][1]["workspace_root"] == root
    for session in ("enterprise-viewer", "valid-admin", "valid-personal"):
        assert (
            client.post("/cron/daily", headers={"x-session": session}, json={}).status_code == 403
        )
    assert len(calls) == 1
