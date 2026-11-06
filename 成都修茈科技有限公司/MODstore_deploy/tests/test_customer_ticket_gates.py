"""Approval is irreversible, and same-status writes cannot drop each other."""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import HTTPException

pytest.importorskip("fastapi")

from modstore_server.customer_service_tools import (  # noqa: E402
    _GATED_EXECUTORS,
    execute_action,
    json_loads,
    register_gated_change_executor,
)
from modstore_server.customer_ticket_human_ops import (  # noqa: E402
    accept_ticket,
    assign_ticket,
    decide_sensitive_action,
    record_diagnosis,
    request_sensitive_action,
    submit_result,
)
from modstore_server.models import User, get_session_factory  # noqa: E402
from modstore_server.models_cs import (  # noqa: E402
    CustomerServiceAction,
    CustomerServiceSession,
    CustomerServiceTicket,
)


def _user(*, admin: bool) -> User:
    name = f"gate_{uuid.uuid4().hex[:8]}"
    with get_session_factory()() as db:
        user = User(username=name, email=f"{name}@pytest.local", password_hash="x", is_admin=admin)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def _open_ticket(owner: User) -> int:
    with get_session_factory()() as db:
        session = CustomerServiceSession(user_id=owner.id, channel="customer_issue_intake")
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            user_id=owner.id,
            session_id=session.id,
            ticket_no=f"CI{uuid.uuid4().hex}",
            title="客户端产品缺陷 · 员工图谱无法显示",
            summary="登录后员工节点无法显示。步骤：打开员工图谱。期望：有节点。实际：暂无员工。",
            intent="product_issue",
            status="open",
            decision_status="pending",
        )
        db.add(ticket)
        db.commit()
        return int(ticket.id)


def _processing_ticket(owner: User, assignee: User) -> int:
    ticket_id = _open_ticket(owner)
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, assignee.id)
        assert ticket is not None and actor is not None
        assign_ticket(db, ticket, actor, assignee.id, "指派给当前处理人")
        accept_ticket(db, ticket, actor, "开始处理")
        return ticket_id


def _snapshot(ticket_id: int) -> dict:
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        assert ticket is not None
        return {
            "status": ticket.status,
            "version": int(ticket.lock_version or 0),
            "assignee": ticket.assigned_admin_id,
            "evidence": json_loads(ticket.evidence_json, {}),
        }


def _action(action_id: int) -> CustomerServiceAction:
    with get_session_factory()() as db:
        action = db.get(CustomerServiceAction, action_id)
        assert action is not None
        db.expunge(action)
        return action


def _race(calls: list) -> list:
    barrier = threading.Barrier(len(calls))
    outcomes: list = [None] * len(calls)

    def run(index: int) -> None:
        db = get_session_factory()()
        db.expire_on_commit = False
        try:
            outcomes[index] = calls[index](db, barrier)
        except Exception as exc:  # noqa: BLE001 — 失败的一方就是这次并发的结果
            outcomes[index] = exc
        finally:
            db.close()

    threads = [threading.Thread(target=run, args=(index,)) for index in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    return outcomes


def _one_winner(outcomes: list):
    winners = [item for item in outcomes if not isinstance(item, Exception)]
    losers = [item for item in outcomes if isinstance(item, HTTPException)]
    assert len(winners) == 1, outcomes
    assert len(losers) == len(outcomes) - 1
    assert all(item.status_code == 409 for item in losers)
    return winners[0]


def test_rejected_approval_cannot_be_reset_and_approved(client):
    del client
    owner = _user(admin=False)
    assignee = _user(admin=True)
    approver = _user(admin=True)
    ticket_id = _processing_ticket(owner, assignee)
    calls = {"n": 0}

    def executor(_request):
        calls["n"] += 1
        return {"ok": True, "verified": True}

    register_gated_change_executor("调整客户可见配置", executor)
    try:
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, assignee.id)
            requested = request_sensitive_action(
                db, ticket, actor, "调整客户可见配置", "需要改显示配置"
            )
        action_id = int(requested["action_id"])
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, approver.id)
            rejected = decide_sensitive_action(
                db, ticket, actor, action_id, decision="rejected", reason="没有充分理由"
            )
        assert rejected["status"] == "rejected"
        assert rejected["executed"] is False
        with get_session_factory()() as db:
            action = db.get(CustomerServiceAction, action_id)
            assert action is not None
            action.status = "pending"
            db.commit()
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, approver.id)
            with pytest.raises(HTTPException) as denied:
                decide_sensitive_action(
                    db, ticket, actor, action_id, decision="approved", reason="拒绝后又想批准"
                )
        assert denied.value.status_code == 409
        action = _action(action_id)
        assert action.status == "rejected"
        assert json_loads(action.result_json, {})["executed"] is False
        with get_session_factory()() as db:
            row = db.get(CustomerServiceAction, action_id)
            actor = db.get(User, approver.id)
            assert row is not None and actor is not None
            row.status = "pending"
            execute_action(db, row, actor)
            db.commit()
            assert row.status == "rejected"
        assert calls["n"] == 0
    finally:
        _GATED_EXECUTORS.pop("调整客户可见配置", None)


def test_duplicate_decision_and_stale_ticket_status_fail(client):
    del client
    owner = _user(admin=False)
    assignee = _user(admin=True)
    approver = _user(admin=True)
    ticket_id = _processing_ticket(owner, assignee)
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, assignee.id)
        requested = request_sensitive_action(
            db, ticket, actor, "调整客户可见配置", "需要改显示配置"
        )
    action_id = int(requested["action_id"])
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        assert ticket is not None
        ticket.status = "awaiting_customer"
        db.commit()
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, approver.id)
        with pytest.raises(HTTPException) as stale:
            decide_sensitive_action(
                db, ticket, actor, action_id, decision="approved", reason="工单状态已经变了"
            )
    assert stale.value.status_code == 409
    assert "失效" in str(stale.value.detail)
    assert _action(action_id).status == "waiting_approval"
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        assert ticket is not None
        ticket.status = "processing"
        db.commit()
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, approver.id)
        approved = decide_sensitive_action(
            db, ticket, actor, action_id, decision="approved", reason="同意这一次变更"
        )
    assert approved["status"] == "pending_execution"
    assert approved["executed"] is False
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, approver.id)
        with pytest.raises(HTTPException) as duplicate:
            decide_sensitive_action(
                db, ticket, actor, action_id, decision="approved", reason="再批一次"
            )
    assert duplicate.value.status_code == 409
    action = _action(action_id)
    assert action.status == "pending_execution"
    assert json_loads(action.result_json, {})["executed"] is False
    assert json_loads(action.result_json, {})["approval_granted"] is True
    assert json_loads(action.result_json, {})["verified"] is False


def test_decision_reloads_ticket_status_before_approving(client):
    del client
    owner = _user(admin=False)
    assignee = _user(admin=True)
    approver = _user(admin=True)
    ticket_id = _processing_ticket(owner, assignee)
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, assignee.id)
        requested = request_sensitive_action(
            db, ticket, actor, "调整客户可见配置", "需要改显示配置"
        )
    action_id = int(requested["action_id"])
    db = get_session_factory()()
    db.expire_on_commit = False
    try:
        stale = db.get(CustomerServiceTicket, ticket_id)
        actor = db.get(User, approver.id)
        assert stale is not None and actor is not None
        assert stale.status == "processing"
        db.commit()
        with get_session_factory()() as other:
            current = other.get(CustomerServiceTicket, ticket_id)
            assert current is not None
            current.status = "open"
            other.commit()
        with pytest.raises(HTTPException) as denied:
            decide_sensitive_action(
                db, stale, actor, action_id, decision="approved", reason="对象里的状态已经过期"
            )
        assert denied.value.status_code == 409
    finally:
        db.close()
    assert _action(action_id).status == "waiting_approval"


def test_verified_executor_runs_once_and_unverified_does_not_complete(client):
    del client
    owner = _user(admin=False)
    assignee = _user(admin=True)
    approver = _user(admin=True)
    ticket_id = _processing_ticket(owner, assignee)
    calls = {"verified": 0, "plain": 0}

    def verified(_request):
        calls["verified"] += 1
        return {"ok": True, "verified": True}

    def plain(_request):
        calls["plain"] += 1
        return {"ok": True, "verified": False}

    register_gated_change_executor("核验后的配置变更", verified)
    register_gated_change_executor("未核验的配置变更", plain)
    plain_ticket_id = _processing_ticket(owner, assignee)
    try:
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, assignee.id)
            verified_request = request_sensitive_action(
                db, ticket, actor, "核验后的配置变更", "需要改显示配置"
            )
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, plain_ticket_id)
            actor = db.get(User, assignee.id)
            plain_request = request_sensitive_action(
                db, ticket, actor, "未核验的配置变更", "另一项还不能核验"
            )
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, approver.id)
            done = decide_sensitive_action(
                db,
                ticket,
                actor,
                int(verified_request["action_id"]),
                decision="approved",
                reason="执行器可以核验",
            )
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, plain_ticket_id)
            actor = db.get(User, approver.id)
            held = decide_sensitive_action(
                db,
                ticket,
                actor,
                int(plain_request["action_id"]),
                decision="approved",
                reason="执行器没有核验",
            )
        assert done["status"] == "completed"
        assert done["executed"] is True
        assert held["status"] == "pending_execution"
        assert held["executed"] is False
        with get_session_factory()() as db:
            row = db.get(CustomerServiceAction, int(verified_request["action_id"]))
            actor = db.get(User, approver.id)
            assert row is not None and actor is not None
            row.status = "pending"
            execute_action(db, row, actor)
            db.commit()
            assert row.status == "completed"
            body = json_loads(row.result_json, {})
        assert body["executed"] is True
        assert body["business_executed"] is True
        assert body["verified"] is True
        plain_action = _action(int(plain_request["action_id"]))
        plain_body = json_loads(plain_action.result_json, {})
        assert plain_body["approval_granted"] is True
        assert plain_body["business_executed"] is True
        assert plain_body["verified"] is False
        assert plain_body["executed"] is False
        assert calls == {"verified": 1, "plain": 1}
    finally:
        _GATED_EXECUTORS.pop("核验后的配置变更", None)
        _GATED_EXECUTORS.pop("未核验的配置变更", None)


def _loaded_call(ticket_id: int, user_id: int, invoke):
    def call(db, barrier):
        ticket = db.get(CustomerServiceTicket, ticket_id)
        user = db.get(User, user_id)
        assert ticket is not None and user is not None
        _ = (ticket.lock_version, ticket.status, ticket.evidence_json, ticket.assigned_admin_id)
        db.commit()
        barrier.wait(10)
        return invoke(db, ticket, user)

    return call


def test_concurrent_diagnosis_result_and_reassign_keep_one_history(client):
    del client
    owner = _user(admin=False)
    assignee = _user(admin=True)
    other = _user(admin=True)
    ticket_id = _processing_ticket(owner, assignee)
    diagnosed = _race(
        [
            _loaded_call(
                ticket_id,
                assignee.id,
                lambda db, ticket, user: record_diagnosis(db, ticket, user, "诊断结论甲：节点缺失"),
            ),
            _loaded_call(
                ticket_id,
                assignee.id,
                lambda db, ticket, user: record_diagnosis(db, ticket, user, "诊断结论乙：接口超时"),
            ),
        ]
    )
    _one_winner(diagnosed)
    evidence = _snapshot(ticket_id)["evidence"]
    texts = [row["text"] for row in evidence["diagnoses"]]
    assert len(texts) == 1
    assert texts[0] in {"诊断结论甲：节点缺失", "诊断结论乙：接口超时"}
    history = [
        row["reason"] for row in evidence["handling_history"] if row["action"] == "ticket_diagnosed"
    ]
    assert history == texts

    resulted = _race(
        [
            _loaded_call(
                ticket_id,
                assignee.id,
                lambda db, ticket, user: submit_result(
                    db, ticket, user, text="处理结果甲：故障仍在", fault_remains=True
                ),
            ),
            _loaded_call(
                ticket_id,
                assignee.id,
                lambda db, ticket, user: submit_result(
                    db, ticket, user, text="处理结果乙：故障仍在", fault_remains=True
                ),
            ),
        ]
    )
    _one_winner(resulted)
    evidence = _snapshot(ticket_id)["evidence"]
    assert evidence["handling_result"]["text"] in {"处理结果甲：故障仍在", "处理结果乙：故障仍在"}
    results = [
        row["reason"]
        for row in evidence["handling_history"]
        if row["action"] == "ticket_result_fault_remains"
    ]
    assert results == [evidence["handling_result"]["text"]]

    reassigned = _race(
        [
            _loaded_call(
                ticket_id,
                assignee.id,
                lambda db, ticket, user: assign_ticket(
                    db, ticket, user, other.id, "改派给另一位管理员"
                ),
            ),
            _loaded_call(
                ticket_id,
                other.id,
                lambda db, ticket, user: assign_ticket(
                    db, ticket, user, assignee.id, "改派回原处理人"
                ),
            ),
        ]
    )
    _one_winner(reassigned)
    snap = _snapshot(ticket_id)
    assert snap["status"] == "open"
    assert len(snap["evidence"]["assignment_history"]) == 2
    assert snap["version"] >= 1


def test_concurrent_approval_commits_one_decision(client):
    del client
    owner = _user(admin=False)
    assignee = _user(admin=True)
    first = _user(admin=True)
    second = _user(admin=True)
    ticket_id = _processing_ticket(owner, assignee)
    calls = {"n": 0}

    def executor(_request):
        calls["n"] += 1
        return {"ok": True, "verified": True}

    register_gated_change_executor("并发审批的配置变更", executor)
    try:
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, assignee.id)
            requested = request_sensitive_action(
                db, ticket, actor, "并发审批的配置变更", "需要改显示配置"
            )
        action_id = int(requested["action_id"])
        outcomes = _race(
            [
                _loaded_call(
                    ticket_id,
                    first.id,
                    lambda db, ticket, user: decide_sensitive_action(
                        db, ticket, user, action_id, decision="approved", reason="第一位管理员批准"
                    ),
                ),
                _loaded_call(
                    ticket_id,
                    second.id,
                    lambda db, ticket, user: decide_sensitive_action(
                        db, ticket, user, action_id, decision="rejected", reason="第二位管理员拒绝"
                    ),
                ),
            ]
        )
        _one_winner(outcomes)
        action = _action(action_id)
        assert action.status in {"completed", "rejected"}
        body = json_loads(action.result_json, {})
        if action.status == "completed":
            assert body["executed"] is True
            assert calls["n"] == 1
        else:
            assert body["executed"] is False
            assert calls["n"] == 0
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            actor = db.get(User, first.id)
            with pytest.raises(HTTPException) as again:
                decide_sensitive_action(
                    db, ticket, actor, action_id, decision="approved", reason="并发之后再批一次"
                )
        assert again.value.status_code == 409
        assert calls["n"] <= 1
    finally:
        _GATED_EXECUTORS.pop("并发审批的配置变更", None)
