"""Delivery startup failures must not persist or return private exception text."""

from __future__ import annotations

import json
import logging
import re
import uuid
from unittest.mock import AsyncMock

import pytest

from tests.test_customer_service_api import (
    _as_user,
    _grant_permanent_purchase,
    _make_ticket,
    _make_user,
)


@pytest.mark.parametrize("entry", ["initial", "revision", "payment", "crm"])
def test_start_failure_remains_private_through_saved_ticket_and_http(
    client, monkeypatch, caplog, entry
):
    from modstore_server import (
        customer_service_delivery_create_api,
        customer_service_delivery_crm_api,
        customer_service_delivery_payment_api,
        incident_bus,
        workbench_api,
    )
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    owner = _make_user("start_owner")
    admin = _make_user("start_admin", admin=True)
    outsider = _make_user("start_outsider")
    _grant_permanent_purchase(owner.id)
    secret = "private-start-provider-token"
    private_path = "/workspace/private/customer-quote.xlsx"
    start = AsyncMock(side_effect=RuntimeError(f"api_key={secret}; input={private_path}"))
    monkeypatch.setattr(workbench_api, "start_workbench_session_for_user", start)
    monkeypatch.setattr(incident_bus, "_dispatch_incident", lambda _event_id: None)
    monkeypatch.setattr(
        customer_service_delivery_create_api, "_schedule_customer_ticket_incident", lambda _: None
    )
    order_no = f"PAID-{uuid.uuid4().hex}"

    def paid_order(user_id, *, expected_out_trade_no):
        assert user_id == owner.id
        assert expected_out_trade_no == order_no
        return {"order_kind": "custom_delivery", "total_amount": "100.00", "trade_no": "T-1"}

    for module in (customer_service_delivery_payment_api, customer_service_delivery_crm_api):
        monkeypatch.setattr(module, "find_matching_paid_order", paid_order)
    request = {
        "kind": "module",
        "title": "报价复核模块",
        "requirements": "读取报价并保留原有客户审批流程。",
        "acceptance_criteria": "真实报价样例可复核。",
        "suggested_id": "private-quote-review",
    }
    if entry != "initial":
        evidence = {
            **request,
            "delivery_terms": {
                "pricing_mode": "initial_included" if entry == "revision" else "post_delivery_addon"
            },
            "crm": {
                "assignment": {"status": "assigned", "owner_name": "Test operator"},
                "quote": {"status": "accepted", "amount": 100, "currency": "CNY"},
                "payment": {"status": "unpaid", "reference": order_no},
            },
        }
        with get_session_factory().begin() as db:
            ticket = _make_ticket(
                db,
                owner,
                ticket_no=f"CS-{uuid.uuid4().hex}",
                title=request["title"],
                intent="custom_delivery",
                status="processing",
                evidence_json=json.dumps(evidence),
            )
            ticket_id = ticket.id

    with caplog.at_level(logging.WARNING):
        if entry in {"initial", "revision"}:
            with _as_user(owner):
                response = client.post("/api/customer-service/custom-deliveries", json=request)
            assert response.status_code == 200, response.text
            if entry == "revision":
                assert response.json()["id"] == ticket_id
            ticket_id = response.json()["id"]
        elif entry == "crm":
            with _as_user(admin):
                response = client.post(
                    f"/api/customer-service/custom-deliveries/{ticket_id}/crm",
                    json={
                        "section": "payment",
                        "status": "paid",
                        "amount": 100,
                        "reference": order_no,
                    },
                )
            assert response.status_code == 200, response.text
        with _as_user(admin):
            detail = client.get(f"/api/customer-service/tickets/{ticket_id}")
    assert detail.status_code == 200, detail.text
    assert start.await_count == 1
    payload = detail.json()
    assert payload["ticket"]["status"] == "processing"
    assert payload["custom_delivery"]["stage"] == "rework"
    assert payload["custom_delivery"]["runs"] == []
    if entry in {"payment", "crm"}:
        assert payload["custom_delivery"]["crm"]["payment"]["status"] == "paid"
    with get_session_factory()() as db:
        stored = db.get(CustomerServiceTicket, ticket_id).evidence_json
    message = json.loads(stored)["start_error"]
    for private_value in (secret, private_path, "Traceback", "RuntimeError:"):
        assert private_value not in detail.text
        assert private_value not in stored
        assert private_value not in caplog.text
    event = re.search(r"诊断编号：([0-9a-f]{32})", message)
    assert event is not None
    diagnostics = [r for r in caplog.records if "custom_delivery_start_failed" in r.getMessage()]
    assert len(diagnostics) == 1
    assert event.group(1) in diagnostics[0].getMessage()
    assert "exception_type=RuntimeError" in diagnostics[0].getMessage()
    assert diagnostics[0].exc_info is None and diagnostics[0].stack_info is None
    with _as_user(owner):
        own = client.get(f"/api/customer-service/tickets/{ticket_id}")
    assert own.status_code == 200 and secret not in own.text
    with _as_user(outsider):
        assert client.get(f"/api/customer-service/tickets/{ticket_id}").status_code == 404
