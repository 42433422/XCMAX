from __future__ import annotations

import hashlib
import json
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
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    token = "cst_ro_" + "test-only-not-a-live-credential" * 2
    ids, owners = [], []
    with get_session_factory()() as db:
        for n in range(3):
            user = User(username=uuid.uuid4().hex, password_hash="x", is_admin=False)
            db.add(user)
            db.flush()
            owners.append(user.id)
            session = CustomerServiceSession(user_id=user.id)
            db.add(session)
            db.flush()
            ticket = CustomerServiceTicket(
                user_id=user.id,
                session_id=session.id,
                ticket_no=uuid.uuid4().hex,
                title=f"Ticket {n}",
                status="processing",
                summary="password=DO_NOT_EXPORT",
                evidence_json='{"token":"DO_NOT_EXPORT"}',
            )
            db.add(ticket)
            db.flush()
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


def test_company_reader_list_detail_pagination_and_redaction(reader_case, caplog):
    client, headers, ids, config, save, _ = reader_case
    caplog.set_level("INFO", logger="modstore_server.customer_ticket_reader")
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
    assert "grant=dot-read" in caplog.text
    assert headers["Authorization"] not in caplog.text
    config["grants"][0]["principal"] = "grok-bot"
    save()
    assert client.get("/api/customer-service/tickets", headers=headers).status_code == 200


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
