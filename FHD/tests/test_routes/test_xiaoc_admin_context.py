from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domain.shared_services.user_memory_service as memory_module
from app.application import desktop_admin_gate, persona_style_inject
from app.application.user_memory import projections
from app.db.models import User
from app.db.models.user import Session as UserSession
from app.fastapi_routes import xiaoc_admin_context as bridge
from app.utils.time import utc_now_naive


@pytest.fixture
def setup_bridge(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        for local, market, tenant in [(7, 42, 11), (8, 43, 12)]:
            db.add(
                User(
                    id=local,
                    username=f"user{local}",
                    password="",
                    tier="admin",
                    tenant_id=tenant,
                    market_user_id=market,
                )
            )
            db.add(
                UserSession(
                    session_id=str(local),
                    user_id=local,
                    expires_at=utc_now_naive() + timedelta(days=1),
                    account_kind="admin",
                    market_user_id=market,
                    market_is_admin=True,
                    tenant_id=tenant,
                )
            )
    monkeypatch.setattr(bridge, "HostSessionLocal", sessions)
    monkeypatch.setattr(desktop_admin_gate, "is_desktop_runtime", lambda: False)
    monkeypatch.setenv("XIAOC_ADMIN_CONTEXT_TOKEN", "test-bridge-key")
    monkeypatch.setattr(memory_module, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(memory_module, "JSON_MEMORY_PATH", str(tmp_path / "memories.json"))
    memory_module.reset_user_memory_service()
    monkeypatch.setattr(projections, "_write_current_projection", lambda *args: {})
    index = Mock(enabled=False)
    monkeypatch.setattr(bridge, "get_long_term_memory", lambda: index)
    style = Mock(return_value="偏好短句")
    monkeypatch.setattr(persona_style_inject, "persona_style_for_user", style)
    app = FastAPI()
    app.include_router(bridge.router)
    with TestClient(app) as client:
        yield client, sessions, index, style
    memory_module.reset_user_memory_service()
    engine.dispose()


def _call(client, operation, *, market=42, token="test-bridge-key", **fields):
    return client.post(
        "/api/internal/xiaoc-admin/context",
        headers={"X-Internal-Api-Key": token},
        json={"market_user_id": market, "operation": operation, **fields},
    )


def test_management_memory_uses_authoritative_records_and_local_owner(setup_bridge):
    client, _, index, style = setup_bridge
    assert _call(client, "list", token="wrong").status_code == 403
    assert _call(client, "list", market=7).status_code == 403

    record = _call(
        client, "save", memory={"key": "交付", "statement": "交付验收前不要承诺发货日期"}
    ).json()["memory"]
    assert record["source"] == "settings_ui"
    assert _call(client, "list", market=43).json()["memories"] == []
    assert _call(client, "delete", market=43, memory_id=record["memory_id"]).status_code == 404
    index.enabled = True
    _, owner = bridge._owner(42)
    index.recall.return_value = [
        {
            "content": "索引文本不是证据",
            "metadata": {
                "source_memory_id": record["memory_id"],
                "source_revision": record["revision"],
                "source_owner_id": owner,
            },
        }
    ]
    recalled = _call(client, "recall", query="交付").json()
    assert recalled == {"style": "偏好短句", "statements": [record["statement"]]}
    style.assert_called_once_with(7)
    corrected = _call(
        client,
        "correct",
        memory_id=record["memory_id"],
        memory={"key": "交付", "statement": "交付验收前先确认测试报告"},
    ).json()["memory"]
    assert corrected["revision"] > record["revision"]
    assert _call(client, "recall", query="交付").json()["statements"] == [corrected["statement"]]
    assert _call(client, "delete", memory_id=record["memory_id"]).json() == {"success": True}
    assert _call(client, "recall", query="交付").json()["statements"] == []


@pytest.mark.parametrize(
    ("attrs", "status"),
    [
        ({"market_is_admin": False}, 403),
        ({"impersonating_market_user_id": 43}, 403),
        ({"expires_at": utc_now_naive() - timedelta(seconds=1)}, 403),
        ({"tenant_id": 12}, 403),
    ],
)
def test_bridge_rejects_invalid_market_session_bindings(setup_bridge, attrs, status):
    client, sessions, _, style = setup_bridge
    with sessions.begin() as db:
        row = db.query(UserSession).filter_by(session_id="7").one()
        for key, value in attrs.items():
            setattr(row, key, value)
    assert _call(client, "recall", query="交付").status_code == status
    style.assert_not_called()


def test_two_market_actors_cannot_reuse_one_local_persona(setup_bridge):
    client, sessions, _, style = setup_bridge
    with sessions.begin() as db:
        db.add(
            UserSession(
                session_id="other-admin",
                user_id=7,
                market_user_id=99,
                tenant_id=11,
                market_is_admin=True,
                account_kind="admin",
                expires_at=utc_now_naive() + timedelta(days=1),
            )
        )
    assert _call(client, "recall", market=42).status_code == 403
    assert _call(client, "recall", market=99).status_code == 403
    style.assert_not_called()


def test_legacy_session_rebinding_never_reuses_local_persona(setup_bridge):
    client, sessions, _, style = setup_bridge
    with sessions.begin() as db:
        db.get(User, 7).market_user_id = None

    record = _call(
        client, "save", memory={"key": "交付", "statement": "账号42的私有交付记录"}
    ).json()["memory"]
    original_context = _call(client, "recall", query="交付").json()
    assert original_context["statements"] == [record["statement"]]
    with sessions.begin() as db:
        db.query(UserSession).filter_by(session_id="7").one().expires_at = (
            utc_now_naive() - timedelta(seconds=1)
        )
        db.add(
            UserSession(
                session_id="replacement-admin",
                user_id=7,
                market_user_id=99,
                tenant_id=11,
                market_is_admin=True,
                account_kind="admin",
                expires_at=utc_now_naive() + timedelta(days=1),
            )
        )
    assert _call(client, "recall", market=99, query="交付").json() == {
        "style": "",
        "statements": [],
    }
    assert _call(client, "list", market=99).json()["memories"] == []
    assert _call(client, "delete", market=99, memory_id=record["memory_id"]).status_code == 404
    assert _call(client, "recall", query="交付").status_code == 403
    assert original_context["style"] == ""
    style.assert_not_called()
