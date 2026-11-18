"""Global approval policy writes require a live platform administrator session."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application import workflow
from app.application.facades import session_facade
from app.db.db_base import Base
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes.approval import router as approval_router
from app.fastapi_routes.domains.shipment import shipment_routes
from app.infrastructure.session import session_manager
from app.middleware.csrf import CSRFMiddleware
from app.utils.time import utc_now_naive
from resources.config import approval_config


@pytest.fixture(params=["/api/ai/config/approval", "/api/approval/tool-rules"])
def policy_http(request, tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    with Session(engine) as db:
        for uid, identity, role, tier, active in (
            (1, "ordinary", "user", "enterprise", True),
            (2, "role_admin", "admin", "enterprise", True),
            (3, "disabled_admin", "admin", "admin", False),
            (4, "admin", "admin", "admin", True),
        ):
            db.add(
                User(
                    id=uid,
                    username=identity,
                    password="test-only",
                    role=role,
                    tier=tier,
                    is_active=active,
                )
            )
            db.add(
                UserSession(
                    user_id=uid,
                    session_id=identity,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
        db.commit()

    @contextmanager
    def host_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(session_manager, "get_host_db", host_db)
    monkeypatch.setattr(session_facade, "get_session_service", session_manager.SessionManager)
    path = tmp_path / "approval_config.yaml"
    monkeypatch.setattr(
        approval_config.ApprovalConfig, "_get_config_path", staticmethod(lambda: str(path))
    )
    monkeypatch.setattr(approval_config, "_approval_config", None)
    approval_config.ApprovalConfig._default_config().save()
    config = approval_config.get_approval_config()
    reload_config = Mock(wraps=approval_config.reload_approval_config)
    reload_service = Mock()
    monkeypatch.setattr(approval_config, "reload_approval_config", reload_config)
    monkeypatch.setattr(workflow, "reload_approval_service", reload_service)
    monkeypatch.setattr(
        shipment_routes, "_trace_approval_route", lambda payload, **_kwargs: payload
    )
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.include_router(shipment_routes.router)
    app.include_router(approval_router)
    try:
        with TestClient(app) as client:
            client.get(request.param)
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            yield client, request.param, path, config, reload_config, reload_service
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "identity,expected",
    [
        ("anonymous", 401),
        ("invalid", 401),
        ("ordinary", 403),
        ("role_admin", 403),
        ("disabled_admin", 403),
    ],
)
def test_unprivileged_policy_writes_have_no_effect(policy_http, identity, expected):
    client, url, path, config, reload_config, reload_service = policy_http
    if identity != "anonymous":
        client.cookies.set("session_id", identity)
    client.headers["X-User-ID"] = "2"
    before = path.read_bytes()
    before_rules = list(config.rules)
    response = client.post(
        url, json={"enabled": False, "rules": [], "user_id": "2", "tier": "admin"}
    )
    assert (
        response.status_code,
        path.read_bytes() == before,
        config.enabled,
        config.rules == before_rules,
    ) == (expected, True, True, True)
    reload_config.assert_not_called()
    reload_service.assert_not_called()


def test_platform_admin_can_persist_and_reload_policy(policy_http):
    client, url, path, _config, reload_config, reload_service = policy_http
    client.cookies.set("session_id", "admin")
    rules = [{"tool_id": "print", "action": "execute", "trigger": "always"}]
    response = client.post(url, json={"enabled": False, "rules": rules})
    assert response.status_code == 200 and response.json()["success"] is True
    saved = approval_config.ApprovalConfig.load()
    assert saved.enabled is False and saved.rules == rules
    assert path.is_file()
    reload_config.assert_called_once_with()
    reload_service.assert_called_once_with()


def test_ordinary_user_can_still_read_policy(policy_http):
    client, url, path, config, reload_config, reload_service = policy_http
    client.cookies.set("session_id", "ordinary")
    before = path.read_bytes()
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "enabled": True,
        "rules": config.rules,
        "attendance_policy": config.attendance_policy,
    }
    assert path.read_bytes() == before
    reload_config.assert_not_called()
    reload_service.assert_not_called()
