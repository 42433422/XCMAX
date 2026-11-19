"""Exercise the original chat, persisted repair and owner-only acceptance together."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from modstore_server import customer_corp_download_reconciliation as site
from modstore_server.api.deps import get_current_user
from modstore_server.app import app
from modstore_server.corp_download_deployment import CorpDownloadDeployment
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import get_session_factory
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceMessage,
    CustomerServiceTicket,
)
from tests.test_customer_issue_delivery_pipeline import github_fixture, seed_repair
from tests.test_customer_service_api import _make_user

BASE = "/api/customer-service"
REPORT = (
    "XCAGI 官网下载路径带末尾斜杠时返回 404。复现：在未登录浏览器依次打开 "
    "https://xiu-ci.com/download 和 https://xiu-ci.com/download/。"
    "前者返回 200，显示 XCAGI 产品下载，后者返回 404；www 域名同样。"
    "预期：带末尾斜杠的分享链接也能进入同一下载页，或跳转到正确地址。实际故障可复现。"
)


@pytest.fixture
def ticket_case(client, monkeypatch, approved_support_assessment):
    owner = _make_user(f"website-owner-{uuid4().hex[:8]}")
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    monkeypatch.setattr(
        "modstore_server.customer_service_api._schedule_customer_ticket_incident", lambda _: None
    )
    report = client.post(f"{BASE}/chat", json={"message": REPORT})
    assert report.status_code == 200, report.text
    assert report.json()["ticket"] is None
    session_id = report.json()["session"]["id"]
    intake = client.post(f"{BASE}/chat", json={"message": "提交工单", "session_id": session_id})
    assert intake.status_code == 200, intake.text
    ticket_id = intake.json()["ticket"]["id"]
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        seed_repair(db, ticket)
        evidence = json_loads(ticket.evidence_json, {})
        case = evidence["corp_download_case"]
        original = db.get(CustomerServiceMessage, case["source_message_id"])
        assert original.content == REPORT and original.ticket_id == ticket_id
        assert ticket.user_id == owner.id and ticket.assigned_admin_id is None
    yield owner, ticket_id
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        ticket.status = "expired"
        db.commit()


def _deployment(*, offset=timedelta()):
    return CorpDownloadDeployment("c" * 40, 4123, 1, datetime.now(UTC) + offset)


def test_released_route_writes_original_ticket_once_then_customer_confirms_or_reopens(
    client, ticket_case, monkeypatch
):
    owner, ticket_id = ticket_case
    github_fixture(monkeypatch)
    monkeypatch.setattr(site, "read_corp_download_deployment", _deployment)
    decision_endpoint = f"{BASE}/issues/{ticket_id}/decision"
    detail_endpoint = f"{BASE}/tickets/{ticket_id}?include_transcript=true"
    confirm = {
        "decision": "resolved",
        "note": "已复验两个地址且可以下载",
        "idempotency_key": "route-confirm-1",
    }
    assert (
        client.get(detail_endpoint).json()["ticket"]["customer_acceptance"]["can_resolve"] is False
    )
    assert client.post(decision_endpoint, json=confirm).status_code == 409

    assert site.reconcile_corp_download_tickets() == 1
    assert site.reconcile_corp_download_tickets() == 0
    ready = client.get(detail_endpoint).json()
    assert ready["ticket"]["status"] == "awaiting_customer"
    assert ready["ticket"]["customer_acceptance"]["can_resolve"] is True
    assert not ready["ticket"]["closed_at"]
    messages = [
        m for m in ready["messages"] if m["payload"].get("origin") == "corp_download_verification"
    ]
    assert len(messages) == 1 and messages[0]["ticket_id"] == ticket_id
    with get_session_factory()() as db:
        act = (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=ticket_id, action_type=site._RECEIPT_ACTION)
            .one()
        )
        proof = json_loads(act.result_json, {})
        assert proof["deployed_sha"] == "c" * 40 and proof["fix_sha"] == "b" * 40
        assert proof["original_path"] == "/download/" and act.user_id == owner.id
        check = (
            db.query(CustomerServiceAuditLog)
            .filter_by(ticket_id=ticket_id, event_type="corp_download_verified")
            .one()
        )
        assert check.actor_user_id is None and check.actor_type == "system"

    other = _make_user(f"website-other-{uuid4().hex[:8]}")
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: other)
    assert client.post(decision_endpoint, json=confirm).status_code == 404
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    assert client.post(decision_endpoint, json=confirm).json()["issue"]["status"] == "resolved"
    closed = client.get(detail_endpoint).json()["ticket"]
    assert closed["closed_at"] and closed["status"] == "resolved"
    reopened = client.post(
        decision_endpoint,
        json={
            "decision": "reopen",
            "note": "现在重新访问仍有问题",
            "idempotency_key": "route-reopen-1",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert site.reconcile_corp_download_tickets() == 0
    view = client.get(detail_endpoint).json()["ticket"]
    assert view["status"] == "processing" and not view["customer_acceptance"]["can_resolve"]


@pytest.mark.parametrize(
    "fault", ["stale_deploy", "ci", "ancestry", "revocation_race", "new_owner_message"]
)
def test_corp_download_writes_require_current_approved_and_unrevoked_scope(
    ticket_case, monkeypatch, fault
):
    _, ticket_id = ticket_case
    github_fixture(monkeypatch, failure=fault)

    def deploy():
        if fault == "revocation_race":
            with get_session_factory()() as db:
                ticket = db.get(CustomerServiceTicket, ticket_id)
                evidence = json_loads(ticket.evidence_json, {})
                evidence["dispatch_revocation"] = {"request_id": "real revocation after selection"}
                ticket.evidence_json = json_dumps(evidence)
                db.commit()
        if fault == "new_owner_message":
            with get_session_factory()() as db:
                ticket = db.get(CustomerServiceTicket, ticket_id)
                db.add(
                    CustomerServiceMessage(
                        ticket_id=ticket.id,
                        session_id=ticket.session_id,
                        user_id=ticket.user_id,
                        role="user",
                        content="我刚刚补充了原故障的复现情况。",
                    )
                )
                db.commit()
        return _deployment(offset=-timedelta(days=1) if fault == "stale_deploy" else timedelta())

    monkeypatch.setattr(site, "read_corp_download_deployment", deploy)
    assert site.reconcile_corp_download_tickets() == 0
    with get_session_factory()() as db:
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=ticket_id, action_type=site._RECEIPT_ACTION)
            .count()
            == 0
        )
