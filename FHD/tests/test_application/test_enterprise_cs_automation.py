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
            market_user_id=501,
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


@pytest.mark.asyncio
async def test_unsupported_model_retains_message_and_records_safe_failure(cs_db, monkeypatch):
    import httpx

    svc, cs_id, conversation_id = _conversation(cs_db)
    message = svc.send_message(conversation_id, 7, "怎样首次登录？", origin="customer")["message"]
    audits = []

    async def failed_completion(*_args, **_kwargs):
        request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"code": "400", "message": "Unsupported model private-model-secret"}},
        )
        response.raise_for_status()

    monkeypatch.setattr(
        "app.infrastructure.llm.invoke.chat_completion_openai_format", failed_completion
    )
    monkeypatch.setattr(
        "app.application.enterprise_cs_automation._audit", lambda **kwargs: audits.append(kwargs)
    )
    result = await EnterpriseCsAutomationService(cs_db).handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=int(message["id"]),
        body=message["body"],
    )
    assert result["action"] == "transfer"
    originals = [
        row
        for row in svc.list_messages(conversation_id, cs_id, limit=20)
        if row["origin"] == "customer"
    ]
    assert [row["id"] for row in originals] == [message["id"]]
    failure = next(row for row in audits if row["action"] == "enterprise_cs.ai_failed")
    assert failure["payload"] == {
        "conversation_id": conversation_id,
        "customer_message_id": message["id"],
        "reason": "unsupported_model",
        "status_code": 400,
    }
    assert "private-model-secret" not in json.dumps(audits)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,outcome", [("ai", "received"), ("human", "received"), ("ai", "unknown")]
)
async def test_explicit_issue_uses_authenticated_idempotent_intake_without_model(
    cs_db,
    monkeypatch,
    mode,
    outcome,
):
    from app.application import client_product_issue_intake as intake

    svc, cs_id, conversation_id = _conversation(cs_db)
    automation = EnterpriseCsAutomationService(cs_db)
    if mode == "human":
        automation.set_mode(conversation_id, mode, operator_user_id=99)
    calls = []

    async def remote(token, path, **kwargs):
        calls.append((token, path, kwargs))
        if kwargs.get("method") == "POST":
            if outcome == "unknown":
                raise ConnectionError("fixture response lost after sending")
            return {"success": True, "ticket_id": 101, "ticket_no": "CS-fixture"}
        if outcome == "unknown" and len(calls) == 2:
            return {"items": []}
        return {
            "items": [
                {
                    "id": 101,
                    "ticket_no": "CS-fixture",
                    "evidence": {
                        "source_ref": calls[0][2]["payload"]["source_ref"],
                    },
                }
            ]
        }

    async def no_model(*args, **kwargs):
        raise AssertionError("explicit intake must not invoke a model")

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    monkeypatch.setattr("app.infrastructure.llm.invoke.chat_completion_openai_format", no_model)
    text = (
        "请提交故障工单：Windows版聊天思考过久会断连、报500并整页卡死，期望页面保持可用失败后能恢复"
    )
    message = svc.send_message(conversation_id, 7, text, origin="customer")["message"]
    result = await automation.handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=message["id"],
        body="untrusted caller text is not evidence",
        market_token="fixture-customer-token",
    )
    assert result["action"] == "issue_intake"
    assert result["cs_mode"] == mode
    assert calls[0][0] == "fixture-customer-token"
    payload = calls[0][2]["payload"]
    assert "Windows版聊天思考过久会断连、报500" in payload["description"]
    assert payload["source_ref"].startswith(f"enterprise-cs:501:{conversation_id}:")
    assert "user_id" not in payload
    assert len([call for call in calls if call[2].get("method") == "POST"]) == 1
    reply = result["message"]["body"]
    assert ("CS-fixture" in reply) is (outcome == "received")
    assert ("暂无法确认" in reply) is (outcome == "unknown")
    assert "fixture-customer-token" not in json.dumps(result)
    repeated = await automation.handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=message["id"],
        body=text,
        market_token="fixture-customer-token",
    )
    assert repeated["intake"]["state"] == "RECEIVED"
    assert (repeated["message"] is not None) is (outcome == "unknown")
    followup = svc.send_message(conversation_id, 7, "提交工单", origin="customer")["message"]
    resumed = await automation.handle_customer_message(
        conversation_id=conversation_id,
        customer_user_id=7,
        message_id=followup["id"],
        body=followup["body"],
        market_token="fixture-customer-token",
    )
    assert resumed["intake"]["owner_ticket_no"] == "CS-fixture"
    assert len([call for call in calls if call[2].get("method") == "POST"]) == 1


@pytest.mark.asyncio
async def test_bare_issue_request_needs_context_and_bound_identity(cs_db, monkeypatch):
    from app.application import client_product_issue_intake as intake

    async def forbidden(*args, **kwargs):
        raise AssertionError("must not submit without description and authenticated identity")

    monkeypatch.setattr(intake, "custom_delivery_remote_json", forbidden)
    monkeypatch.setattr("app.infrastructure.llm.invoke.chat_completion_openai_format", forbidden)
    svc, cs_id, cid = _conversation(cs_db)
    automation = EnterpriseCsAutomationService(cs_db)
    for text, expected in [
        ("提交工单", "请说明"),
        ("请提交故障工单：Windows500报错卡死", "暂无法确认"),
    ]:
        message = svc.send_message(cid, 7, text, origin="customer")["message"]
        result = await automation.handle_customer_message(
            conversation_id=cid,
            customer_user_id=7,
            message_id=message["id"],
            body=text,
        )
        assert expected in result["message"]["body"]
    result = await automation.handle_customer_message(
        conversation_id=cid,
        customer_user_id=7,
        message_id=result["message"]["id"],
        body="提交工单",
        market_token="fixture-token",
    )
    assert result["reason"] == "invalid_customer_message"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clarification,submit",
    [
        ("客户端信息页点击提交后报错，无法提交", True),
        ("客户端报错：not found", True),
        ("客户端无法取消订单，点击取消按钮报错", True),
        ("查询按钮点击报错，客户端没反应", True),
        ("请提交工单：取消按钮失效，查询按钮报错", True),
        ("旧问题已经解决，现在客户端保存报错", True),
        ("不用了，问题已经解决了", False),
        ("不要提交问题工单", False),
        ("取消建单，客户端报错已经恢复正常", False),
        ("取消提交工单：客户端报错", False),
        ("请提交工单，问题已经解决了", False),
        ("现在有多少客户？", False),
        ("查询目前失败的订单", False),
        ("查询提交工单失败的订单", False),
    ],
)
async def test_issue_description_answers_pending_clarification(
    cs_db, monkeypatch, clarification, submit
):
    from app.application import client_product_issue_intake as intake

    calls = []
    readbacks = []

    async def receive(token, report, missing, **kwargs):
        calls.append((token, report))
        readbacks.append(kwargs["readback_only"])
        return {"state": "RECEIVED", "owner_ticket_no": "CS-clarification"}

    async def completion(*args, **kwargs):
        assert not submit, "issue clarification must continue the pending intake"
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "action": "reply",
                                "reply": "已了解您的当前要求。",
                                "confidence": 0.9,
                                "risk_level": "low",
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(intake, "receive_pending_report", receive)
    monkeypatch.setattr("app.infrastructure.llm.invoke.chat_completion_openai_format", completion)
    svc, _, cid = _conversation(cs_db)
    automation = EnterpriseCsAutomationService(cs_db)
    for text in ("提交工单", "提交工单", clarification):
        message = svc.send_message(cid, 7, text, origin="customer")["message"]
        result = await automation.handle_customer_message(
            conversation_id=cid,
            customer_user_id=7,
            message_id=message["id"],
            body=text,
            market_token="fixture-token",
        )
        assert result["action"] == ("issue_intake" if text != clarification or submit else "reply")
        assert result["message"] is not None
    assert calls == (
        [("fixture-token", clarification.removeprefix("请提交工单："))] if submit else []
    )
    assert ("CS-clarification" in result["message"]["body"]) is submit
    if submit:
        replay = await automation.handle_customer_message(
            conversation_id=cid,
            customer_user_id=7,
            message_id=message["id"],
            body="untrusted caller text",
            market_token="fixture-token",
        )
        assert replay["message"] is None
        assert readbacks == [False, True]
    else:
        # A later bare request cannot recycle withdrawn/resolved/query text as
        # the missing fault description.
        message = svc.send_message(cid, 7, "提交工单", origin="customer")["message"]
        result = await automation.handle_customer_message(
            conversation_id=cid,
            customer_user_id=7,
            message_id=message["id"],
            body=message["body"],
            market_token="fixture-token",
        )
        assert result["action"] == "issue_intake"
        assert "请说明" in result["message"]["body"]
        assert not calls


@pytest.mark.asyncio
async def test_same_report_is_owner_scoped_and_rejects_other_customers_message(cs_db, monkeypatch):
    from app.application import client_product_issue_intake as intake

    cs_db.add(
        User(
            id=8,
            username="second-customer",
            password="!",
            is_active=True,
            tier="enterprise",
            market_user_id=502,
        )
    )
    cs_db.commit()
    svc, cs_id, cid = _conversation(cs_db)
    other_cid = svc.get_or_create_direct(8, cs_id)["id"]
    calls = []

    async def remote(token, path, **kwargs):
        calls.append((token, kwargs["payload"]))
        return {"success": True, "ticket_id": len(calls), "ticket_no": f"CS-{len(calls)}"}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    automation = EnterpriseCsAutomationService(cs_db)
    for user_id, conv in [(7, cid), (8, other_cid)]:
        msg = svc.send_message(conv, user_id, "请提交故障工单：Windows500卡死", origin="customer")[
            "message"
        ]
        await automation.handle_customer_message(
            conversation_id=conv,
            customer_user_id=user_id,
            message_id=msg["id"],
            body=msg["body"],
            market_token=f"fixture-owner-{user_id}",
        )
    assert calls[0][1]["source_ref"] != calls[1][1]["source_ref"]
    assert [call[0] for call in calls] == ["fixture-owner-7", "fixture-owner-8"]
    rejected = await automation.handle_customer_message(
        conversation_id=cid,
        customer_user_id=7,
        message_id=msg["id"],
        body="提交工单",
        market_token="fixture-owner-7",
    )
    assert rejected["reason"] == "invalid_customer_message"
    assert len(calls) == 2
