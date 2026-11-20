"""A typed support assessment must gate the real chat and incident entry points."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from modstore_server import customer_issue_api, customer_service_api, customer_service_orchestrator
from modstore_server.app import app
from modstore_server.customer_issue_intake import INTAKE_EVENT, dispatch_issue_event
from modstore_server.customer_ticket_intake_review import (
    intake_dispatch_block_reason,
    parse_intake_review,
    review_report_async,
)
from modstore_server.eventing import db_outbox
from modstore_server.models import RefundRequest, User, get_session_factory
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceMessage,
    CustomerServiceTicket,
)
from modstore_server.services import llm

BASE = "/api/customer-service"


@pytest.fixture
def client(isolated_modstore):
    return TestClient(app, client=(f"intake-test-{uuid4().hex}", 50000))


def _authenticated_ticket_user(monkeypatch, *, is_admin=False):
    user_name = f"intake-test-{uuid4().hex[:12]}"
    with get_session_factory()() as db:
        user = User(
            username=user_name,
            email=f"{user_name}@example.test",
            password_hash="x",
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    monkeypatch.setitem(
        app.dependency_overrides, customer_service_api._get_current_user, lambda: user
    )
    monkeypatch.setitem(app.dependency_overrides, customer_issue_api.get_current_user, lambda: user)
    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "1")
    monkeypatch.setattr(llm, "resolve_platform_bench_llm", lambda: ("mock", "support"))
    monkeypatch.setattr(customer_service_orchestrator, "_llm_classify_intent", lambda _text: None)
    return user


@pytest.fixture
def authenticated_ticket_admin(monkeypatch):
    return _authenticated_ticket_user(monkeypatch, is_admin=True)


@pytest.mark.parametrize(
    ("report", "kind"),
    [
        ("蓝色封面按钮失灵，这段情景只用于演练，实际没有发生。", "invalid"),
        ("我想给家里的薄荷浇水，这件事与平台支持的产品或服务无关。", "out_of_scope"),
    ],
)
def test_customer_confirmed_disposition_closes_and_replies_once(client, monkeypatch, report, kind):
    owner = _authenticated_ticket_user(monkeypatch)
    reviews = []

    async def classify(_provider, _model, messages, **_opts):
        reviews.append(messages[-1]["content"])
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": kind,
                    "reason": "核对提交范围",
                    "evidence_excerpt": report,
                }
            ),
        }

    scheduled = []
    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", classify)
    monkeypatch.setattr(
        customer_service_api, "_schedule_customer_ticket_incident", scheduled.append
    )
    entered = client.post(f"{BASE}/chat", json={"message": report}).json()
    offered = entered["message"]["payload"]["intake_confirmation"]
    assert offered["kind"] == kind
    request = {
        "message": "提交工单",
        "session_id": entered["session"]["id"],
        "intake_confirmation": offered,
    }
    wrong_kind = "out_of_scope" if kind == "invalid" else "invalid"
    mismatched = client.post(
        f"{BASE}/chat",
        json={
            **request,
            "intake_confirmation": {**offered, "kind": wrong_kind},
        },
    )
    assert mismatched.status_code == 409
    with_order = client.post(f"{BASE}/chat", json={**request, "context": {"order_no": "NEW-ORDER"}})
    assert with_order.status_code == 409
    with_image = client.post(
        f"{BASE}/chat", json={**request, "image_data_url": "data:image/png;base64,eA=="}
    )
    assert with_image.status_code == 409
    response = client.post(f"{BASE}/chat", json=request)
    assert response.status_code == 200, response.text
    submitted = response.json()
    ticket = submitted["ticket"]
    assert ticket["status"] == "rejected" and ticket["closed_at"]
    assert ticket["disposition"]["kind"] == kind
    assert ticket["dispatch_status"] == "terminal"
    assert submitted["message"]["payload"]["origin"] == "assistant_disposition"
    assert client.post(f"{BASE}/chat", json=request).status_code == 409
    assert reviews == [report] and scheduled == []
    records = db_outbox.fetch_pending(100, aggregate_prefix=f"{ticket['ticket_no']}:")
    assert all(event.event_name != INTAKE_EVENT for event in records)
    readback = client.get(f"{BASE}/sessions/{request['session_id']}").json()
    transcript = readback["messages"]
    final_replies = [m for m in transcript if m["payload"].get("origin") == "assistant_disposition"]
    assert len(final_replies) == 1
    assert ticket["ticket_no"] in final_replies[0]["content"]
    with get_session_factory()() as db:
        original = db.get(CustomerServiceMessage, offered["source_message_id"])
        assert original.ticket_id == ticket["id"] and original.content == report
        stored = db.get(CustomerServiceTicket, ticket["id"])
        assert stored.assigned_admin_id is None and stored.user_id == owner.id
        action = db.query(CustomerServiceAction).filter_by(ticket_id=stored.id).one()
        assert action.action_type == "ticket.disposition" and action.status == "completed"
        audit = (
            db.query(CustomerServiceAuditLog)
            .filter_by(
                ticket_id=stored.id,
                event_type="assistant_ticket_disposed",
            )
            .one()
        )
        assert audit.actor_user_id is None and audit.actor_type == "ai"
        assert json.loads(audit.detail_json)["actor"] == "xiaoc"


def test_disposition_offer_cannot_close_another_or_changed_original(client, monkeypatch):
    owner = _authenticated_ticket_user(monkeypatch)
    report = "这是一个演练描述，实际没有发生。"

    async def classify(_provider, _model, messages, **_opts):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": "invalid",
                    "reason": "演练",
                    "evidence_excerpt": messages[-1]["content"],
                }
            ),
        }

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", classify)
    entered = client.post(f"{BASE}/chat", json={"message": report}).json()
    session = entered["session"]["id"]
    request = {
        "message": "提交工单",
        "session_id": session,
        "intake_confirmation": entered["message"]["payload"]["intake_confirmation"],
    }
    _authenticated_ticket_user(monkeypatch)
    assert client.post(f"{BASE}/chat", json=request).status_code == 409
    monkeypatch.setitem(
        app.dependency_overrides, customer_service_api._get_current_user, lambda: owner
    )
    assert (
        client.post(
            f"{BASE}/chat", json={"message": "这是另外一段反馈。", "session_id": session}
        ).status_code
        == 200
    )
    assert client.post(f"{BASE}/chat", json=request).status_code == 409
    with get_session_factory()() as db:
        assert db.query(CustomerServiceTicket).filter_by(session_id=session).count() == 0


def test_out_of_scope_model_quote_alone_does_not_offer_close_for_download_failure(
    client, monkeypatch
):
    _authenticated_ticket_user(monkeypatch)
    report = "我问过薄荷浇水。实际故障是 XCAGI 官网下载 /download/ 返回 404。"

    async def classify(*_args, **_opts):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": "out_of_scope",
                    "reason": "盆栽",
                    "evidence_excerpt": "薄荷浇水",
                }
            ),
        }

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", classify)
    checked = client.post(f"{BASE}/chat", json={"message": report}).json()
    assert "intake_confirmation" not in checked["message"]["payload"]


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


def test_short_anchored_material_reaches_existing_ticket_workflow(
    client, authenticated_ticket_admin, monkeypatch
):
    original = "重复购买的商品希望退款，请提交工单。"
    supplement = "订单号：REFUND-123456"
    reports, executions = [], []

    async def review(_provider, _model, messages, **_opts):
        report = messages[-1]["content"]
        reports.append(report)
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": "actionable" if report == original else "needs_review",
                    "intent": "refund",
                    "reason": "核对原退款诉求与订单材料",
                    "evidence_excerpt": original,
                }
            ),
        }

    def execute(_db, action, _user):
        executions.append((action.ticket_id, action.action_type, action.target_id))
        action.status = "completed"
        return action

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", review)
    monkeypatch.setattr(customer_service_orchestrator, "execute_action", execute)
    monkeypatch.setattr(customer_service_api, "_schedule_customer_ticket_incident", lambda _: None)
    first = client.post(f"{BASE}/chat", json={"message": original}).json()
    ticket_id = first["ticket"]["id"]
    assert first["ticket"]["status"] == "waiting_user" and not executions
    response = client.post(
        f"{BASE}/chat",
        json={
            "message": supplement,
            "session_id": first["session"]["id"],
            "context": {"ticket_id": ticket_id, "order_no": "CLIENT-SPOOFED-ORDER"},
        },
    )
    assert response.status_code == 200, response.text
    ticket = response.json()["ticket"]
    assert reports[-1] == f"{original}\n原工单补充：{supplement}"
    assert ticket["id"] == ticket_id and ticket["summary"] == original
    assert ticket["evidence"]["order_no"] == "REFUND-123456"
    assert executions == [(ticket_id, "refund.apply", "REFUND-123456")]


def test_verified_original_refund_uses_the_corrected_order(client, monkeypatch):
    customer = _authenticated_ticket_user(monkeypatch)
    old_order = f"OLD-{uuid4().hex[:10]}"
    correct_order = f"NEW-{uuid4().hex[:10]}"
    original = f"重复购买的商品希望退款，订单号：{old_order}，请提交工单。"
    correction = f"更正订单号：{correct_order}"
    looked_up = []

    async def review(_provider, _model, messages, **_opts):
        report = messages[-1]["content"]
        accepted = correction in report
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": "actionable" if accepted else "needs_review",
                    "intent": "refund",
                    "reason": "核对原单与更正材料",
                    "evidence_excerpt": correction if accepted else "",
                }
            ),
        }

    def paid_order(number):
        looked_up.append(number)
        return {"user_id": customer.id, "status": "paid", "total_amount": 10}

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", review)
    monkeypatch.setattr("modstore_server.customer_service_tools.payment_orders.find", paid_order)
    monkeypatch.setattr(customer_service_api, "_schedule_customer_ticket_incident", lambda _: None)
    first = client.post(f"{BASE}/chat", json={"message": original}).json()
    ticket_id = first["ticket"]["id"]
    assert not looked_up and not first["actions"]
    amended = client.post(
        f"{BASE}/chat",
        json={
            "message": correction,
            "session_id": first["session"]["id"],
            "context": {"ticket_id": ticket_id, "order_no": "CONTEXT-SPOOFED-ORDER"},
        },
    )
    assert amended.status_code == 200, amended.text
    assert amended.json()["ticket"]["id"] == ticket_id
    assert looked_up == [correct_order]
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        assert ticket.subject_id == correct_order and ticket.summary == original
        assert json.loads(ticket.evidence_json)["order_no"] == correct_order
        assert [r.order_no for r in db.query(RefundRequest).filter_by(user_id=customer.id)] == [
            correct_order
        ]


@pytest.mark.parametrize(
    "protected",
    [
        None,
        "invalid",
        "out_of_scope",
        "revoked",
        "changed_since_review",
        "repeat_original",
        "intent_changed",
        "legacy",
        "revoked_legacy",
        "typed",
        "null_review",
        "empty_review",
        "unknown_review",
        "malformed_review",
    ],
)
def test_anchored_reassessment_releases_only_current_hold_once(
    client, authenticated_ticket_admin, monkeypatch, protected
):
    original = "官网下载页白屏，请提交工单。"
    clarification = "我在官网点击下载产品按钮，界面白屏，连续复现两次。"
    changed = "管理员已更新问题范围，当前等待现场核实。"
    reports, scheduled = [], []
    ticket_id = None
    repeats_original = protected in {"repeat_original", "intent_changed"}

    async def review(_provider, _model, messages, **_opts):
        report = messages[-1]["content"]
        reports.append(report)
        if ticket_id and protected == "changed_since_review":
            with get_session_factory()() as db:
                db.get(CustomerServiceTicket, ticket_id).summary = changed
                db.commit()
        actionable = clarification in report or (repeats_original and ticket_id is not None)
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": "actionable" if actionable else "needs_review",
                    "intent": (
                        "refund"
                        if actionable and protected == "intent_changed"
                        else "product_issue"
                    ),
                    "reason": "根据原始说明及新增复现场景核对",
                    "evidence_excerpt": clarification if clarification in report else original,
                }
            ),
        }

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", review)
    monkeypatch.setattr(
        customer_service_api, "_schedule_customer_ticket_incident", scheduled.append
    )
    first = client.post(f"{BASE}/chat", json={"message": original}).json()
    ticket_id = first["ticket"]["id"]
    assert first["ticket"]["evidence"]["intake_review"]["disposition"] == "needs_review"
    assert not scheduled
    malformed_receipts = {
        "null_review": None,
        "empty_review": {},
        "unknown_review": {"disposition": "unrecognized"},
        "malformed_review": {"disposition": "needs_review", "reason": 123},
    }
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket_id)
        evidence = json.loads(row.evidence_json)
        if protected in {"legacy", "revoked_legacy", "typed"}:
            assert evidence["issue_domain_source"]
            del evidence["intake_review"]
        if protected == "typed":
            evidence["source"] = "enterprise_portal"
        elif protected in {"invalid", "out_of_scope"}:
            evidence["intake_review"]["disposition"] = protected
        elif protected in malformed_receipts:
            evidence["intake_review"] = malformed_receipts[protected]
        if protected in {"revoked", "revoked_legacy"}:
            evidence["dispatch_revocation"] = {"note": "核对后停止新派发"}
        row.evidence_json = json.dumps(evidence)
        expected_reason = {
            "typed": "",
            "revoked": "ticket_dispatch_revoked",
            "revoked_legacy": "ticket_dispatch_revoked",
        }.get(protected, "intake_review_required")
        assert intake_dispatch_block_reason(row) == expected_reason
        db.commit()
    body = {
        "message": original if repeats_original else clarification,
        "session_id": first["session"]["id"],
        "context": {} if repeats_original else {"ticket_id": ticket_id},
    }
    updated = client.post(f"{BASE}/chat", json=body).json()["ticket"]
    assert updated["id"] == ticket_id
    assert reports[-1] == (
        original if repeats_original else f"{original}\n原工单补充：{clarification}"
    )
    if protected == "typed":
        assert updated["evidence"]["source"] == "enterprise_portal"
        assert "intake_review" not in updated["evidence"]
        assert "intake_reassessment_sha256" not in updated["evidence"]
        assert scheduled == [{"ticket_id": ticket_id}]
        return
    if protected not in {None, "repeat_original", "legacy"}:
        assert ("intake_review" in updated["evidence"]) == ("intake_review" in evidence)
        assert updated["evidence"].get("intake_review") == evidence.get("intake_review")
        assert "intake_reassessment_sha256" not in updated["evidence"]
        assert updated["summary"] == (changed if protected == "changed_since_review" else original)
        assert not scheduled
        records = db_outbox.fetch_pending(100, aggregate_prefix=f"{updated['ticket_no']}:")
        assert not any(event.event_name == INTAKE_EVENT for event in records)
        return
    assert updated["evidence"]["intake_review"]["disposition"] == "actionable"
    assert updated["summary"] == original
    repeated = client.post(f"{BASE}/chat", json=body).json()["ticket"]
    assert repeated["id"] == ticket_id
    assert scheduled == [{"ticket_id": ticket_id}]
    records = db_outbox.fetch_pending(100, aggregate_prefix=f"{updated['ticket_no']}:")
    assert len([event for event in records if event.event_name == INTAKE_EVENT]) == 1
