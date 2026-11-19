"""Regression: WeChat ingestion and context must not cross tenant boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.wechat_chat_context import resolve_wechat_chat_context
from app.application.wechat_ingest_service import (
    _dedupe_hash,
    build_contact_context,
    ingest_wechat_payload,
    link_wechat_contact,
)
from app.db.db_base import Base
from app.db.models.customer import Customer
from app.db.models.wechat_sync import WechatContact, WechatMessage


@pytest.fixture()
def store(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'wechat_scope.db'}")
    Base.metadata.create_all(
        engine, tables=[WechatContact.__table__, WechatMessage.__table__, Customer.__table__]
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _ingest(factory, tenant_id: int, content: str) -> dict:
    with factory() as session:
        return ingest_wechat_payload(
            {
                "tenant_id": tenant_id,
                "contacts": [{"contact_key": "shared", "display_name": "共享昵称"}],
                "messages": [
                    {"contact_key": "shared", "role": "other", "content": content, "client_seq": 1}
                ],
            },
            session=session,
        )


def test_same_contact_key_has_independent_messages_and_dedupe(store) -> None:
    first = _ingest(store, 7, "identical text")
    second = _ingest(store, 8, "identical text")
    assert first["messages_inserted"] == second["messages_inserted"] == 1

    with store() as session:
        contacts = session.scalars(
            select(WechatContact).where(WechatContact.contact_key == "shared")
        ).all()
        assert {c.tenant_id for c in contacts} == {7, 8}
        for contact in contacts:
            messages = session.scalars(
                select(WechatMessage).where(WechatMessage.contact_id == contact.id)
            ).all()
            assert len(messages) == 1
            assert messages[0].tenant_id == contact.tenant_id

    replay = _ingest(store, 8, "identical text")
    assert replay["messages_inserted"] == 0
    assert replay["messages_skipped"] == 1


def test_other_tenant_message_is_not_appended_to_first_matching_contact(store) -> None:
    _ingest(store, 7, "tenant seven secret")
    second = _ingest(store, 8, "tenant eight secret")
    assert second["messages_inserted"] == 1
    with store() as session:
        for tenant_id, expected in ((7, "tenant seven secret"), (8, "tenant eight secret")):
            payload = build_contact_context("shared", tenant_id=tenant_id, session=session)
            assert [m["content"] for m in payload["recent_messages"]] == [expected]
        assert build_contact_context("shared", session=session)["known"] is False


def test_contact_binding_does_not_cross_tenant_or_guess_an_ambiguous_key(store) -> None:
    with store() as session:
        customers = [
            Customer(customer_name=f"Company {tenant}", tenant_id=tenant)
            for tenant in (7, 8)
        ]
        session.add_all(customers)
        session.add_all(
            [WechatContact(contact_key="shared", display_name="shared", tenant_id=tenant)
             for tenant in (7, 8)]
        )
        session.commit()

        assert link_wechat_contact("shared", customers[1].id, session=session)[
            "error_code"
        ] == "ambiguous_tenant"
        denied = link_wechat_contact(
            "shared", customers[1].id, tenant_id=7, session=session
        )
        assert denied["success"] is False
        assert denied["error_code"] == "not_found"
        linked = link_wechat_contact(
            "shared", customers[1].id, tenant_id=8, session=session
        )
        assert linked["success"] is True
        assert build_contact_context("shared", tenant_id=8, session=session)["customer"][
            "name"
        ] == "Company 8"
        assert build_contact_context("shared", tenant_id=7, session=session)["customer"] is None


def test_historical_dedupe_hash_replay_is_preserved_in_same_tenant(store) -> None:
    with store() as session:
        contact = WechatContact(contact_key="shared", display_name="shared", tenant_id=7)
        session.add(contact)
        session.flush()
        session.add(
            WechatMessage(
                contact_id=contact.id, tenant_id=7, role="other", content="old message",
                source="db", dedupe_hash=_dedupe_hash("shared", "other", "old message", 1),
            )
        )
        session.commit()
    result = _ingest(store, 7, "old message")
    assert result["messages_inserted"] == 0
    assert result["messages_skipped"] == 1


def test_corrupt_cross_tenant_customer_and_message_rows_remain_hidden(store) -> None:
    with store() as session:
        foreign = Customer(customer_name="private customer", tenant_id=8)
        session.add(foreign)
        session.flush()
        contact = WechatContact(
            contact_key="shared",
            display_name="shared",
            tenant_id=7,
            customer_id=foreign.id,
            match_status="manual_linked",
        )
        session.add(contact)
        session.flush()
        # Legacy cross-tenant message rows may already reference this contact.
        session.add(
            WechatMessage(
                contact_id=contact.id,
                tenant_id=8,
                role="other",
                content="foreign tenant secret",
                source="db",
                dedupe_hash="foreign-tenant-corrupt-row",
            )
        )
        session.commit()
        payload = build_contact_context("shared", tenant_id=7, session=session)
        assert payload["customer"] is None
        assert payload["recent_messages"] == []
        assert payload["message_count"] == 0


def test_ai_context_fails_closed_without_tenant_identity() -> None:
    assert resolve_wechat_chat_context("共享昵称的消息", {}) is None
    assert resolve_wechat_chat_context(
        "共享昵称的消息", {"tenant_id": "not-a-tenant"}
    ) is None
