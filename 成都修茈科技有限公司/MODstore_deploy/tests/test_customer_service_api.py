from __future__ import annotations

import types
import uuid
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("fastapi")


def _make_user(username: str, *, admin: bool = False):
    from modstore_server.models import User, get_session_factory

    username = f"{username}_{uuid.uuid4().hex[:8]}"
    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
            is_admin=admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(
            id=user.id, username=user.username, email=user.email, is_admin=user.is_admin
        )


def _grant_permanent_purchase(
    user_id: int, plan_id: str = "saas-permanent-growth"
) -> str:
    from modstore_server.models import Entitlement, UserPlan, get_session_factory

    order_no = f"ACCOUNT-PYTEST-{uuid.uuid4().hex[:10]}"
    sf = get_session_factory()
    with sf() as session:
        session.add(UserPlan(user_id=user_id, plan_id=plan_id, is_active=True))
        session.add(
            Entitlement(
                user_id=user_id,
                entitlement_type="plan",
                source_order_id=order_no,
                metadata_json=f'{{"plan_id":"{plan_id}"}}',
                is_active=True,
            )
        )
        session.commit()
    return order_no


def _paid_order(tmp_path, monkeypatch, user_id: int) -> str:
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    from modstore_server import payment_orders

    order_no = f"CS-PYTEST-{uuid.uuid4().hex[:10]}"
    payment_orders.create(
        out_trade_no=order_no,
        subject="customer service order",
        total_amount="19.90",
        user_id=user_id,
        order_kind="plan",
        plan_id="plan_basic",
    )
    payment_orders.update_status(
        out_trade_no=order_no,
        status="paid",
        trade_no="TRADE1",
        paid_at="2026-01-01T00:00:00Z",
    )
    return order_no


def test_customer_service_refund_chat_creates_ticket_action_and_refund(
    client, tmp_path, monkeypatch
):
    from modstore_server import customer_service_api, webhook_dispatcher
    from modstore_server.app import app
    from modstore_server.models import RefundRequest, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_user")
    order_no = _paid_order(tmp_path, monkeypatch, user.id)
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    monkeypatch.setattr(
        webhook_dispatcher, "dispatch_event", lambda event: {"ok": True, "event": event}
    )
    try:
        r = client.post(
            "/api/customer-service/chat",
            json={
                "message": f"订单号：{order_no} 我想退款，重复购买了",
                "context": {"channel": "web"},
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["ticket"]["intent"] == "refund"
        assert data["decision"]["decision"] == "approved"
        assert data["actions"][0]["action_type"] == "refund.apply"
        assert data["actions"][0]["status"] == "completed"

        sf = get_session_factory()
        with sf() as session:
            assert (
                session.query(CustomerServiceTicket)
                .filter(CustomerServiceTicket.ticket_no == data["ticket"]["ticket_no"])
                .first()
            )
            refund = (
                session.query(RefundRequest)
                .filter(RefundRequest.order_no == order_no)
                .first()
            )
            assert refund is not None
            assert refund.status == "pending"
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_incomplete_refund_chats_without_ticket(client, monkeypatch):
    """材料不齐的退款诉求只聊天引导，不立刻建单。"""
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_missing")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post(
            "/api/customer-service/chat", json={"message": "我要退款", "context": {}}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ticket"] is None
        assert data["intent"]["intent"] == "refund"
        assert data["intent"]["need_ticket"] is False
        assert "提交工单" in data["message"]["content"]
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_chat_does_not_block_on_incident_publish_async(
    client, monkeypatch
):
    """建单后的 incident 派发若同步执行会卡死「处理中…」；必须异步。"""
    import time
    from threading import Event

    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_async_inc")
    started = {"ok": False}
    started_event = Event()

    def slow_publish(payload):
        started["ok"] = True
        started_event.set()

    monkeypatch.setattr(
        customer_service_api, "_publish_customer_ticket_incident", slow_publish
    )
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        t0 = time.time()
        r = client.post(
            "/api/customer-service/chat",
            json={
                "message": "订单号 RF123456 想退款，原因是重复购买",
                "context": {"channel": "web"},
            },
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        assert r.json().get("ticket")
        assert elapsed < 4.0, (
            f"chat unexpectedly slow on async incident publish: {elapsed:.2f}s"
        )
        assert started_event.wait(1.0)
        assert started["ok"] is True
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_chat_does_not_block_on_incident_publish(client, monkeypatch):
    """建单后的 incident 派发若同步执行会卡死「处理中…」；必须异步。"""
    import time
    from threading import Event

    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_async_inc")
    started = {"ok": False}
    started_event = Event()

    def slow_publish(payload):
        started["ok"] = True
        started_event.set()

    monkeypatch.setattr(
        customer_service_api, "_publish_customer_ticket_incident", slow_publish
    )
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        t0 = time.time()
        r = client.post(
            "/api/customer-service/chat",
            json={
                "message": "订单号 RF123456 想退款，原因是重复购买",
                "context": {"channel": "web"},
            },
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        assert r.json().get("ticket")
        assert elapsed < 4.0, (
            f"chat unexpectedly slow on async incident publish: {elapsed:.2f}s"
        )
        assert started_event.wait(1.0)
        assert started["ok"] is True
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_greeting_does_not_create_ticket(client, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.app import app
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_hi")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post(
            "/api/customer-service/chat", json={"message": "你好", "context": {}}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["ticket"] is None
        assert data["intent"]["intent"] == "greeting"
        assert data["intent"]["need_ticket"] is False
        assert data["cards"] == []
        assert "小C" in data["message"]["content"]
        assert "intent" not in data["message"]["content"]
        assert "{" not in data["message"]["content"]

        sf = get_session_factory()
        with sf() as session:
            n = (
                session.query(CustomerServiceTicket)
                .filter(CustomerServiceTicket.user_id == user.id)
                .count()
            )
            assert n == 0
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_escalate_phrase_creates_ticket(client, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_esc")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post(
            "/api/customer-service/chat",
            json={"message": "这个问题处理不了，请提交工单", "context": {}},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ticket"] is not None
        assert data["ticket"]["intent"] == "general"
        assert data["intent"]["need_ticket"] is True
        # 功能/咨询类无自动动作：应登记跟进，不能秒结案
        assert data["ticket"]["status"] == "processing"
        assert data["ticket"]["status"] != "resolved"
        assert (data.get("decision") or {}).get("decision") == "accepted"
        assert "已处理完成" not in str(data.get("message", {}).get("content") or "")
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_ui_bug_escalate_stays_processing(client, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_ui_bug")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r1 = client.post(
            "/api/customer-service/chat",
            json={"message": "浅色模式/自选模型文字看不见", "context": {}},
        )
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["ticket"] is None
        assert d1["intent"]["intent"] == "product_issue"
        sid = d1["session"]["id"]
        r2 = client.post(
            "/api/customer-service/chat",
            json={"message": "提交工单", "session_id": sid, "context": {}},
        )
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["ticket"] is not None
        assert data["ticket"]["intent"] == "product_issue"
        assert data["ticket"]["status"] == "processing"
        assert data["ticket"]["title"] == "平台功能问题"
        assert data["ticket"].get("issue_domain") == "platform"
        assert data["ticket"].get("issue_domain_label") == "平台"
        assert (data.get("decision") or {}).get("decision") == "accepted"
        assert data["ticket"].get("lifecycle_stage") == 2
        body = str(data.get("message", {}).get("content") or "")
        assert "已处理完成" not in body
        assert "功能问题" in body or "浅色" in body or "看不见" in body
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_resolve_issue_domain_three_way():
    from modstore_server.customer_service_orchestrator import (
        _parse_domain_clarify_reply,
        resolve_issue_domain,
    )

    platform = resolve_issue_domain(
        intent="product_issue",
        text="浅色模式/自选模型文字看不见",
        extracted={},
        context={},
    )
    assert platform["domain"] == "platform"

    software = resolve_issue_domain(
        intent="product_issue",
        text="这个员工包打不开",
        extracted={"catalog_id": 12},
        context={},
    )
    assert software["domain"] == "software"

    custom = resolve_issue_domain(
        intent="product_issue",
        text="我的定制员工回复异常",
        extracted={"account_custom": True},
        context={},
    )
    assert custom["domain"] == "custom"
    assert custom["label"] == "客户定制"
    assert _parse_domain_clarify_reply("是平台") == "platform"
    assert (
        resolve_issue_domain(
            intent="greeting", text="是平台", extracted={}, context={}
        )["domain"]
        == "platform"
    )


def test_product_issue_domain_clarify_continues_ticket(client, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    published: list = []

    def _fake_publish(event_type, payload, *, source, fingerprint=None):
        published.append(
            {"event_type": event_type, "payload": dict(payload or {}), "source": source}
        )
        return True

    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        _fake_publish,
    )
    # 强制同步调度线程目标，便于断言
    monkeypatch.setattr(
        customer_service_api,
        "_schedule_customer_ticket_incident",
        lambda payload: customer_service_api._publish_customer_ticket_incident(payload),
    )

    user = _make_user("cs_domain_clarify")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r1 = client.post(
            "/api/customer-service/chat",
            json={"message": "浅色模式/自选模型文字看不见", "context": {}},
        )
        assert r1.status_code == 200, r1.text
        sid = r1.json()["session"]["id"]
        r2 = client.post(
            "/api/customer-service/chat",
            json={
                "message": "提交工单",
                "session_id": sid,
                "context": {"reason": "浅色模式/自选模型文字看不见"},
            },
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["ticket"]["status"] == "processing"
        published.clear()

        r3 = client.post(
            "/api/customer-service/chat",
            json={"message": "是平台", "session_id": sid, "context": {}},
        )
        assert r3.status_code == 200, r3.text
        data = r3.json()
        assert data["ticket"] is not None
        assert data["ticket"]["intent"] == "product_issue"
        assert data["ticket"]["status"] == "processing"
        assert data["ticket"]["issue_domain"] == "platform"
        assert data["ticket"]["title"] == "平台功能问题"
        body = str(data.get("message", {}).get("content") or "")
        assert "确认" in body or "平台" in body
        assert "已处理完成" not in body
        assert published, "应再次发布 ops.intake.customer_ticket 给 intake-dispatcher"
        assert published[-1]["event_type"] == "ops.intake.customer_ticket"
        assert published[-1]["payload"].get("user_confirmed_domain") == "platform"
        assert published[-1]["payload"].get("source") == "customer_ticket"
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_parse_intent_json_handles_truncated_minimax():
    from modstore_server.customer_service_orchestrator import (
        _parse_intent_json,
        classify_customer_intent,
        extract_fields,
    )

    truncated = '\n{"intent":"general","need_ticket":false,"confidence":0'
    data = _parse_intent_json(truncated)
    assert data is not None
    assert data["intent"] == "general"

    # LLM 关闭时，缺陷语义仍落到 product_issue
    import os

    os.environ["MODSTORE_CS_LLM_INTENT"] = "0"
    c = classify_customer_intent(
        "浅色模式/自选模型文字看不见",
        extract_fields("浅色模式/自选模型文字看不见", {}),
    )
    assert c["intent"] == "product_issue"
    assert c["need_ticket"] is False


def test_ticket_lifecycle_five_stages():
    from modstore_server.customer_service_orchestrator import (
        ticket_lifecycle_payload,
        ticket_lifecycle_stage,
    )

    assert ticket_lifecycle_stage("open") == 1
    assert ticket_lifecycle_stage("processing") == 2
    assert ticket_lifecycle_stage("processing", "accepted") == 2
    assert ticket_lifecycle_stage("processing", "approved") == 3
    assert ticket_lifecycle_stage("waiting_user") == 4
    assert ticket_lifecycle_stage("resolved") == 5
    payload = ticket_lifecycle_payload("waiting_user")
    assert payload["lifecycle_label"] == "待补充"
    assert [s["state"] for s in payload["lifecycle_steps"]] == [
        "done",
        "done",
        "done",
        "current",
        "todo",
    ]


def test_apply_customer_ticket_incident_progress_advances_lifecycle(
    client, monkeypatch
):
    """incident team 结果应回写客服消息，并把工单推到「有结果」。"""
    from modstore_server import customer_service_api
    from modstore_server.app import app
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
        ticket_lifecycle_stage,
    )
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceMessage, CustomerServiceTicket

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    monkeypatch.setattr(
        customer_service_api,
        "_schedule_customer_ticket_incident",
        lambda payload: None,
    )
    user = _make_user("cs_emp_progress")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r1 = client.post(
            "/api/customer-service/chat",
            json={"message": "浅色模式文字看不见", "context": {}},
        )
        assert r1.status_code == 200, r1.text
        sid = r1.json()["session"]["id"]
        r2 = client.post(
            "/api/customer-service/chat",
            json={
                "message": "提交工单",
                "session_id": sid,
                "context": {"reason": "浅色模式文字看不见"},
            },
        )
        assert r2.status_code == 200, r2.text
        ticket_id = int(r2.json()["ticket"]["id"])
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)

    sf = get_session_factory()
    with sf() as db:
        out = apply_customer_ticket_incident_progress(
            db,
            ticket_id=ticket_id,
            event_id=99001,
            team_ok=False,
            team_rows=[
                {
                    "role": "scout",
                    "employee_id": "change-request-auditor",
                    "ok": False,
                    "status": "handler_failed",
                },
                {
                    "role": "fix",
                    "employee_id": "vibe-coding-maintainer",
                    "ok": False,
                    "status": "handler_failed",
                },
                {
                    "role": "verify",
                    "employee_id": "test-qa-runner",
                    "ok": True,
                    "status": "success",
                },
            ],
            summary_hint="浅色模式文字看不见",
        )
        db.commit()
        assert out.get("ok") is True
        assert out.get("lifecycle_stage") == 3
        ticket = (
            db.query(CustomerServiceTicket)
            .filter(CustomerServiceTicket.id == ticket_id)
            .first()
        )
        assert ticket is not None
        assert ticket.status == "processing"
        assert ticket.decision_status == "approved"
        assert ticket_lifecycle_stage(ticket.status, ticket.decision_status) == 3
        msgs = (
            db.query(CustomerServiceMessage)
            .filter(
                CustomerServiceMessage.ticket_id == ticket_id,
                CustomerServiceMessage.role == "assistant",
            )
            .order_by(CustomerServiceMessage.id.desc())
            .all()
        )
        assert any("员工处理进展" in (m.content or "") for m in msgs)


def test_custom_delivery_requires_quality_acceptance_and_install_receipt(
    client, monkeypatch
):
    """定制交付不能因员工报告成功提前结案；必须质量门、验收和安装回执齐全。"""
    from modstore_server import (
        customer_service_api,
        customer_service_delivery_api,
        workbench_api,
    )
    from modstore_server.app import app
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceAuditLog, CustomerServiceTicket

    user = _make_user("custom_delivery")
    account_order_no = _grant_permanent_purchase(user.id)
    admin = _make_user("custom_delivery_admin", admin=True)
    state = {
        "id": "wb-custom-1",
        "intent": "mod",
        "status": "running",
        "steps": [{"id": "spec", "label": "理解需求", "status": "running"}],
        "artifact": None,
        "error": None,
        "quality_report": None,
        "sandbox_report": None,
    }

    async def fake_start(user_id, payload):
        assert user_id == user.id
        assert payload["intent"] in {"mod", "employee"}
        return {"session_id": state["id"], "status": "running"}

    async def fake_snapshot(session_id, user_id):
        assert session_id == state["id"]
        assert user_id == user.id
        return dict(state)

    monkeypatch.setattr(workbench_api, "start_workbench_session_for_user", fake_start)
    monkeypatch.setattr(workbench_api, "get_workbench_session_snapshot", fake_snapshot)
    monkeypatch.setattr(
        customer_service_api,
        "_schedule_customer_ticket_incident",
        lambda payload: None,
    )
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        created = client.post(
            "/api/customer-service/custom-deliveries",
            json={
                "kind": "bundle",
                "title": "合同审核与审批员工",
                "requirements": "解析合同并标记风险，再交由审批员工生成复核意见。",
                "acceptance_criteria": "沙箱用例和员工真实执行门均通过。",
                "suggested_id": "contract-review-private",
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["user_id"] == user.id
        assert body["custom_delivery"]["stage"] == "production"
        assert body["custom_delivery"]["pricing_mode"] == "initial_included"
        assert (
            body["custom_delivery"]["delivery_terms"]["source_order_id"]
            == account_order_no
        )
        assert body["custom_delivery"]["commerce_ready"] is True
        ticket_id = int(body["id"])
        sf = get_session_factory()

        duplicate_initial = client.post(
            "/api/customer-service/custom-deliveries",
            json={
                "kind": "module",
                "title": "首次交付前追加要求",
                "requirements": "在当前首次交付完成前追加一个新的审核规则。",
                "acceptance_criteria": "追加规则与原工单一起通过验收。",
                "suggested_id": "pre-delivery-extra-rule",
            },
        )
        assert duplicate_initial.status_code == 200, duplicate_initial.text
        assert int(duplicate_initial.json()["id"]) == ticket_id
        assert (
            duplicate_initial.json()["custom_delivery"]["pricing_mode"]
            == "initial_included"
        )
        assert duplicate_initial.json()["custom_delivery"]["stage"] == "production"
        with sf() as db:
            revised_row = (
                db.query(CustomerServiceTicket).filter_by(id=ticket_id).first()
            )
            revised_evidence = customer_service_api._custom_delivery_evidence(
                revised_row
            )
            assert len(revised_evidence["pre_delivery_changes"]) == 1
            assert (
                revised_evidence["pre_delivery_changes"][0]["included_in_purchase"]
                is True
            )
            assert len(revised_evidence["runs"]) == 2

        with sf() as db:
            progress = apply_customer_ticket_incident_progress(
                db,
                ticket_id=ticket_id,
                event_id=71001,
                team_ok=True,
                team_rows=[
                    {
                        "role": "verify",
                        "employee_id": "test-qa-runner",
                        "ok": True,
                        "status": "success",
                    }
                ],
            )
            db.commit()
            assert progress["ok"] is True
            row = db.query(CustomerServiceTicket).filter_by(id=ticket_id).first()
            assert row.status == "processing"
            assert row.closed_at is None

        state.update(
            {
                "status": "done",
                "steps": [
                    {"id": "spec", "label": "理解需求", "status": "done"},
                    {"id": "mod_sandbox", "label": "Mod 沙箱", "status": "done"},
                    {"id": "complete", "label": "完成", "status": "done"},
                ],
                "artifact": {
                    "mod_id": "contract-review-private",
                    "validation_summary": {"ok": True},
                },
            }
        )
        listed = client.get("/api/customer-service/custom-deliveries")
        assert listed.status_code == 200, listed.text
        current = next(row for row in listed.json()["items"] if row["id"] == ticket_id)
        assert current["custom_delivery"]["stage"] == "acceptance"
        assert current["custom_delivery"]["gate_ok"] is True

        app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin
        internal_approved = client.post(
            f"/api/customer-service/custom-deliveries/{ticket_id}/decision",
            json={"action": "accept", "note": "管理端内部质量确认"},
        )
        assert internal_approved.status_code == 200, internal_approved.text
        assert internal_approved.json()["custom_delivery"]["stage"] == "acceptance"
        assert (
            internal_approved.json()["custom_delivery"]["acceptance_status"]
            == "internal_approved"
        )

        app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
        accepted = client.post(
            f"/api/customer-service/custom-deliveries/{ticket_id}/decision",
            json={"action": "accept", "note": "验收通过"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["custom_delivery"]["stage"] == "delivering"
        assert accepted.json()["custom_delivery"]["commerce_ready"] is True
        with sf() as db:
            accepted_audit = (
                db.query(CustomerServiceAuditLog)
                .filter_by(ticket_id=ticket_id, event_type="custom_delivery_accepted")
                .first()
            )
            assert accepted_audit is not None
            assert accepted_audit.actor_user_id == user.id

        app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin
        crm_updates = [
            {"section": "assignment", "owner_name": "张交付"},
            {
                "section": "quote",
                "status": "accepted",
                "number": "QT-PYTEST-001",
                "amount": 1999,
            },
            {
                "section": "contract",
                "status": "signed",
                "number": "CT-PYTEST-001",
                "reference": "oss://pytest/contract.pdf",
            },
            {
                "section": "payment",
                "status": "paid",
                "amount": 1999,
                "reference": "PAY-PYTEST-001",
            },
        ]
        for crm_payload in crm_updates:
            updated = client.post(
                f"/api/customer-service/custom-deliveries/{ticket_id}/crm",
                json=crm_payload,
            )
            assert updated.status_code == 200, updated.text
        assert updated.json()["custom_delivery"]["commerce_ready"] is True
        assert updated.json()["custom_delivery"]["stage"] == "delivering"
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: user

        receipt_token = "pytest-download-receipt-token-73"
        with sf() as db:
            row = db.query(CustomerServiceTicket).filter_by(id=ticket_id).first()
            evidence = customer_service_api._custom_delivery_evidence(row)
            evidence["download_grants"] = [
                {
                    "token": receipt_token,
                    "kind": "module",
                    "id": "contract-review-private",
                    "used": False,
                }
            ]
            row.evidence_json = customer_service_api.json_dumps(evidence)
            db.commit()

        installed = client.post(
            f"/api/customer-service/custom-deliveries/{ticket_id}/installed",
            json={
                "artifact_kind": "module",
                "artifact_id": "contract-review-private",
                "installed_version": "1.0.0",
                "host": "XCAGI Desktop pytest",
                "receipt_token": receipt_token,
            },
        )
        assert installed.status_code == 200, installed.text
        assert installed.json()["status"] == "resolved"
        assert installed.json()["custom_delivery"]["stage"] == "delivered"
        replayed = client.post(
            f"/api/customer-service/custom-deliveries/{ticket_id}/installed",
            json={
                "artifact_kind": "module",
                "artifact_id": "contract-review-private",
                "installed_version": "1.0.0",
                "host": "XCAGI Desktop pytest",
                "receipt_token": receipt_token,
            },
        )
        assert replayed.status_code == 409

        addon = client.post(
            "/api/customer-service/custom-deliveries",
            json={
                "kind": "employee",
                "title": "交付后新增采购复核员工",
                "requirements": "在首次交付完成后新增采购复核和异常升级处理能力。",
                "acceptance_criteria": "真实采购样本通过并生成可复核的处理记录。",
                "suggested_id": "procurement-review-addon",
            },
        )
        assert addon.status_code == 200, addon.text
        addon_body = addon.json()
        assert addon_body["custom_delivery"]["pricing_mode"] == "post_delivery_addon"
        assert addon_body["custom_delivery"]["stage"] == "commerce"
        assert addon_body["custom_delivery"]["commerce_ready"] is False
        addon_ticket_id = int(addon_body["id"])

        app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin
        quoted = client.post(
            f"/api/customer-service/custom-deliveries/{addon_ticket_id}/crm",
            json={
                "section": "quote",
                "status": "accepted",
                "number": "QT-ADDON-PYTEST-001",
                "amount": 3000,
            },
        )
        assert quoted.status_code == 200, quoted.text
        assert quoted.json()["custom_delivery"]["stage"] == "commerce"

        from modstore_server import customer_service_delivery_crm_api

        monkeypatch.setattr(
            customer_service_delivery_api,
            "create_custom_delivery_payment_order",
            AsyncMock(
                return_value={
                    "ok": True,
                    "order_id": "CDP-ADDON-PYTEST-001",
                    "type": "page",
                    "redirect_url": "https://alipay.example/checkout",
                    "checkout_path": "/market/checkout/CDP-ADDON-PYTEST-001",
                }
            ),
        )
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
        checkout = client.post(
            f"/api/customer-service/custom-deliveries/{addon_ticket_id}/payment-checkout",
            json={"pay_channel": "alipay"},
        )
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["order_id"] == "CDP-ADDON-PYTEST-001"
        assert checkout.json()["redirect_url"] == "https://alipay.example/checkout"
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin

        monkeypatch.setattr(
            customer_service_delivery_crm_api,
            "find_matching_paid_order",
            lambda *_args, **_kwargs: {
                "out_trade_no": "PAID-WRONG-KIND-PYTEST-001",
                "status": "paid",
                "total_amount": "3000.00",
                "order_kind": "plan",
                "user_id": user.id,
            },
        )
        rejected_payment = client.post(
            f"/api/customer-service/custom-deliveries/{addon_ticket_id}/crm",
            json={
                "section": "payment",
                "status": "paid",
                "amount": 3000,
                "reference": "NOT-A-REAL-ORDER",
            },
        )
        assert rejected_payment.status_code == 409

        monkeypatch.setattr(
            customer_service_delivery_api,
            "find_matching_paid_order",
            lambda *_args, **_kwargs: {
                "out_trade_no": "PAID-ADDON-PYTEST-001",
                "status": "paid",
                "total_amount": "3000.00",
                "order_kind": "custom_delivery",
                "user_id": user.id,
            },
        )
        state.update(
            {
                "status": "running",
                "steps": [{"id": "spec", "label": "理解新增需求", "status": "running"}],
                "artifact": None,
            }
        )
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
        reconciled = client.get("/api/customer-service/custom-deliveries")
        assert reconciled.status_code == 200, reconciled.text
        paid = next(
            row for row in reconciled.json()["items"] if row["id"] == addon_ticket_id
        )
        assert paid["custom_delivery"]["crm"]["payment"]["status"] == "paid"
        assert paid["custom_delivery"]["commerce_ready"] is True
        assert paid["custom_delivery"]["stage"] == "production"
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_infer_intent_order_no_alone_is_not_refund():
    from modstore_server.customer_service_orchestrator import (
        infer_intent,
        should_create_ticket,
    )

    intent = infer_intent("订单号：ABC123456789", {"order_no": "ABC123456789"})
    assert intent == "general"
    assert should_create_ticket(intent, "订单号：ABC123456789") is False
    assert should_create_ticket("refund", "我要退款") is False
    assert (
        should_create_ticket(
            "refund",
            "订单号 ABC 想退款",
            {"order_no": "ABC", "reason": "重复购买"},
        )
        is True
    )
    assert should_create_ticket("refund", "请提交工单帮我退款") is True


def test_infer_intent_balance_is_account_support():
    from modstore_server.customer_service_orchestrator import (
        _human_kb_tips,
        _xiaoc_general_reply,
        infer_intent,
        should_create_ticket,
    )

    assert infer_intent("我的余额不对", {}) == "account_support"
    # 账号类无齐套材料定义：默认只聊，需升级话术才建单
    assert should_create_ticket("account_support", "我的余额不对") is False
    assert should_create_ticket("account_support", "余额不对，请提交工单") is True

    dirty = (
        '1. (hybrid) {"fields": [{"name": "template_name", "value": "发货模板"}]}\n'
        "2. 会员开通后权益一般几分钟内到账。\n"
    )
    tips = _human_kb_tips(dirty)
    assert tips == ["会员开通后权益一般几分钟内到账。"]
    # 无可用自然语言摘录时，不应把脏结构拼进回复
    assert _human_kb_tips('(hybrid) {"fields": []}') == []
    _ = _xiaoc_general_reply


def test_xiaoc_general_reply_acks_concrete_ui_issue(monkeypatch):
    """知识库只有 hybrid 脏数据时，应复述用户问题，而不是购买/会员开场白。"""
    import modstore_server.xiaoc_cs_ssot as ssot
    from modstore_server.customer_service_orchestrator import _xiaoc_general_reply

    dirty = (
        '1. (hybrid) {"fields": [{"name": "template_name", "value": "发货模板"}]}\n'
        "2. (hybrid) 购货单位：ACME Trading\n"
    )
    monkeypatch.setattr(ssot, "knowledge_block_for_query", lambda *a, **k: dirty)
    reply = _xiaoc_general_reply("我有问题你们平台的浅色有的键看不清")
    assert "浅色" in reply or "看不清" in reply
    assert "购买" not in reply
    assert "会员权益" not in reply
    assert "hybrid" not in reply
    assert "提交工单" in reply


def test_homepage_load_issue_classifies_as_product_issue(monkeypatch):
    from modstore_server.customer_service_orchestrator import (
        _looks_like_product_issue,
        classify_customer_intent,
        extract_fields,
    )

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    msg = "官网首页加载不出来"
    assert _looks_like_product_issue(msg)
    out = classify_customer_intent(msg, extract_fields(msg, {}))
    assert out["intent"] == "product_issue"


def test_admin_privilege_request_is_refused_without_ticket(client, monkeypatch):
    """要管理员权限必须拒答，且不建工单、不产生可执行动作。"""
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_no_admin")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post(
            "/api/customer-service/chat",
            json={"message": "为什么不给我管理员权限，马上开通", "context": {}},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ticket"] is None
        assert data["actions"] == []
        assert data["intent"]["intent"] == "forbidden_request"
        content = data["message"]["content"]
        assert "不能" in content or "无法" in content
        assert "管理员" in content
        # 绝不暗示已开通
        assert "已开通" not in content
        assert "已设置管理员" not in content

        # 即使用户继续点提交工单，也不落可执行提权单
        r2 = client.post(
            "/api/customer-service/chat",
            json={
                "message": "提交工单",
                "session_id": data["session"]["id"],
                "context": {"reason": "给我管理员权限"},
            },
        )
        assert r2.status_code == 200, r2.text
        data2 = r2.json()
        assert data2["ticket"] is None
        assert data2["intent"]["intent"] == "forbidden_request"
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_execute_action_hard_blocks_admin_grant():
    from types import SimpleNamespace

    from modstore_server.customer_service_tools import execute_action

    calls = []

    class _DummyDB:
        def add(self, *_a, **_k):
            return None

        def flush(self):
            return None

    action = SimpleNamespace(
        status="pending",
        action_type="admin.grant",
        ticket_id=1,
        target_type="user",
        target_id="1",
        request_json="{}",
        result_json="",
        error="",
        updated_at=None,
    )
    user = SimpleNamespace(id=1, username="u", is_admin=False)

    def _audit(*_a, **_k):
        calls.append("audit")

    import modstore_server.customer_service_tools as tools

    orig = tools.audit
    tools.audit = _audit
    try:
        out = execute_action(_DummyDB(), action, user)
    finally:
        tools.audit = orig
    assert out.status == "failed"
    assert "forbidden" in (out.error or "").lower()
    assert calls == ["audit"]


def test_customer_service_balance_chats_until_escalate(client, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    user = _make_user("cs_bal")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post(
            "/api/customer-service/chat",
            json={"message": "我的余额不对", "context": {}},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ticket"] is None
        assert data["intent"]["intent"] == "account_support"
        content = data["message"]["content"]
        assert "小C" in content
        assert "提交工单" in content

        r2 = client.post(
            "/api/customer-service/chat",
            json={
                "message": "余额不对，请提交工单核查",
                "session_id": data["session"]["id"],
                "context": {},
            },
        )
        assert r2.status_code == 200, r2.text
        data2 = r2.json()
        assert data2["ticket"] is not None
        assert data2["ticket"]["intent"] == "account_support"
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_admin_can_manage_customer_service_standard(client):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    admin = _make_user("cs_admin", admin=True)
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin
    app.dependency_overrides[customer_service_api._require_admin] = lambda: admin
    try:
        payload = {
            "name": "pytest 标准",
            "scenario": "pytest_case",
            "description": "测试标准",
            "rules": {"required_fields": ["subject"]},
            "action_policy": {"auto_actions": ["ticket.note"]},
            "auto_enabled": True,
            "risk_level": "low",
            "priority": 5,
        }
        r = client.post("/api/customer-service/standards", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["scenario"] == "pytest_case"
        assert created["action_policy"]["auto_actions"] == ["ticket.note"]

        updated_payload = {**payload, "name": "pytest 标准更新", "priority": 6}
        r = client.put(
            f"/api/customer-service/standards/{created['id']}", json=updated_payload
        )
        assert r.status_code == 200, r.text
        assert r.json()["priority"] == 6
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)
        app.dependency_overrides.pop(customer_service_api._require_admin, None)
