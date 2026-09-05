"""Retired industry POST: real session/admin checks and no account or Mod mutation."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fastapi_routes import system_routes

pytestmark = pytest.mark.release_gate


@pytest.fixture
def industry_app(tmp_path, monkeypatch):
    import app.db as database
    import app.db.session as db_session
    from app.db.base import Base
    from app.db.models.user import Session, User
    from app.utils.time import utc_now_naive

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "0")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    mods_root = tmp_path / "mods"
    manifest = mods_root / "coating-industry" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"id": "coating-industry", "version": "1.0.0", "industry": {"id": "涂料"}})
    )
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(mods_root))
    db_path = tmp_path / "industry.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    monkeypatch.setattr(db_session, "SessionLocal", sessions)
    with sessions.begin() as db:
        for uid, tier, active in (
            (1, "personal", True),
            (2, "enterprise", True),
            (3, "admin", True),
            (4, "admin", False),
        ):
            db.add(
                User(
                    id=uid,
                    username=f"industry-test-{uid}",
                    password="unused",
                    tier=tier,
                    tenant_id=10 + uid,
                    industry_id="通用",
                    is_active=active,
                    entitled_industries=["通用", "涂料"] if uid == 3 else ["通用"],
                )
            )
            db.add(
                Session(
                    session_id=f"industry-session-{uid}",
                    user_id=uid,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    account_kind="admin" if tier == "admin" else "enterprise",
                )
            )

    # A retired endpoint must not even begin catalog or mutation work. These
    # fail-if-called guards do not replace session resolution or authorization.
    guards = []
    for target in (
        "resources.config.industry_config.set_current_industry",
        "app.application.tenant_workspace_prefs.save_selected_industry",
        "app.application.tenant_workspace_prefs.bind_selected_industry_for_user",
        "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
        "app.mod_sdk.industry_seed.deactivate_other_open_industry_mods",
    ):
        guard = Mock(side_effect=AssertionError(f"retired industry route called {target}"))
        monkeypatch.setattr(target, guard)
        guards.append(guard)

    def snapshot():
        with sqlite3.connect(db_path) as db:
            rows = tuple(db.iterdump())
        files = {
            str(p.relative_to(mods_root)): p.read_bytes()
            for p in mods_root.rglob("*")
            if p.is_file()
        }
        return rows, files

    app = FastAPI()
    app.include_router(system_routes.router)
    try:
        with TestClient(app) as client:
            yield client, snapshot, guards
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "session_id, industry_id, status, code",
    [
        (None, "涂料", 401, "UNAUTHORIZED"),
        ("missing-session", "涂料", 401, "UNAUTHORIZED"),
        ("industry-session-1", "涂料", 403, "ADMIN_ONLY"),
        ("industry-session-2", "涂料", 403, "ADMIN_ONLY"),
        ("industry-session-4", "涂料", 403, "ACCOUNT_DISABLED"),
        ("industry-session-3", "涂料", 410, "INDUSTRY_SWITCH_RETIRED"),
        ("industry-session-3", "unknown-industry", 410, "INDUSTRY_SWITCH_RETIRED"),
        ("industry-session-3", "考勤", 410, "INDUSTRY_SWITCH_RETIRED"),
    ],
)
def test_retired_industry_post_preserves_auth_and_all_data(
    industry_app, session_id, industry_id, status, code
):
    client, snapshot, guards = industry_app
    before = snapshot()
    headers = {"X-User-ID": "3", "X-Tenant-ID": "13"}
    if session_id:
        headers["X-Session-ID"] = session_id
    response = client.post(
        "/api/system/industry", headers=headers, json={"industry_id": industry_id}
    )
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    actual_code = detail["code"] if status == 410 else detail["message"]["code"]
    assert actual_code == code
    if status == 410:
        assert detail["message"] == "行业由账号资料确定，该切换入口已停用。"
    assert snapshot() == before
    for guard in guards:
        guard.assert_not_called()


def test_openapi_marks_only_industry_post_retired(industry_app):
    client, _snapshot, _guards = industry_app
    operations = client.app.openapi()["paths"]["/api/system/industry"]
    assert operations["post"]["deprecated"] is True
    assert {"401", "403", "410"} <= operations["post"]["responses"].keys()
    assert "200" not in operations["post"]["responses"]
    assert not operations["get"].get("deprecated", False)
