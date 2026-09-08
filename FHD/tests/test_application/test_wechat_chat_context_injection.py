"""微信联系人情报注入 AI 对话的测试：解析命中、显式指定、异常降级、prompt 渲染。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import wechat_ingest_service
from app.application.ai_chat_app_service_aichatapplicationservice_mixin01__aichatapplicationservicepart01mixin_mixin02 import (
    __AIChatApplicationServicePart01MixinPart02Mixin as _ChatMixin,
)
from app.application.wechat_chat_context import resolve_wechat_chat_context
from app.db.base import Base
from app.db.models.customer import Customer
from app.db.models.wechat_sync import WechatContact, WechatMessage
from app.services.conversation.prompts import PromptsMixin


@pytest.fixture()
def wechat_db(tmp_path: Path, monkeypatch):
    """独立 SQLite：建微信同步三表；ingest service 的会话工厂指向测试引擎。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'wechat_chat_ctx_test.db'}")
    Base.metadata.create_all(
        engine, tables=[WechatContact.__table__, WechatMessage.__table__, Customer.__table__]
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(wechat_ingest_service, "_open_session", lambda: factory())
    return factory


def _seed_linked_contact(factory) -> None:
    with factory() as session:
        customer = Customer(customer_name="白龙马实业", contact_person="李秋林", tenant_id=7)
        session.add(customer)
        session.flush()
        contact = WechatContact(
            contact_key="白龙马^_^李秋林",
            display_name="白龙马^_^李秋林",
            customer_id=customer.id,
            match_status="auto_linked",
            tenant_id=7,
        )
        session.add(contact)
        session.flush()
        session.add(
            WechatMessage(
                contact_id=contact.id,
                role="other",
                content="尾款什么时候结",
                msg_ts=datetime(2026, 9, 5, 10, 0, 0, tzinfo=UTC),
                source="db",
                dedupe_hash="h1",
                tenant_id=7,
            )
        )
        session.add(
            WechatMessage(
                contact_id=contact.id,
                role="self",
                content="本周五前安排",
                msg_ts=datetime(2026, 9, 5, 10, 1, 0, tzinfo=UTC),
                source="db",
                dedupe_hash="h2",
                tenant_id=7,
            )
        )
        session.commit()


def test_auto_match_contact_by_message_text(wechat_db) -> None:
    _seed_linked_contact(wechat_db)
    payload = resolve_wechat_chat_context("白龙马^_^李秋林的尾款怎么催？", {"tenant_id": 7})
    assert payload is not None
    assert payload["matched_by"] == "auto_match"
    assert payload["contact"]["match_status"] == "auto_linked"
    assert payload["customer"]["name"] == "白龙马实业"
    assert [m["content"] for m in payload["recent_messages"]] == [
        "尾款什么时候结",
        "本周五前安排",
    ]
    assert payload["message_count"] == 2


def test_explicit_contact_key_wins(wechat_db) -> None:
    _seed_linked_contact(wechat_db)
    payload = resolve_wechat_chat_context(
        "帮我看看他聊到哪了", {"tenant_id": 7, "wechat_contact_key": "白龙马^_^李秋林"}
    )
    assert payload is not None
    assert payload["matched_by"] == "explicit"
    assert payload["customer"] is not None


def test_no_match_returns_none(wechat_db) -> None:
    _seed_linked_contact(wechat_db)
    assert resolve_wechat_chat_context("今天天气怎么样", {"tenant_id": 7}) is None


def test_resolver_swallows_errors(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(wechat_ingest_service, "list_wechat_contacts", _boom)
    assert resolve_wechat_chat_context("白龙马在吗", {"tenant_id": 7}) is None


def test_inject_mixin_sets_none_on_miss(wechat_db) -> None:
    _seed_linked_contact(wechat_db)
    mixin = object.__new__(_ChatMixin)
    enriched = mixin._inject_wechat_contact_context("无关消息", {"tenant_id": 7, "keep": 1})
    # 未命中显式置 None：防止 request_context 跨轮合并时残留上一轮情报
    assert enriched["wechat_contact_context"] is None
    assert enriched["keep"] == 1


def test_inject_mixin_enriches_on_hit(wechat_db) -> None:
    _seed_linked_contact(wechat_db)
    mixin = object.__new__(_ChatMixin)
    enriched = mixin._inject_wechat_contact_context("白龙马^_^李秋林问到尾款了", {"tenant_id": 7})
    assert isinstance(enriched["wechat_contact_context"], dict)
    assert enriched["wechat_contact_context"]["customer"]["name"] == "白龙马实业"


def test_prompt_block_rendered_and_excluded_from_extra() -> None:
    pm = PromptsMixin()
    payload = {
        "contact_key": "白龙马^_^李秋林",
        "matched_by": "auto_match",
        "contact": {"display_name": "白龙马^_^李秋林", "match_status": "auto_linked"},
        "customer": {"name": "白龙马实业", "contact_person": "李秋林"},
        "recent_messages": [
            {"role": "other", "content": "尾款什么时候结", "msg_ts": "2026-09-05T10:00:00+00:00"},
            {"role": "self", "content": "本周五前安排", "msg_ts": "2026-09-05T10:01:00+00:00"},
        ],
        "message_count": 2,
    }
    rendered = pm._format_request_context_for_system({"wechat_contact_context": payload})
    assert "【微信联系人情报" in rendered
    assert "白龙马实业" in rendered
    assert "尾款什么时候结" in rendered
    assert "机主：本周五前安排" in rendered
    assert "严禁编造" in rendered
    # 专用块渲染后不得再落入【附加上下文】原始 JSON
    assert "wechat_contact_context" not in rendered


def test_prompt_block_none_payload_is_skipped() -> None:
    pm = PromptsMixin()
    rendered = pm._format_request_context_for_system({"wechat_contact_context": None})
    assert "【微信联系人情报" not in rendered
