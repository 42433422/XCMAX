"""Unassigned tickets stay open until a named admin accepts them."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("fastapi")

from modstore_server import customer_service_api  # noqa: E402
from modstore_server.app import app  # noqa: E402
from modstore_server.models import User, get_session_factory  # noqa: E402
from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket  # noqa: E402


@pytest.fixture(autouse=True)
def restore_auth_overrides():
    """Every role switch belongs to this case, including its failure paths."""
    previous = app.dependency_overrides.copy()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def _user(*, admin: bool) -> User:
    name = f"human_{uuid.uuid4().hex[:8]}"
    with get_session_factory()() as db:
        user = User(
            username=name,
            email=f"{name}@pytest.local",
            password_hash="x",
            is_admin=admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def _ticket(owner: User, *, legacy: bool = False) -> int:
    with get_session_factory()() as db:
        session = CustomerServiceSession(user_id=owner.id, channel="customer_issue_intake")
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            user_id=owner.id,
            session_id=session.id,
            ticket_no=f"{'CS' if legacy else 'CI'}{uuid.uuid4().hex}",
            title="客户端产品缺陷 · 员工图谱无法显示",
            summary="登录后员工节点无法显示。步骤：打开员工图谱。期望：有节点。实际：暂无员工。",
            intent="product_issue",
            status="open",
            decision_status="pending",
        )
        db.add(ticket)
        db.commit()
        return int(ticket.id)


def _as(user: User):
    from fastapi import HTTPException

    from modstore_server import customer_issue_api
    from modstore_server.api import deps

    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[customer_issue_api.get_current_user] = lambda: user

    def gate():
        if not getattr(user, "is_admin", False):
            raise HTTPException(403, "需要管理员")
        return user

    app.dependency_overrides[customer_service_api._require_admin] = gate


@pytest.mark.parametrize("kind", ["invalid", "out_of_scope"])
def test_disposition_is_scoped_replayable_and_fences_late_work(client, kind):
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.db.mac_control import MacControlTask
    from modstore_server.mac_control_store import accept

    customer, another_customer = _user(admin=False), _user(admin=False)
    admin, another_admin = _user(admin=True), _user(admin=True)
    ticket_id, another_ticket_id = _ticket(customer), _ticket(another_customer)
    path = f"/api/customer-service/tickets/{ticket_id}"
    body = {
        "disposition": kind,
        "request_id": str(uuid.uuid4()),
        "note": "原单核对完成，描述未构成平台受理的问题。",
        "verification": "已对照正式受理范围与当前页面说明，并逐项复核了提交人提供的原始记录。",
    }
    _as(customer)
    assert client.post(f"{path}/disposition", json=body).status_code == 403
    _as(admin)
    assert (
        client.post(
            f"{path}/assign", json={"assignee_id": admin.id, "reason": "指派核查原单"}
        ).status_code
        == 200
    )
    assert client.post(f"{path}/accept", json={"reason": "受理原工单"}).status_code == 200
    assert client.post(f"{path}/disposition", json=body).status_code == 409
    assert client.post(f"{path}/diagnose", json={"reason": body["verification"]}).status_code == 200
    _as(another_admin)
    assert client.post(f"{path}/disposition", json=body).status_code == 403

    with get_session_factory()() as db:

        def make_task(owner, target):
            return accept(
                db,
                actor="employee:fixture",
                key=uuid.uuid4().hex,
                request={"source": "employee", "ticket_id": target, "customer_id": owner.id},
            )

        queued_id = make_task(customer, ticket_id).id
        other_id = make_task(another_customer, another_ticket_id).id
        active_id = None
        if kind == "out_of_scope":
            active = make_task(customer, ticket_id)
            active.attempt_id, active.para_task_id, active.state = (
                "attempt",
                "exact-para-id",
                "running",
            )
            db.commit()
            active_id = active.id

    _as(admin)
    closed = client.post(f"{path}/disposition", json=body)
    assert closed.status_code == 200, closed.text
    ticket = closed.json()["ticket"]
    assert ticket["status"] == "rejected" and ticket["closed_at"]
    assert "fault_remains" not in ticket["evidence"]
    assert ticket["evidence"]["diagnoses"]
    assert ticket["disposition"]["kind"] == kind
    stop = ticket["disposition"]["execution_stop"]
    assert stop["state"] == ("stop_unconfirmed" if active_id else "dispatch_blocked")
    assert stop["new_dispatch_blocked"] is True
    assert client.post(f"{path}/disposition", json=body).json()["replayed"] is True
    assert (
        client.post(f"{path}/disposition", json={**body, "note": body["note"] + "变更"}).status_code
        == 409
    )
    readback = client.get(path).json()
    assert readback["ticket"]["disposition"] == ticket["disposition"]
    assert len([a for a in readback["actions"] if a["action_type"] == "ticket.disposition"]) == 1

    with get_session_factory()() as db:
        assert db.get(MacControlTask, queued_id).state == "cancelled"
        assert db.get(MacControlTask, other_id).state == "queued"
        if active_id:
            assert db.get(MacControlTask, active_id).state == "cancel_requested"
            assert any(row["para_task_id"] == "exact-para-id" for row in stop["mac_control_tasks"])
        assert (
            apply_customer_ticket_incident_progress(
                db, ticket_id=ticket_id, event_id=1, team_ok=True
            )["replayed"]
            is True
        )

    _as(customer)
    public = client.get(path).json()["ticket"]
    assert set(public["disposition"]) == {"kind", "at", "note"}
    messages = client.get(f"/api/customer-service/sessions/{ticket['session_id']}").json()[
        "messages"
    ]
    assert len(messages) == 1 and body["note"] in messages[0]["content"]
    assert messages[0]["payload"] == {"origin": "admin_disposition"}
    assert (
        client.post(
            f"/api/customer-service/issues/{ticket_id}/decision",
            json={
                "decision": "reopen",
                "note": "原样本复查",
                "idempotency_key": "negative-reopen-1",
            },
        ).status_code
        == 409
    )


def test_revoke_dispatch_preserves_original_ticket_and_fences_queued_work(client):
    from modstore_server.customer_issue_intake import dispatch_issue_event, enqueue_issue
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.customer_service_tools import json_dumps
    from modstore_server.db.mac_control import MacControlTask
    from modstore_server.mac_control_store import accept
    from modstore_server.mac_control_worker import reconcile

    owner, admin, another_admin = _user(admin=False), _user(admin=True), _user(admin=True)
    ticket_id, other_id = _ticket(owner), _ticket(owner)
    path = f"/api/customer-service/tickets/{ticket_id}"
    body = {"request_id": str(uuid.uuid4()), "note": "原问题保留，停止自动派发后转人工诊断。"}
    _as(owner)
    assert client.post(f"{path}/dispatch-revoke", json=body).status_code == 403
    _as(admin)
    assert (
        client.post(
            f"{path}/assign", json={"assignee_id": admin.id, "reason": "安排人工处理原单"}
        ).status_code
        == 200
    )
    assert client.post(f"{path}/accept", json={"reason": "接受原始问题"}).status_code == 200
    _as(another_admin)
    assert client.post(f"{path}/dispatch-revoke", json=body).status_code == 403
    _as(admin)
    with get_session_factory()() as db:

        def task_for(target, actor="employee:fixture"):
            return accept(
                db,
                actor=actor,
                key=uuid.uuid4().hex,
                request={"source": "employee", "ticket_id": target, "customer_id": owner.id},
            )

        queued_id = task_for(ticket_id).id
        unrelated_id = task_for(other_id).id
        manually_owned_id = task_for(ticket_id, actor=f"admin:{admin.id}").id
        active = task_for(ticket_id)
        active.attempt_id, active.para_task_id, active.state = "attempt", "exact-para-id", "running"
        active_id = active.id
        db.get(CustomerServiceTicket, ticket_id).evidence_json = json_dumps(
            {"resolution": {"team": [{"role": "fix", "employee_id": "previous-employee"}]}}
        )
        db.commit()
    original = client.get(path).json()["ticket"]
    response = client.post(f"{path}/dispatch-revoke", json=body)
    assert response.status_code == 200, response.text
    stopped = response.json()["ticket"]
    assert stopped["status"] == original["status"] == "processing"
    assert stopped["decision_status"] == original["decision_status"]
    assert stopped["closed_at"] == original["closed_at"] == ""
    assert "disposition" not in stopped
    receipt = stopped["dispatch_revocation"]
    assert receipt["execution_stop"]["state"] == "stop_unconfirmed"
    assert receipt["execution_stop"]["new_dispatch_blocked"] is True
    assert client.post(f"{path}/dispatch-revoke", json=body).json()["replayed"] is True
    assert (
        client.post(
            f"{path}/dispatch-revoke", json={**body, "request_id": str(uuid.uuid4())}
        ).status_code
        == 409
    )

    envelope = {"id": "previously-enqueued", "data": {"ticket_id": ticket_id, "user_id": owner.id}}
    assert dispatch_issue_event(envelope) == {
        "ok": True,
        "skipped": True,
        "reason": "ticket_dispatch_revoked",
    }
    with get_session_factory()() as db:
        assert db.get(MacControlTask, queued_id).state == "cancelled"
        assert db.get(MacControlTask, active_id).state == "cancel_requested"
        assert db.get(MacControlTask, unrelated_id).state == "queued"
        assert db.get(MacControlTask, manually_owned_id).state == "queued"
        assert not enqueue_issue(db, db.get(CustomerServiceTicket, ticket_id))
        assert (
            apply_customer_ticket_incident_progress(
                db, ticket_id=ticket_id, event_id=1, team_ok=True
            )["replayed"]
            is True
        )
    detail = client.get(path).json()
    assert detail["ticket"]["dispatch_revocation"] == receipt
    assert detail["execution_overview"]["blocker"] == "dispatch_revoked"
    responsible = detail["execution_overview"]["responsible"]
    assert responsible["kind"] == "admin" and responsible["id"] == admin.id
    prior_receipts = {
        row["id"]: row for row in detail["execution_overview"]["revocation_task_receipts"]
    }
    assert prior_receipts[active_id]["state"] == "cancel_requested"
    assert len([a for a in detail["actions"] if a["action_type"] == "ticket.dispatch_revoke"]) == 1
    with get_session_factory()() as db:

        class StoppedExecutor:
            def task(self, task_id):
                assert task_id == "exact-para-id"
                return {"id": task_id, "status": "cancelled"}

        reconcile(db, db.get(MacControlTask, active_id), StoppedExecutor())
    refreshed = client.get(path).json()
    assert refreshed["ticket"]["dispatch_revocation"] == receipt
    assert {
        row["id"]: row["state"]
        for row in refreshed["execution_overview"]["revocation_task_receipts"]
    }[active_id] == "cancelled"
    assert client.post(f"{path}/diagnose", json={"reason": "继续人工核查原问题"}).status_code == 200
    _as(owner)
    public = client.get(path).json()["ticket"]
    assert public["dispatch_status"] == "revoked"
    assert public["status"] == "processing" and "dispatch_revocation" not in public


def test_verified_repair_cannot_be_dismissed(client):
    from modstore_server.customer_service_tools import json_dumps

    customer, admin = _user(admin=False), _user(admin=True)
    ticket_id = _ticket(customer)
    path = f"/api/customer-service/tickets/{ticket_id}"
    _as(admin)
    body = {
        "disposition": "invalid",
        "request_id": str(uuid.uuid4()),
        "note": "原单已有真实修复证据，必须沿用原验收。",
        "verification": "已核对同一软件版本及修复动作，确认需要保留已有修复和正式验收回执。",
    }
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        ticket.status, ticket.assigned_admin_id = "processing", admin.id
        ticket.evidence_json = json_dumps(
            {
                "diagnoses": [{"operator_id": admin.id}],
                "resolution": {"repair_verified": True},
            }
        )
        db.commit()
    assert client.post(f"{path}/disposition", json=body).status_code == 409
    assert (
        client.post(
            f"{path}/dispatch-revoke", json={"request_id": body["request_id"], "note": body["note"]}
        ).status_code
        == 409
    )


def test_human_loop_blocks_false_close_and_keeps_history(client):
    customer = _user(admin=False)
    first = _user(admin=True)
    second = _user(admin=True)
    outsider = _user(admin=False)
    ticket_id = _ticket(customer, legacy=True)
    http = client

    _as(outsider)
    denied = http.post(
        f"/api/customer-service/tickets/{ticket_id}/assign",
        json={"assignee_id": first.id, "reason": "普通客户不能指派"},
    )
    assert denied.status_code == 403

    _as(first)
    assigned = http.post(
        f"/api/customer-service/tickets/{ticket_id}/assign",
        json={"assignee_id": first.id, "reason": "指派给技术管理员"},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["ticket"]["status"] == "open"
    assert assigned.json()["ticket"]["assigned_admin_id"] == first.id

    _as(second)
    stolen = http.post(
        f"/api/customer-service/tickets/{ticket_id}/accept",
        json={"reason": "不是当前处理人"},
    )
    assert stolen.status_code == 403

    _as(first)
    accepted = http.post(
        f"/api/customer-service/tickets/{ticket_id}/accept",
        json={"reason": "开始核查员工图谱"},
    )
    assert accepted.json()["ticket"]["status"] == "processing"
    http.post(
        f"/api/customer-service/tickets/{ticket_id}/diagnose",
        json={"reason": "企业员工工作流全景四层均暂无员工 Mod，总工位为 0"},
    )
    blocked = http.post(
        f"/api/customer-service/tickets/{ticket_id}/result",
        json={"text": "原故障仍在，员工节点仍未出现", "fault_remains": True},
    )
    assert blocked.json()["ticket"]["status"] == "processing"
    _as(customer)
    visible = next(
        row
        for row in http.get("/api/customer-service/issues/mine").json()["items"]
        if row["id"] == ticket_id
    )
    assert visible["latest_result"]["source"] == "human"
    assert visible["latest_result"]["fault_remains"] is True
    assert "原故障仍在" in visible["latest_result"]["progress"]
    assert visible["can_resolve"] is False
    assert visible["can_reopen"] is False
    still_open = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "reopen",
            "note": "故障还在但不能重开",
            "idempotency_key": "reopen-while-open",
        },
    )
    assert still_open.status_code == 409
    _as(customer)
    close = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "resolved",
            "note": "我确认已经好了",
            "idempotency_key": "close-too-soon-1",
        },
    )
    assert close.status_code == 409

    _as(first)
    requested = http.post(
        f"/api/customer-service/tickets/{ticket_id}/sensitive-action",
        json={"change": "调整客户可见配置", "reason": "需要改显示配置才能复现"},
    )
    assert requested.json()["status"] == "waiting_approval"
    assert requested.json()["executed"] is False
    _as(second)
    rejected = http.post(
        f"/api/customer-service/tickets/{ticket_id}/sensitive-action/decision",
        json={
            "action_id": requested.json()["action_id"],
            "decision": "rejected",
            "reason": "没有充分理由",
        },
    )
    assert rejected.json()["executed"] is False
    assert rejected.json()["status"] == "rejected"

    _as(first)
    self_check = http.post(
        f"/api/customer-service/tickets/{ticket_id}/result",
        json={"text": "处理人自己宣布复测通过", "fault_remains": False},
    )
    assert self_check.status_code == 403
    _as(second)
    ready = http.post(
        f"/api/customer-service/tickets/{ticket_id}/result",
        json={"text": "另一位管理员复测员工图谱已显示节点", "fault_remains": False},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["ticket"]["status"] == "awaiting_customer"
    assert ready.json()["ticket"]["lifecycle_label"] == "待客户确认"
    _as(customer)
    confirmed = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "resolved",
            "note": "员工节点已经显示",
            "idempotency_key": "customer-ok-0001",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["issue"]["status"] == "resolved"
    reopened = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "reopen",
            "note": "节点再次消失",
            "idempotency_key": "customer-reopen-1",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["issue"]["status"] == "processing"
    assert reopened.json()["issue"]["reopen_count"] == 1

    _as(second)
    moved = http.post(
        f"/api/customer-service/tickets/{ticket_id}/assign",
        json={"assignee_id": second.id, "reason": "重开后改派"},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()["ticket"]
    assert body["status"] == "open"
    assert body["assigned_admin_id"] == second.id
    history = body["evidence"]["assignment_history"]
    assert [row["assignee_id"] for row in history] == [first.id, second.id]
    assert any(row["action"] == "ticket_diagnosed" for row in body["evidence"]["handling_history"])
