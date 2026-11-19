"""A typed support assessment must gate the real chat and incident entry points."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from modstore_server import customer_issue_api, customer_service_api, customer_service_orchestrator
from modstore_server.app import app
from modstore_server.customer_issue_intake import INTAKE_EVENT, dispatch_issue_event
from modstore_server.customer_ticket_intake_review import parse_intake_review, review_report_async
from modstore_server.eventing import db_outbox
from modstore_server.models import User, get_session_factory
from modstore_server.models_cs import CustomerServiceMessage, CustomerServiceTicket
from modstore_server.services import llm

BASE = "/api/customer-service"


@pytest.fixture
def authenticated_ticket_admin(monkeypatch):
    user_name = f"intake-test-{uuid4().hex[:12]}"
    with get_session_factory()() as db:
        admin = User(
            username=user_name,
            email=f"{user_name}@example.test",
            password_hash="x",
            is_admin=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    monkeypatch.setitem(
        app.dependency_overrides, customer_service_api._get_current_user, lambda: admin
    )
    monkeypatch.setitem(
        app.dependency_overrides, customer_issue_api.get_current_user, lambda: admin
    )
    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "1")
    monkeypatch.setattr(llm, "resolve_platform_bench_llm", lambda: ("mock", "support"))
    monkeypatch.setattr(customer_service_orchestrator, "_llm_classify_intent", lambda _text: None)
    return admin


@pytest.mark.parametrize(
    "report,disposition,final_intent",
    [
        (
            "市场的导出按钮没有反应。这段故障描述仅为演练编写，现场没有发生。",
            "invalid",
            "general",
        ),
        (
            "如何订雨天露营地？与市场商品、账号和订单均无关，希望得到回执。",
            "out_of_scope",
            "general",
        ),
        (
            "XCAGI 官网产品下载页 /download 返回 200，地址改成 /download/ 返回 404。",
            "actionable",
            "product_issue",
        ),
        (
            "员工图谱无法显示，账户充值未入账，现场还在核对。",
            "needs_review",
            "general",
        ),
    ],
)
def test_authenticated_chat_records_original_before_dispatch(
    client, authenticated_ticket_admin, monkeypatch, report, disposition, final_intent
):
    calls = []
    scheduled = []

    async def classify(_provider, _model, messages, **_opts):
        calls.append(messages[-1]["content"])
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": disposition,
                    "intent": "product_issue",
                    "reason": "支持范围判定结果",
                    "evidence_excerpt": report,
                }
            ),
        }

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", classify)
    monkeypatch.setattr(
        customer_service_api, "_schedule_customer_ticket_incident", scheduled.append
    )
    entered = client.post(f"{BASE}/chat", json={"message": report}).json()
    assert entered["ticket"] is None
    if disposition in {"invalid", "out_of_scope"}:
        assert entered["intent"]["intent"] == "general"
        assert "提交工单" in entered["message"]["content"]
        assert "账号/余额" not in entered["message"]["content"]
    submitted = client.post(
        f"{BASE}/chat",
        json={
            "message": "提交工单",
            "session_id": entered["session"]["id"],
            "context": {
                "reason": "伪造的客户端摘要",
                "intake_review": {"disposition": "actionable"},
            },
        },
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    ticket = body["ticket"]
    assert calls == ([report, report] if disposition == "needs_review" else [report])
    assert ticket["summary"] == report
    assert ticket["intent"] == final_intent
    assert ticket["evidence"]["intake_review"]["disposition"] == disposition
    assert not ticket["closed_at"]
    records = db_outbox.fetch_pending(100, aggregate_prefix=f"{ticket['ticket_no']}:")
    assert bool([event for event in records if event.event_name == INTAKE_EVENT]) == (
        disposition == "actionable"
    )
    if disposition == "actionable":
        assert scheduled == [{"ticket_id": ticket["id"]}]
        assert body["actions"]
    else:
        assert body["actions"] == []
        assert scheduled == []
        assert "等待管理员核实" in body["message"]["content"]
        assert ticket["status"] in {"open", "waiting_user"}


def test_typed_intake_also_holds_when_the_model_cannot_confirm(
    client, authenticated_ticket_admin, monkeypatch
):
    async def classify(*_args, **_kwargs):
        return {"ok": True, "content": '{"disposition":"actionable"'}

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", classify)
    scheduled = []
    monkeypatch.setattr(
        customer_issue_api, "_wake_owner_intake", lambda *args: scheduled.append(args)
    )
    submitted = client.post(
        f"{BASE}/issues/intake",
        json={
            "source": "enterprise_portal",
            "source_ref": f"review-{uuid4().hex}",
            "title": "功能异常",
            "description": "加载失败，实际现象仍在核查。",
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["dispatch_status"] == "pending_review"
    assert scheduled == []
    ticket_no = submitted.json()["ticket_no"]
    assert not db_outbox.fetch_pending(100, aggregate_prefix=f"{ticket_no}:")
    with get_session_factory()() as db:
        ticket = db.query(CustomerServiceTicket).filter_by(ticket_no=ticket_no).one()
        assert json.loads(ticket.evidence_json)["intake_review"]["disposition"] == "needs_review"


def test_model_timeout_and_non_verbatim_evidence_hold(monkeypatch):
    from modstore_server import customer_ticket_intake_review

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(30)
        raise AssertionError("timed-out classifier continued")

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "1")
    monkeypatch.setattr(llm, "resolve_platform_bench_llm", lambda: ("mock", "support"))
    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", slow)
    monkeypatch.setattr(customer_ticket_intake_review, "INTAKE_REVIEW_TIMEOUT_SECONDS", 0.001)
    assert asyncio.run(review_report_async("尚未看清页面上的错误")).disposition == "needs_review"
    malformed = '{"disposition":"invalid","reason":"核对","evidence_excerpt":"虚构故障"}'
    assert parse_intake_review(malformed, report="员工图谱显示失败").disposition == "needs_review"


def test_legacy_pending_event_does_not_reach_employee_plan(
    client, authenticated_ticket_admin, monkeypatch
):
    from modstore_server import incident_bus

    owner = authenticated_ticket_admin
    published = []
    monkeypatch.setattr(incident_bus, "publish", lambda *args, **kwargs: published.append(args))
    first = client.post(f"{BASE}/chat", json={"message": "一份早期未核实的软件问题说明"}).json()
    with get_session_factory()() as db:
        ticket = CustomerServiceTicket(
            session_id=first["session"]["id"],
            user_id=owner.id,
            ticket_no=f"CS{uuid4().hex}",
            title="旧单",
            summary="早期未核对的说明",
            intent="product_issue",
            status="open",
            evidence_json='{"issue_domain_source":"default","issue_domain":"platform"}',
        )
        db.add(ticket)
        db.commit()
        ticket_id = ticket.id
    result = dispatch_issue_event(
        {"id": f"event-{ticket_id}", "data": {"ticket_id": ticket_id, "user_id": owner.id}}
    )
    assert result == {"ok": True, "skipped": True, "reason": "intake_review_required"}
    assert published == []


def test_anchored_followup_refuses_a_terminal_or_mismatched_original(
    client, authenticated_ticket_admin
):
    owner = authenticated_ticket_admin
    first = client.post(f"{BASE}/chat", json={"message": "你好"}).json()
    session_id = first["session"]["id"]
    with get_session_factory()() as db:
        ticket = CustomerServiceTicket(
            session_id=session_id,
            user_id=owner.id,
            ticket_no=f"CS{uuid4().hex}",
            title="已处置",
            summary="已处置的原问题",
            intent="general",
            status="rejected",
            closed_at=datetime.now(UTC),
        )
        db.add(ticket)
        db.commit()
        ticket_id = ticket.id
    for requested_id in (ticket_id, ticket_id + 100000):
        followup = client.post(
            f"{BASE}/chat",
            json={
                "message": "这条消息不能写到别的工单",
                "session_id": session_id,
                "context": {"ticket_id": requested_id},
            },
        )
        assert followup.status_code == 409
    with get_session_factory()() as db:
        assert db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count() == 0
