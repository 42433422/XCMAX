"""Real SQL/outbox/HTTP/collector-adapter chain; only the Windows DB reader is replaced."""

from __future__ import annotations

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import wechat_ingest_service as ingest
from app.application import wechat_refresh_service as refresh
from app.application.agent_orchestrator.execution_identity import execution_actor_scope
from app.db.base import Base
from app.db.models.customer import Customer
from app.db.models.wechat_refresh import WechatRefreshRequest
from app.db.models.wechat_sync import WechatContact, WechatMessage
from app.fastapi_routes import wechat_ingest
from app.infrastructure.tenant_scope import tenant_scope
from app.services import tools_wechat_control as control


@pytest.fixture()
def system(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'host.sqlite'}")
    Base.metadata.create_all(
        engine,
        tables=[
            WechatRefreshRequest.__table__,
            WechatContact.__table__,
            WechatMessage.__table__,
            Customer.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(refresh, "_open_session", factory)
    monkeypatch.setattr(ingest, "_open_session", factory)
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "test-only-worker-token")
    app = FastAPI()
    app.include_router(wechat_ingest.router)
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def _call(action, params=None, key="one"):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    with tenant_scope(None):
        return AgentToolExecutor().execute(
            AgentStep(node_id="wechat", tool_id="wechat", action=action, params=params or {}),
            runtime_context={"idempotency_key": key, "user_id": "17", "tenant_id": 7},
        )


def test_outbox_scope_replay_conflict_and_lease(system, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(refresh, "time", SimpleNamespace(time=lambda: now[0]))
    first = refresh.request_refresh(7, "17", "refresh_contact_cache", "same")
    assert refresh.request_refresh(7, "17", "refresh_contact_cache", "same") == first
    with pytest.raises(ValueError, match="another action"):
        refresh.request_refresh(7, "17", "refresh_messages_cache", "same")
    assert refresh.get_refresh(8, "17", first["request_id"]) is None
    assert refresh.get_refresh(7, "18", first["request_id"]) is None
    assert refresh.claim_refresh(8) is None
    old = refresh.claim_refresh(7)
    assert old is not None
    assert refresh.claim_refresh(7) is None
    now[0] += 301
    new = refresh.claim_refresh(7)
    assert new is not None and new["lease_token"] != old["lease_token"]
    args = (7, first["request_id"])
    assert not refresh.finish_refresh(*args, old["lease_token"], {"success": True})
    assert not refresh.finish_refresh(8, first["request_id"], new["lease_token"], {"success": True})
    receipt = {"success": True, "contacts": 2, "secret": "not stored"}
    assert refresh.finish_refresh(*args, new["lease_token"], receipt)
    assert refresh.finish_refresh(*args, new["lease_token"], receipt)
    assert not refresh.finish_refresh(*args, new["lease_token"], {"success": False})
    saved = refresh.get_refresh(7, "17", first["request_id"])
    assert saved["completed"] is True
    assert "secret" not in saved["receipt"]
    assert "lease_token" not in saved


def test_concurrent_claim_has_one_winner(system):
    refresh.request_refresh(7, "17", "refresh_contact_cache", "same")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(refresh.claim_refresh, [7, 7]))
    assert sum(item is not None for item in results) == 1


def test_offline_is_not_success_and_expired_cannot_be_claimed(system, monkeypatch):
    clock = iter([0, 11])
    monkeypatch.setattr(control, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    result = _call("refresh_contact_cache")
    assert result["success"] is False
    assert result["error_code"] == "wechat_refresh_pending"
    status = _call("query", {"request_id": result["data"]["request_id"]})
    assert status["success"] is True
    assert status["data"]["completed"] is False
    monkeypatch.setattr(
        refresh, "time", SimpleNamespace(time=lambda: status["data"]["expires_at"] + 1)
    )
    assert refresh.claim_refresh(7) is None
    assert (
        _call("query", {"request_id": result["data"]["request_id"]})["data"]["state"] == "expired"
    )


def test_worker_requires_token_and_positive_tenant(system):
    client, _ = system
    assert client.post("/api/ops/wechat/refresh/claim?tenant_id=7").status_code == 401
    headers = {"Authorization": "Bearer test-only-worker-token"}
    assert (
        client.post("/api/ops/wechat/refresh/claim?tenant_id=0", headers=headers).status_code == 422
    )
    assert client.post("/api/ops/wechat/refresh/claim", headers=headers).status_code == 422


@pytest.fixture()
def collector(system, tmp_path, monkeypatch):
    client, _ = system
    path = Path(__file__).resolve().parents[2] / "tools/wechat_sync/wechat_sync.py"
    spec = importlib.util.spec_from_file_location("wechat_control_test_collector", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(module, "CONTEXT_CACHE_PATH", str(tmp_path / "context.json"))

    def post(url, token, body, timeout=60, *, path="/api/ops/wechat/ingest"):
        response = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()

    monkeypatch.setattr(module, "_post_json", post)
    settings = {
        "server_url": "http://testserver",
        "token": "test-only-worker-token",
        "tenant_id": 7,
        "contact_filter": None,
        "limit": 50,
    }
    return module, settings


@pytest.mark.parametrize("action", ["refresh_contact_cache", "refresh_messages_cache"])
def test_model_to_collector_to_sql_and_receipt(system, collector, monkeypatch, action):
    module, settings = collector
    reads = []

    def messages(*args, **kwargs):
        reads.append(True)
        return {
            "success": True,
            "messages": [{"role": "other", "text": "请确认订单", "ts": 1788800000}],
        }

    monkeypatch.setitem(
        sys.modules,
        "wechat_db_read",
        SimpleNamespace(
            get_default_wechat_data_dir=lambda: None,
            get_contact_list_from_db=lambda **kwargs: {"success": True, "contacts": ["客户甲"]},
            get_contact_and_messages_from_db=messages,
        ),
    )
    import time

    monkeypatch.setattr(
        control,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic,
            sleep=lambda _: module.poll_refresh(settings),
        ),
    )
    result = _call(action)
    assert result["success"] is True
    assert result["data"]["completed"] is True
    assert bool(reads) == (action == "refresh_messages_cache")
    contacts = _call("list")
    assert contacts["items"][0]["contact_key"] == "客户甲"
    context = _call("view", {"contact_key": "客户甲"})
    assert context["message_count"] == int(action == "refresh_messages_cache")
    # Replaying the same task reads its durable receipt; no second collection.
    assert _call(action)["data"] == result["data"]
    assert len(reads) <= 1
    with execution_actor_scope("18"), tenant_scope(8):
        denied = control.execute_wechat_control(
            "query", {"request_id": result["data"]["request_id"]}, {}, "", ""
        )
        assert denied["success"] is False
        assert control.execute_wechat_control("list", {}, {}, "", "")["items"] == []


def test_failed_collection_does_not_report_empty_success(system, collector, monkeypatch):
    module, settings = collector
    monkeypatch.setitem(
        sys.modules,
        "wechat_db_read",
        SimpleNamespace(
            get_default_wechat_data_dir=lambda: None,
            get_contact_list_from_db=lambda **kwargs: {
                "success": False,
                "message": "missing database",
            },
            get_contact_and_messages_from_db=lambda *args, **kwargs: pytest.fail(
                "must not read messages"
            ),
        ),
    )
    row = refresh.request_refresh(7, "17", "refresh_contact_cache", "failure")
    assert module.poll_refresh(settings)["success"] is False
    status = refresh.get_refresh(7, "17", row["request_id"])
    assert status["state"] == "failed" and status["completed"] is False


def test_raw_context_cannot_grant_identity(system):
    with execution_actor_scope(""), tenant_scope(None):
        result = control.execute_wechat_control(
            "list", {}, {"user_id": "17", "tenant_id": 7}, "", ""
        )
    assert result["error_code"] == "identity_required"
    assert _call("list", {"tenant_id": 8})["error_code"] == "scope_mismatch"


def test_registered_background_dispatch_restores_identity_and_tenant(system):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.infrastructure.tenant_scope import current_tenant_id

    _, factory = system
    with factory() as session:
        session.add_all(
            [
                WechatContact(contact_key="visible", display_name="账号七", tenant_id=7),
                WechatContact(contact_key="hidden", display_name="账号八", tenant_id=8),
            ]
        )
        session.commit()
    step = AgentStep(node_id="wechat", tool_id="wechat", action="list", params={})
    with execution_actor_scope(""), tenant_scope(None):
        result = AgentToolExecutor().execute(
            step, runtime_context={"user_id": "17", "tenant_id": 7}
        )
        assert result["success"] is True
        assert [row["contact_key"] for row in result["items"]] == ["visible"]
        assert current_tenant_id() is None
    with tenant_scope(8):
        denied = AgentToolExecutor().execute(step, runtime_context={"user_id": "17"})
        assert denied["error_code"] == "invalid_tenant_context"


def test_refresh_migration_is_idempotent_and_matches_model(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_09_08_wechat_refresh.py"
    spec = importlib.util.spec_from_file_location("wechat_refresh_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        columns = {
            item["name"] for item in inspect(connection).get_columns("wechat_refresh_requests")
        }
        assert columns == set(WechatRefreshRequest.__table__.columns.keys())
    engine.dispose()
