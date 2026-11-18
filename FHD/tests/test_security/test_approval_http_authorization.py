"""Approval HTTP authorization against real sessions and an isolated database."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application import approval_workspace_app_service as service
from app.application.facades import session_facade
from app.db.db_base import Base
from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRecord, ApprovalRequest
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes.approval import router
from app.infrastructure.auth.dependencies import require_identified_user
from app.infrastructure.session import session_manager
from app.middleware.csrf import CSRFMiddleware
from app.middleware.industry_context import IndustryContextMiddleware
from app.utils.time import utc_now_naive


@pytest.fixture(params=["/api/approval", "/api/mod/xcagi-approval-bridge"])
def approval_http(request, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            model.__table__
            for model in (
                User,
                UserSession,
                ApprovalFlow,
                ApprovalFlowNode,
                ApprovalRequest,
                ApprovalRecord,
            )
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE ai_action_audit (actor TEXT, action TEXT, payload TEXT)")
        )
    with Session(engine) as db:
        for uid, role, tier, active, tenant in (
            (1, "viewer", "enterprise", True, 10),
            (2, "admin", "admin", True, None),
            (3, "admin", "admin", False, None),
        ):
            db.add(
                User(
                    id=uid,
                    username=f"synthetic-{uid}",
                    password="test-only",
                    role=role,
                    tier=tier,
                    is_active=active,
                    tenant_id=tenant,
                )
            )
            db.add(
                UserSession(
                    user_id=uid,
                    session_id=f"session-{uid}",
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
        db.add(ApprovalFlow(id=1, flow_key="existing", flow_name="Unchanged", created_by=2))
        db.commit()

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(service, "get_db", database)
    monkeypatch.setattr(session_manager, "get_host_db", database)
    monkeypatch.setattr(session_facade, "get_session_service", session_manager.SessionManager)
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(router)

    @app.get("/identified")
    def identified(user=Depends(require_identified_user)):
        return {"user_id": user.user_id}

    path = (
        Path(__file__).resolve().parents[2]
        / "mods/bridge/xcagi-approval-bridge/backend/blueprints.py"
    )
    spec = importlib.util.spec_from_file_location("approval_authorization_bridge", path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    bridge.register_fastapi_routes(app, "xcagi-approval-bridge")
    try:
        with TestClient(app) as client:
            client.get(request.param + "/flows")
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            yield client, request.param, engine
    finally:
        engine.dispose()


def _new_flow():
    return {
        "flow": {"flow_name": "Synthetic", "flow_key": "new", "created_by": 999},
        "nodes": [{"node_name": "Review", "approver_ids": [2]}],
    }


@pytest.mark.parametrize("identity,expected", [(None, 401), ("expired", 401), (3, 403)])
def test_session_required_on_both_surfaces(approval_http, identity, expected):
    client, prefix, engine = approval_http
    if identity is not None:
        client.cookies.set("session_id", f"session-{identity}")
    client.headers["X-User-ID"] = "2"
    for path in ("/requests", "/requests/1", "/flows", "/flows/1", "/users"):
        assert client.get(prefix + path).status_code == expected
    assert client.post(prefix + "/flows", json=_new_flow()).status_code == expected
    with Session(engine) as db:
        assert db.query(ApprovalFlow).count() == 1


@pytest.mark.parametrize("identity,expected", [(None, 401), (1, 403), (3, 403)])
def test_unprivileged_flow_mutations_never_write(approval_http, identity, expected):
    client, prefix, engine = approval_http
    if identity is not None:
        client.cookies.set("session_id", f"session-{identity}")
    client.headers["X-User-ID"] = "2"
    for method, path, body in (
        ("POST", "/flows", _new_flow()),
        ("PUT", "/flows/1", {"flow_name": "Overwritten"}),
        ("PATCH", "/flows/1/active", {"is_active": False}),
        ("DELETE", "/flows/1", None),
    ):
        assert client.request(method, prefix + path, json=body).status_code == expected
    assert client.get(prefix + "/users").status_code == expected
    assert client.post("/api/approval/process-timeouts").status_code == expected
    assert client.get("/api/approval/users/2/orphan-check").status_code == expected
    with Session(engine) as db:
        flow = db.get(ApprovalFlow, 1)
        assert (flow.flow_name, flow.is_active, flow.is_deleted) == ("Unchanged", True, False)
        assert db.query(ApprovalFlow).count() == 1
        assert db.execute(text("SELECT count(*) FROM ai_action_audit")).scalar_one() == 0


def test_admin_lifecycle_preserves_verified_actor(approval_http):
    client, prefix, engine = approval_http
    client.cookies.set("session_id", "session-2")
    client.headers["X-User-ID"] = "999"
    created = client.post(prefix + "/flows", json=_new_flow())
    assert created.status_code == 200
    flow_id = created.json()["data"]["id"]
    assert client.post(prefix + "/flows", json=_new_flow()).status_code == 409
    assert client.post(prefix + "/flows", json={}).status_code == 400
    assert (
        client.put(prefix + f"/flows/{flow_id}", json={"flow_name": "Updated"}).status_code == 200
    )
    assert (
        client.patch(prefix + f"/flows/{flow_id}/active", json={"is_active": False}).status_code
        == 200
    )
    assert client.get(prefix + "/users").status_code == 200
    with Session(engine) as db:
        flow = db.get(ApprovalFlow, flow_id)
        assert (flow.created_by, flow.flow_name, flow.is_active) == (2, "Updated", False)
        assert set(db.execute(text("SELECT actor FROM ai_action_audit")).scalars()) == {"2"}
    assert client.delete(prefix + f"/flows/{flow_id}").status_code == 200
    with Session(engine) as db:
        assert db.get(ApprovalFlow, flow_id).is_deleted is True


@pytest.mark.parametrize("status", ["pending", "in_progress"])
def test_global_flow_cannot_be_deleted_while_any_tenant_has_live_requests(approval_http, status):
    client, prefix, engine = approval_http
    with Session(engine) as db:
        db.add(
            ApprovalRequest(
                request_no="synthetic-pending",
                tenant_id=10,
                flow_id=1,
                applicant_id=1,
                business_type="general",
                title="Pending",
                status=status,
            )
        )
        db.commit()
    client.cookies.set("session_id", "session-2")
    assert client.delete(prefix + "/flows/1").status_code == 409
    with Session(engine) as db:
        assert db.get(ApprovalFlow, 1).is_deleted is False


def test_disabled_user_cannot_retain_identified_access_or_fall_back_to_header(
    approval_http, monkeypatch
):
    client, _, _ = approval_http
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    client.headers["X-User-ID"] = "2"
    client.cookies.set("session_id", "session-1")
    active = client.get("/identified")
    assert active.status_code == 200 and active.json()["user_id"] == 1
    client.cookies.set("session_id", "session-3")
    inactive = client.get("/identified")
    assert inactive.status_code == 403
    assert inactive.json()["detail"]["message"]["code"] == "ACCOUNT_DISABLED"
