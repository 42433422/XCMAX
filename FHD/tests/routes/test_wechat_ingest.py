"""微信聊天记录摄取基建测试：幂等、身份解析、回流上下文、token 认证。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.application import wechat_ingest_service
from app.db.base import Base
from app.db.models.customer import Customer
from app.db.models.wechat_sync import WechatContact, WechatMessage
from app.fastapi_routes import wechat_ingest


@pytest.fixture()
def client_and_session_factory(tmp_path: Path, monkeypatch):
    """独立 SQLite：仅建本基建相关表；service 的 session 工厂指向测试引擎。"""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'wechat_sync_test.db'}")
    Base.metadata.create_all(
        engine, tables=[WechatContact.__table__, WechatMessage.__table__, Customer.__table__]
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(wechat_ingest_service, "_open_session", lambda: factory())

    app = FastAPI()
    app.include_router(wechat_ingest.router)
    test_client = TestClient(app)
    test_client.__enter__()
    yield test_client, factory
    test_client.__exit__(None, None, None)


def _ingest_payload() -> dict:
    return {
        "tenant_id": 7,
        "contacts": [{"contact_key": "白龙马^_^李秋林", "display_name": "白龙马^_^李秋林"}],
        "messages": [
            {
                "contact_key": "白龙马^_^李秋林",
                "role": "other",
                "content": "尾款什么时候结",
                "client_seq": 1,
            },
            {
                "contact_key": "白龙马^_^李秋林",
                "role": "self",
                "content": "本周五前安排",
                "client_seq": 2,
            },
        ],
    }


def test_ingest_idempotent_and_context_backflow(client_and_session_factory, monkeypatch) -> None:
    client, _ = client_and_session_factory
    monkeypatch.setattr(wechat_ingest, "_auth", lambda *args, **kwargs: None)

    first = client.post("/api/ops/wechat/ingest", json=_ingest_payload())
    assert first.status_code == 200
    body = first.json()
    assert body["success"] is True
    assert body["contacts_upserted"] == 1
    assert body["messages_inserted"] == 2
    assert body["messages_skipped"] == 0

    # 回流上下文：第二载体拿到的客户情报
    context = body["context"]["白龙马^_^李秋林"]
    assert context["known"] is True
    assert context["message_count"] == 2
    assert [m["content"] for m in context["recent_messages"]] == [
        "尾款什么时候结",
        "本周五前安排",
    ]

    # 幂等：同一批重复上行 → 全部去重
    second = client.post("/api/ops/wechat/ingest", json=_ingest_payload())
    assert second.status_code == 200
    body2 = second.json()
    assert body2["messages_inserted"] == 0
    assert body2["messages_skipped"] == 2
    assert body2["context"]["白龙马^_^李秋林"]["message_count"] == 2


def test_same_text_different_seq_both_stored(client_and_session_factory, monkeypatch) -> None:
    """同文重复消息（不同 client_seq）必须都入库——聊天里连发两条『好的』是常态。"""
    client, _ = client_and_session_factory
    monkeypatch.setattr(wechat_ingest, "_auth", lambda *args, **kwargs: None)
    payload = {
        "tenant_id": 1,
        "contacts": [{"contact_key": "c1", "display_name": "客户一"}],
        "messages": [
            {"contact_key": "c1", "role": "other", "content": "好的", "client_seq": 1},
            {"contact_key": "c1", "role": "other", "content": "好的", "client_seq": 2},
        ],
    }
    body = client.post("/api/ops/wechat/ingest", json=payload).json()
    assert body["messages_inserted"] == 2
    assert body["context"]["c1"]["message_count"] == 2


def test_auto_link_customer_by_display_name(client_and_session_factory, monkeypatch) -> None:
    client, factory = client_and_session_factory
    monkeypatch.setattr(wechat_ingest, "_auth", lambda *args, **kwargs: None)
    with factory() as session:
        session.add(
            Customer(
                customer_name="白龙马^_^李秋林",
                contact_person="李秋林",
                tenant_id=7,
            )
        )
        session.commit()

    body = client.post("/api/ops/wechat/ingest", json=_ingest_payload()).json()
    context = body["context"]["白龙马^_^李秋林"]
    assert context["contact"]["match_status"] == "auto_linked"
    assert context["customer"] is not None
    assert context["customer"]["name"] == "白龙马^_^李秋林"


def test_manual_link_and_contacts_list(client_and_session_factory, monkeypatch) -> None:
    client, factory = client_and_session_factory
    monkeypatch.setattr(wechat_ingest, "_auth", lambda *args, **kwargs: None)
    payload = {
        "tenant_id": 1,
        "contacts": [{"contact_key": "sunbird", "display_name": "太阳鸟负责人"}],
        "messages": [],
    }
    client.post("/api/ops/wechat/ingest", json=payload)

    with factory() as session:
        customer = Customer(customer_name="太阳鸟实业", tenant_id=1)
        session.add(customer)
        session.flush()
        customer_id = customer.id
        session.commit()

    link = client.post("/api/ops/wechat/contacts/sunbird/link", json={"customer_id": customer_id})
    assert link.status_code == 200
    assert link.json()["match_status"] == "manual_linked"

    listing = client.get("/api/ops/wechat/contacts").json()
    assert listing["success"] is True
    assert any(item["contact_key"] == "sunbird" for item in listing["items"])

    context = client.get("/api/ops/wechat/context", params={"contact_key": "sunbird"}).json()
    assert context["known"] is True
    assert context["customer"]["name"] == "太阳鸟实业"


def test_ingest_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "secret-token")
    app = FastAPI()
    app.include_router(wechat_ingest.router)
    client = TestClient(app)
    client.__enter__()
    try:
        denied = client.post("/api/ops/wechat/ingest", json={"contacts": [], "messages": []})
        assert denied.status_code == 401
        granted = client.post(
            "/api/ops/wechat/ingest",
            json={"contacts": [], "messages": []},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert granted.status_code == 200
        assert granted.json()["success"] is True
    finally:
        client.__exit__(None, None, None)


def test_unknown_contact_context_is_known_false(client_and_session_factory, monkeypatch) -> None:
    client, _ = client_and_session_factory
    monkeypatch.setattr(wechat_ingest, "_auth", lambda *args, **kwargs: None)
    body = client.get("/api/ops/wechat/context", params={"contact_key": "nobody"}).json()
    assert body["success"] is True
    assert body["known"] is False
