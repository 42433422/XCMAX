from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def reader_case(client, monkeypatch, tmp_path):
    from modstore_server.customer_ticket_reader import SCOPE
    from modstore_server.models import User, get_session_factory
    from modstore_server.models_cs import (
        CustomerServiceAction,
        CustomerServiceAuditLog,
    )
    from tests.test_customer_service_api import _make_ticket

    token = "cst_ro_" + "test-only-not-a-live-credential" * 2
    ids, owners = [], []
    with get_session_factory()() as db:
        for n in range(3):
            user = User(username=uuid.uuid4().hex, password_hash="x", is_admin=False)
            db.add(user)
            db.flush()
            owners.append(user.id)
            ticket = _make_ticket(
                db,
                user,
                ticket_no=uuid.uuid4().hex,
                title=f"Ticket {n}",
                status="processing",
                summary="password=DO_NOT_EXPORT",
                evidence_json='{"token":"DO_NOT_EXPORT"}',
            )
            ids.append(ticket.id)
            db.add(
                CustomerServiceAction(
                    ticket_id=ticket.id,
                    user_id=user.id,
                    action_type="employee.dispatch",
                    status="failed",
                    idempotency_key=uuid.uuid4().hex,
                    result_json='{"roles":[{"role":"fix","ok":false,"status":"handler_failed"}],"token":"DO_NOT_EXPORT"}',
                )
            )
            db.add(
                CustomerServiceAuditLog(
                    ticket_id=ticket.id,
                    event_type="employee_progress",
                    actor_type="system",
                    detail_json='{"token":"DO_NOT_EXPORT"}',
                )
            )
        db.commit()
    config = {
        "instance_id": "instance-a",
        "company_id": "company-a",
        "owner_user_ids": owners[:2],
        "grants": [
            {
                "id": "dot-read",
                "principal": "dot",
                "scopes": [SCOPE],
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        ],
    }
    path = tmp_path / "grants.json"

    def save():
        path.write_text(json.dumps(config))
        path.chmod(0o600)

    save()
    monkeypatch.setenv("MODSTORE_TICKET_READ_GRANTS_FILE", str(path))
    monkeypatch.setenv("MODSTORE_INSTANCE_ID", "instance-a")
    return client, {"Authorization": f"Bearer {token}"}, ids, config, save, path


@pytest.fixture
def audit_capture(caplog):
    logger = logging.getLogger("modstore_server.customer_ticket_reader")
    logger.addHandler(caplog.handler)
    yield caplog
    logger.removeHandler(caplog.handler)


def test_company_reader_list_detail_pagination_and_redaction(reader_case, audit_capture):
    client, headers, ids, config, save, _ = reader_case
    audit_capture.set_level("INFO", logger="modstore_server.customer_ticket_reader")
    pages = [
        client.get(
            "/api/customer-service/tickets", headers=headers, params={"limit": 1, "offset": offset}
        )
        for offset in (0, 1, 2)
    ]
    assert [p.status_code for p in pages] == [200, 200, 200]
    assert all(p.json()["total"] == 2 for p in pages)
    assert {p.json()["items"][0]["id"] for p in pages[:2]} == set(ids[:2])
    assert pages[2].json()["items"] == []
    assert [p.json()["has_more"] for p in pages] == [True, False, False]
    for ticket_id in ids[:2]:
        response = client.get(f"/api/customer-service/tickets/{ticket_id}", headers=headers)
        assert response.status_code == 200
        assert "DO_NOT_EXPORT" not in response.text
        assert "evidence" not in response.json()["ticket"]
        assert response.json()["ticket"]["blockers"][0]["role"] == "fix"
        assert response.json()["ticket"]["blockers"][0]["status"] == "handler_failed"
        assert response.json()["ticket"]["is_overdue"] is None
        assert response.json()["ticket"]["assignment_status"] == "unassigned"
        assert response.json()["timeline"][0]["event_type"] == "employee_progress"
    assert client.get(f"/api/customer-service/tickets/{ids[2]}", headers=headers).status_code == 404
    assert "grant=dot-read" in audit_capture.text
    assert headers["Authorization"] not in audit_capture.text
    config["grants"][0]["principal"] = "grok-bot"
    save()
    assert client.get("/api/customer-service/tickets", headers=headers).status_code == 200


@pytest.mark.parametrize("kind", ["quoted_json", "chinese", "private_key", "database_uri"])
def test_free_text_credentials_are_redacted_in_list_and_detail(reader_case, kind):
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    client, headers, ids, *_ = reader_case
    canary = "SYNTHETIC_DO_NOT_EXPORT"
    values = {
        "quoted_json": '{"password":"' + canary + '"}',
        "chinese": "密码：" + canary,
        "private_key": "-----"
        + "BEGIN PRIVATE KEY"
        + "-----\n"
        + canary
        + "\n-----"
        + "END PRIVATE KEY"
        + "-----",
        "database_uri": "postgresql://" + "test:" + canary + "@localhost/test",
    }
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ids[0])
        row.title = "Safe issue context " + values[kind]
        row.summary = values[kind]
        db.commit()
    for path in ("/api/customer-service/tickets", f"/api/customer-service/tickets/{ids[0]}"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert canary not in response.text
        assert "Safe issue context" in response.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/customer-service/chat"),
        ("PUT", "/api/customer-service/standards/1"),
        ("GET", "/api/customer-service/sessions"),
        ("GET", "/api/customer-service/actions"),
        ("GET", "/api/auth/me"),
    ],
)
def test_service_grant_cannot_be_used_as_login_or_write_token(reader_case, method, path):
    client, headers, *_ = reader_case
    response = client.request(method, path, headers=headers, json={})
    assert response.status_code in (401, 403), response.text


@pytest.mark.parametrize("parameter", ["company_id", "instance_id", "tenant_id", "user_id"])
def test_scope_cannot_be_changed_by_query(reader_case, parameter):
    client, headers, ids, *_ = reader_case
    for path in ("/api/customer-service/tickets", f"/api/customer-service/tickets/{ids[0]}"):
        assert client.get(path, headers=headers, params={parameter: "foreign"}).status_code == 403


@pytest.mark.parametrize(
    "change", ["revoked", "expired", "scope", "instance", "permissions", "missing"]
)
def test_grants_fail_closed_and_revocation_is_immediate(reader_case, change):
    client, headers, _, config, save, path = reader_case
    assert client.get("/api/customer-service/tickets", headers=headers).status_code == 200
    if change == "revoked":
        config["grants"][0]["revoked"] = True
    elif change == "expired":
        config["grants"][0]["expires_at"] = "2000-01-01T00:00:00Z"
    elif change == "scope":
        config["grants"][0]["scopes"] = ["tasks:read"]
    elif change == "instance":
        config["instance_id"] = "other-instance"
    save()
    if change == "permissions":
        path.chmod(0o644)
    if change == "missing":
        path.unlink()
    assert client.get("/api/customer-service/tickets", headers=headers).status_code == 401


@pytest.mark.parametrize("old_intent", [None, "account_support", "general"])
def test_title_correction_is_admin_only_atomic_and_has_no_dispatch(
    reader_case, monkeypatch, old_intent
):
    from modstore_server import customer_service_api
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.test_customer_service_api import _as_user, _make_user

    client, headers, ids, *_ = reader_case
    ticket_id = ids[0]
    url = f"/api/customer-service/tickets/{ticket_id}/title"

    def set_ticket(**values):
        with get_session_factory()() as db:
            db.query(CustomerServiceTicket).filter_by(id=ticket_id).update(values)
            db.commit()

    body = {"title": "  员工图谱无法正常显示  ", "expected_title": "Ticket 0"}
    if old_intent:
        body.update(
            title="Ticket 0",
            intent="product_issue",
            expected_intent=old_intent,
            reason="原描述明确是软件功能故障，纠正误分类",
        )
        set_ticket(intent=old_intent)

    def forbidden(*args, **kwargs):
        raise AssertionError("metadata correction must not enter chat or dispatch")

    monkeypatch.setattr(customer_service_api, "handle_customer_message", forbidden)
    monkeypatch.setattr(customer_service_api, "_schedule_customer_ticket_incident", forbidden)
    assert client.put(url, json=body, headers=headers).status_code == 403
    with _as_user(_make_user("title_customer")):
        assert client.put(url, json=body).status_code == 403
    with _as_user(_make_user("title_admin", admin=True)) as admin:
        detail_url = f"/api/customer-service/tickets/{ticket_id}"
        original = client.get(detail_url).json()["ticket"]
        count = client.get("/api/customer-service/tickets").json()["total"]
        stale_intent = "general" if old_intent == "account_support" else "account_support"
        for changes, status in [
            ({"title": " "}, 422),
            ({"title": "x" * 257}, 422),
            ({"status": "resolved"}, 422),
            ({"expected_title": "stale"}, 409),
            *(
                [
                    ({"reason": "不足"}, 422),
                    ({"expected_intent": None}, 422),
                    ({"intent": None}, 422),
                    ({"intent": "refund"}, 422),
                    ({"expected_intent": stale_intent}, 409),
                ]
                if old_intent
                else [({"reason": "未选择分类"}, 422)]
            ),
        ]:
            assert client.put(url, json={**body, **changes}).status_code == status
        if old_intent:
            for values in (
                {"status": "resolved"},
                {"closed_at": datetime.now(UTC)},
                {"intent": "refund"},
            ):
                set_ticket(**values)
                assert client.put(url, json=body).status_code == 409
                set_ticket(status="processing", closed_at=None, intent=old_intent)
        assert client.put(url.replace(str(ticket_id), "99999999"), json=body).status_code == 404
        response = client.put(url, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["ticket"]["title"] == body["title"].strip()
        assert response.json()["ticket"].get("intent") == ("product_issue" if old_intent else None)
        assert client.put(url, json=body).status_code == 200
        assert client.put(url, json={**body, "title": "another"}).status_code == 409
        detail = client.get(detail_url).json()
        current = detail["ticket"]
        original.pop("updated_at")
        current.pop("updated_at")
        assert current == {
            **original,
            "title": body["title"].strip(),
            **({"intent": "product_issue"} if old_intent else {}),
        }
        assert client.get("/api/customer-service/tickets").json()["total"] == count
        event = "ticket_classification_corrected" if old_intent else "ticket_title_corrected"
        audits = [r for r in detail["audit_logs"] if r["event_type"] == event]
        assert len(audits) == 1
        assert audits[0]["actor_user_id"] == admin.id and audits[0]["actor_type"] == "admin"
        assert audits[0]["detail"]["old_title"] == "Ticket 0"
        if old_intent:
            assert audits[0]["detail"] == {
                "old_title": "Ticket 0",
                "new_title": "Ticket 0",
                "old_intent": old_intent,
                "new_intent": "product_issue",
                "reason": body["reason"],
            }


@pytest.mark.parametrize("disposition", ["resolved", "expired"])
def test_admin_close_requires_evidence_and_is_audited_and_idempotent(reader_case, disposition):
    from datetime import datetime

    from modstore_server.models import User, get_session_factory
    from modstore_server.models_cs import (
        CustomerServiceAction,
        CustomerServiceAuditLog,
        CustomerServiceMessage,
        CustomerServiceSession,
        CustomerServiceTicket,
    )
    from tests.test_customer_service_api import _as_user, _make_user

    client, reader_headers, ids, *_ = reader_case
    ticket_id = ids[0]
    with get_session_factory()() as db:
        row = db.query(CustomerServiceTicket).filter_by(id=ticket_id).one()
        row.evidence_json = '{"prior": "keep"}'
        db.commit()
    url = f"/api/customer-service/tickets/{ticket_id}/close"
    body = {
        "disposition": disposition,
        "request_id": str(uuid.uuid4()),
        "note": "修复已部署并完成原场景验收",
        "verification": "主线 SHA abc123；运行端页面正常显示，原复现步骤通过。",
    }
    eta_url = f"/api/customer-service/tickets/{ticket_id}/expected-completion"
    eta = {"expected_completion_at": "2026-10-21T11:30:00+08:00"}
    assert client.patch(eta_url, json=eta, headers=reader_headers).status_code == 403
    assert client.post(url, json=body, headers=reader_headers).status_code == 403
    with _as_user(_make_user("close_customer")):
        assert client.post(url, json=body).status_code == 403
        assert client.patch(eta_url, json=eta).status_code == 403
    admin = _make_user("close_admin", admin=True)
    with _as_user(admin):
        if disposition == "resolved":
            for protected_id, intent in zip(ids[1:], ("product_issue", "custom_delivery")):
                with get_session_factory()() as db:
                    db.get(CustomerServiceTicket, protected_id).intent = intent
                    db.commit()
                guarded = client.post(
                    f"/api/customer-service/tickets/{protected_id}/close",
                    json={**body, "request_id": str(uuid.uuid4())},
                )
                assert guarded.status_code == 409
                assert (
                    client.get(f"/api/customer-service/tickets/{protected_id}").json()["ticket"][
                        "status"
                    ]
                    == "processing"
                )
        updated = client.patch(eta_url, json=eta)
        assert updated.status_code == 200
        assert updated.json()["ticket"]["expected_completion_at"] == "2026-10-21T03:30:00+00:00"
        assert client.post(url, json={**body, "verification": "不足"}).status_code == 422
        if disposition == "expired":
            assert client.post(url, json=body).status_code == 409
            with get_session_factory()() as db:
                old = datetime(2026, 1, 1)
                db.query(CustomerServiceTicket).filter_by(id=ticket_id).update(
                    {"created_at": old, "updated_at": old}
                )
                db.query(CustomerServiceAuditLog).filter_by(ticket_id=ticket_id).update(
                    {"created_at": old}
                )
                db.query(CustomerServiceAction).filter_by(ticket_id=ticket_id).update(
                    {"created_at": old, "updated_at": old}
                )
                db.commit()
        with get_session_factory()() as db:
            original_session_id = db.get(CustomerServiceTicket, ticket_id).session_id
            session = db.get(CustomerServiceSession, original_session_id)
            original_owner = session.user_id
            session.user_id = db.get(CustomerServiceTicket, ids[1]).user_id
            db.commit()
        denied = client.post(url, json=body)
        assert denied.status_code == 409 and "原客服会话不可核验" in denied.json()["detail"]
        with get_session_factory()() as db:
            assert db.get(CustomerServiceTicket, ticket_id).status == "processing"
            assert db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count() == 0
            db.get(CustomerServiceSession, original_session_id).user_id = original_owner
            db.commit()
        response = client.post(url, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["ticket"]["status"] == disposition
        resolution = response.json()["ticket"]["evidence"]["resolution"]
        assert resolution["repair_verified"] is (disposition == "resolved")
        assert ("resolved_at" in resolution) is (disposition == "resolved")
        assert response.json()["ticket"]["evidence"]["resolution"]["verification_mode"] == (
            "admin_expiry" if disposition == "expired" else "admin_runtime"
        )
        assert client.post(url, json=body).json()["replayed"] is True
        detail = client.get(f"/api/customer-service/tickets/{ticket_id}").json()
        assert detail["ticket"]["expected_completion_at"] == "2026-10-21T03:30:00+00:00"
        assert detail["ticket"]["evidence"]["prior"] == "keep"
        assert (
            sum(a["event_type"] == "expected_completion_updated" for a in detail["audit_logs"]) == 1
        )
        assert [a["action_type"] for a in detail["actions"]].count("ticket.close") == 1
        event = "admin_ticket_expired" if disposition == "expired" else "admin_ticket_closed"
        audits = [a for a in detail["audit_logs"] if a["event_type"] == event]
        assert len(audits) == 1 and audits[0]["actor_user_id"] == admin.id
        assert client.post(url, json={**body, "note": "different close request"}).status_code == 409
        with get_session_factory()() as db:
            messages = db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).all()
            assert len(messages) == 1 and messages[0].user_id == detail["ticket"]["user_id"]
            assert body["note"] in messages[0].content
            assert body["verification"] not in messages[0].content
            owner = db.get(User, detail["ticket"]["user_id"])
        with _as_user(owner):
            visible = client.get(f"/api/customer-service/sessions/{detail['ticket']['session_id']}")
            assert visible.status_code == 200
            assert body["note"] in visible.json()["messages"][-1]["content"]
            assert body["verification"] not in str(visible.json())
        if disposition == "expired":
            from modstore_server.customer_issue_intake import (
                dispatch_issue_event,
                record_dispatch_failure,
            )
            from modstore_server.customer_service_orchestrator import (
                apply_customer_ticket_incident_progress,
            )

            lineage = {"ticket_id": ticket_id, "user_id": detail["ticket"]["user_id"]}
            assert (
                dispatch_issue_event({"id": "late-event", "data": lineage})["reason"]
                == "ticket_expired"
            )
            record_dispatch_failure(lineage, "late failure")
            with get_session_factory()() as db:
                assert apply_customer_ticket_incident_progress(db, ticket_id=ticket_id)["replayed"]
                db.commit()
            after = client.get(f"/api/customer-service/tickets/{ticket_id}").json()
            assert after["ticket"]["status"] == "expired"
            assert after["ticket"]["evidence"] == detail["ticket"]["evidence"]
