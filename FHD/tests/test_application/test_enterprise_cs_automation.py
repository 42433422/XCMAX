from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.enterprise_cs_automation import EnterpriseCsAutomationService
from app.application.im_app_service import ImApplicationService
from app.db.models.im import (
    ImConversation,
    ImConversationMember,
    ImCustomerServiceAutomationState,
    ImMessage,
)
from app.db.models.user import Session as UserSession
from app.db.models.user import User


@pytest.fixture()
def cs_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'enterprise-cs.db'}")
    User.__table__.create(engine, checkfirst=True)
    UserSession.__table__.create(engine, checkfirst=True)
    ImConversation.__table__.create(engine, checkfirst=True)
    ImConversationMember.__table__.create(engine, checkfirst=True)
    ImMessage.__table__.create(engine, checkfirst=True)
    ImCustomerServiceAutomationState.__table__.create(engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    session.add(
        User(
            id=7,
            username="enterprise-customer",
            password="!",
            display_name="企业客户",
            is_active=True,
            tier="enterprise",
            account_tier="pro",
        )
    )
    session.commit()
    monkeypatch.setattr(
        ImApplicationService, "_record_im_message_change", lambda *_args, **_kwargs: 1
    )
    monkeypatch.setattr(ImApplicationService, "_record_im_read_change", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        ImApplicationService, "_maybe_push_cs_message", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("app.application.enterprise_cs_automation._audit", lambda **_kwargs: None)
    yield session
    session.close()


def _conversation(cs_db):
    svc = ImApplicationService(cs_db)
    cs = svc._ensure_enterprise_dedicated_cs_user()
    assert cs is not None
    conv = svc.get_or_create_direct(7, int(cs.id))
    return svc, int(cs.id), int(conv["id"])


@pytest.mark.asyncio
async def test_low_risk_message_gets_ai_reply_in_same_conversation(
    cs_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, cs_id, conversation_id = _conversation(cs_db)
    customer_message = svc.send_message(
        conversation_id, 7, "安装后怎么首次登录？", origin="customer"
    )["message"]

    observed: dict[str, object] = {}

    async def fake_completion(messages, **kwargs):
        observed["messages"] = messages
        observed["kwargs"] = kwargs
        return {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "action": "reply",
                                "reply": "请打开已安装客户端并使用购买账号完成首次登录。",
                                "summary": "客户咨询首次登录",
                                "confidence": 0.92,
                                "risk_level": "low",
                                "transfer_reason": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
        }

    monkeypatch.setattr(
        "app.infrastructure.llm.invoke.chat_completion_openai_format", fake_completion
    )
    result = await EnterpriseCsAutomationService(cs_db).handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(customer_message["id"]),
        body=customer_message["body"],
    )

    assert result["action"] == "reply"
    messages = svc.list_messages(conversation_id, cs_id, limit=20)
    assert [item["origin"] for item in messages] == ["customer", "ai"]
    assert messages[-1]["body"] == "请打开已安装客户端并使用购买账号完成首次登录。"
    state = cs_db.get(ImCustomerServiceAutomationState, conversation_id)
    assert state is not None
    assert state.mode == "ai"
    assert state.status == "ai_active"
    assert state.summary == "客户咨询首次登录"
    llm_messages = observed["messages"]
    assert isinstance(llm_messages, list)
    assert "只针对 latest_customer_message" in llm_messages[0]["content"]
    prompt = json.loads(llm_messages[1]["content"])
    assert prompt["latest_customer_message"] == {
        "id": int(customer_message["id"]),
        "body": "安装后怎么首次登录？",
    }
    assert observed["kwargs"] == {
        "temperature": 0.2,
        "max_tokens": 700,
        "profile": "customer_copilot",
        "reasoning_enabled": False,
    }


@pytest.mark.asyncio
async def test_explicit_transfer_skips_llm_and_enters_existing_human_inbox(
    cs_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, cs_id, conversation_id = _conversation(cs_db)
    customer_message = svc.send_message(conversation_id, 7, "请马上转人工", origin="customer")[
        "message"
    ]

    async def forbidden_completion(*_args, **_kwargs):
        raise AssertionError("explicit handoff must not call LLM")

    monkeypatch.setattr(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        forbidden_completion,
    )
    result = await EnterpriseCsAutomationService(cs_db).handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(customer_message["id"]),
        body=customer_message["body"],
    )

    assert result["action"] == "transfer"
    assert result["cs_status"] == "human_pending"
    assert result["cs_transfer_reason"] == "客户主动要求转人工"
    messages = svc.list_messages(conversation_id, cs_id, limit=20)
    assert [item["origin"] for item in messages] == ["customer", "system"]
    assert "转接人工客服" in messages[-1]["body"]


@pytest.mark.asyncio
async def test_high_risk_request_fails_closed_to_human(cs_db) -> None:
    svc, _cs_id, conversation_id = _conversation(cs_db)
    customer_message = svc.send_message(
        conversation_id, 7, "我要退款并修改永久套餐权益", origin="customer"
    )["message"]
    result = await EnterpriseCsAutomationService(cs_db).handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(customer_message["id"]),
        body=customer_message["body"],
    )

    assert result["action"] == "transfer"
    assert result["cs_mode"] == "human"
    assert "高风险" in result["cs_transfer_reason"]


@pytest.mark.asyncio
async def test_ai_failure_fails_closed_to_human(cs_db, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, _cs_id, conversation_id = _conversation(cs_db)
    customer_message = svc.send_message(
        conversation_id, 7, "安装后在哪里登录？", origin="customer"
    )["message"]

    async def unavailable_completion(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        unavailable_completion,
    )
    result = await EnterpriseCsAutomationService(cs_db).handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(customer_message["id"]),
        body=customer_message["body"],
    )

    assert result["action"] == "transfer"
    assert result["cs_status"] == "human_pending"
    assert result["cs_transfer_reason"] == "AI服务暂时不可用"


@pytest.mark.asyncio
async def test_two_unsolved_turns_transfer_without_third_ai_reply(
    cs_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _cs_id, conversation_id = _conversation(cs_db)
    calls = 0

    async def fake_completion(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "action": "reply",
                                "reply": "我再帮您确认一个信息：当前看到的报错是什么？",
                                "summary": "客户反馈问题未解决",
                                "confidence": 0.9,
                                "risk_level": "low",
                                "transfer_reason": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        fake_completion,
    )
    automation = EnterpriseCsAutomationService(cs_db)
    first = svc.send_message(conversation_id, 7, "还是不行，能再看看吗", origin="customer")[
        "message"
    ]
    first_result = await automation.handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(first["id"]),
        body=first["body"],
    )
    assert first_result["action"] == "reply"

    second = svc.send_message(conversation_id, 7, "还是不行，没解决", origin="customer")["message"]
    second_result = await automation.handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(second["id"]),
        body=second["body"],
    )

    assert second_result["action"] == "transfer"
    assert second_result["cs_transfer_reason"] == "客户连续反馈AI未解决问题"
    assert calls == 1


@pytest.mark.asyncio
async def test_manual_takeover_stops_ai_and_preserves_operator_provenance(
    cs_db,
) -> None:
    svc, _cs_id, conversation_id = _conversation(cs_db)
    automation = EnterpriseCsAutomationService(cs_db)
    automation.set_mode(conversation_id, "human", operator_user_id=99)
    customer_message = svc.send_message(conversation_id, 7, "普通功能怎么用", origin="customer")[
        "message"
    ]
    skipped = await automation.handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(customer_message["id"]),
        body=customer_message["body"],
    )
    assert skipped["reason"] == "human_mode"

    svc.cs_reply(
        conversation_id,
        "人工答复",
        origin="manual",
        operator_user_id=99,
    )
    manual = cs_db.execute(
        select(ImMessage).where(
            ImMessage.conversation_id == conversation_id,
            ImMessage.origin == "manual",
        )
    ).scalar_one()
    assert manual.operator_user_id == 99
