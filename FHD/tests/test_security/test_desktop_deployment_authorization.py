"""Desktop deployment settings never expose remote credentials or accept anonymous writes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes.desktop_runtime import router
from app.middleware.csrf import CSRFMiddleware
from app.utils.time import utc_now_naive
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def deployment_http(tmp_path, monkeypatch, trusted_actor):
    owner = trusted_actor(role="user", tier="enterprise")
    disabled = trusted_actor(role="user", tier="enterprise")
    expired = trusted_actor(role="user", tier="enterprise")
    with owner.factory.begin() as db:
        db.get(User, disabled.user_id).is_active = False
        db.get(UserSession, expired.session_row_id).expires_at = (
            utc_now_naive() - timedelta(seconds=1)
        )

    data_dir = tmp_path / "desktop-data"
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_dir))
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        client.get("/csrf-init")
        client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
        yield client, data_dir, {"owner": owner, "disabled": disabled, "expired": expired}


@pytest.mark.parametrize(
    ("actor", "expected"),
    [
        ("anonymous", 401),
        ("forged", 401),
        ("expired", 401),
        ("disabled", 403),
    ],
)
def test_untrusted_caller_cannot_read_or_change_deployment(deployment_http, actor, expected):
    client, data_dir, actors = deployment_http
    if actor == "forged":
        headers = {"X-Session-ID": "invalid", "X-User-ID": str(actors["owner"].user_id)}
    elif actor == "anonymous":
        headers = {}
    else:
        headers = actors[actor].headers

    assert client.get("/api/desktop/deployment", headers=headers).status_code == expected
    result = client.put("/api/desktop/deployment", headers=headers, json={"mode": "performance"})
    assert result.status_code == expected, result.text
    assert not (data_dir / "config" / "database.json").exists()
    assert not (data_dir / "config" / "deployment.json").exists()


def test_logged_in_desktop_user_can_configure_without_leaking_pg_password(deployment_http):
    client, data_dir, actors = deployment_http
    secret = "synthetic-secret-should-never-be-in-http"
    dsn = f"postgresql+psycopg://demo:{secret}@db.example:5432/product"
    headers = actors["owner"].headers

    updated = client.put(
        "/api/desktop/deployment",
        headers=headers,
        json={"mode": "performance", "postgresUrl": dsn},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["success"] is True
    assert updated.json()["restartRequired"] is True
    assert secret not in updated.text
    assert "<postgres-url>" in updated.json()["syncPlan"]["syncCommand"]

    read = client.get("/api/desktop/deployment", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["currentMode"] == "performance"
    assert secret not in read.text
    assert "<postgres-url>" in read.json()["syncPlan"]["syncCommand"]
    assert dsn in (data_dir / "config" / "database.json").read_text(encoding="utf-8")


def test_web_runtime_must_not_read_or_change_desktop_profiles(deployment_http, monkeypatch):
    client, data_dir, actors = deployment_http
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    headers = actors["owner"].headers
    assert client.get("/api/desktop/deployment", headers=headers).status_code == 403
    assert (
        client.put("/api/desktop/deployment", headers=headers, json={"mode": "safe"})
        .status_code
        == 403
    )
    assert not (data_dir / "config" / "database.json").exists()
