"""Software-only purchases use the original quoted customization checkout."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from modstore_server.account_license_plans import (
    LEGACY_ACCOUNT_LICENSE_PLANS,
    STANDARD_PLAN_ID,
)
from tests.test_customer_service_api import (
    _as_user,
    _grant_permanent_purchase,
    _make_user,
)

REQUEST = {
    "kind": "module",
    "title": "独立定制报价复核",
    "requirements": "读取客户报价并按已确认的需求生成独立复核结果。",
    "acceptance_criteria": "输出符合已确认的报价范围和客户验收标准。",
}
ENDPOINT = "/api/customer-service/custom-deliveries"


@pytest.fixture
def customization(client, monkeypatch):
    from modstore_server import (
        customer_service_delivery_create_api,
        incident_bus,
        workbench_api,
    )

    owner = _make_user("software_only_delivery")
    start = AsyncMock(
        side_effect=lambda *_, **kwargs: {
            "session_id": kwargs.get("session_id") or "customization-test",
            "status": "running",
        }
    )
    monkeypatch.setattr(workbench_api, "start_workbench_session_for_user", start)
    monkeypatch.setattr(
        workbench_api,
        "get_workbench_session_snapshot",
        AsyncMock(
            side_effect=lambda session_id, *_: {
                "id": session_id,
                "user_id": owner.id,
                "status": "running",
                "steps": [],
            }
        ),
    )
    monkeypatch.setattr(incident_bus, "_dispatch_incident", lambda _: None)
    monkeypatch.setattr(
        customer_service_delivery_create_api, "_schedule_customer_ticket_incident", lambda _: None
    )
    return owner, start


def test_standard_first_customization_requires_quoted_payment(client, customization, monkeypatch):
    from modstore_server import payment_cs_internal
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceAuditLog

    owner, start = customization
    _grant_permanent_purchase(owner.id, STANDARD_PLAN_ID)
    with _as_user(owner):
        response = client.post(ENDPOINT, json=REQUEST)
        assert response.status_code == 200, response.text
        delivery = response.json()["custom_delivery"]
        assert delivery["stage"] == "commerce"
        assert delivery["pricing_mode"] == "post_delivery_addon"
        assert not delivery["included_in_purchase"] and not delivery["commerce_ready"]
        assert delivery["crm"]["quote"]["status"] == "draft"
        assert delivery["crm"]["payment"]["status"] == "unpaid"
        ticket_id = response.json()["id"]
        ticket_no = response.json()["ticket_no"]
        assert client.post(f"{ENDPOINT}/{ticket_id}/payment-checkout", json={}).status_code == 409
    start.assert_not_awaited()

    admin = _make_user("customization_quote_admin", admin=True)
    with _as_user(admin):
        quoted = client.post(
            f"{ENDPOINT}/{ticket_id}/crm",
            json={"section": "quote", "status": "accepted", "number": "QUOTE-1", "amount": 4180},
        )
        assert quoted.status_code == 200, quoted.text
        assert quoted.json()["custom_delivery"]["stage"] == "commerce"
    start.assert_not_awaited()

    # Replace payment HTTP and employee I/O, retaining the existing quote,
    # checkout, order readback, ticket transactions and producer dispatch.
    order = {
        "out_trade_no": "CUSTOM-ORDER",
        "user_id": owner.id,
        "status": "pending",
        "total_amount": "4180.00",
        "order_kind": "custom_delivery",
        "trade_no": "TRADE-1",
    }

    def payment_transport(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            assert request.url.path == "/api/internal/payment/custom-delivery-checkout"
            assert payload["user_id"] == owner.id and payload["ticket_no"] == ticket_no
            assert payload["total_amount"] == "4180.00"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "order_id": "CUSTOM-ORDER",
                    "type": "precreate",
                    "checkout_path": "/checkout/CUSTOM-ORDER",
                },
            )
        assert request.url.path == "/api/internal/payment/user-orders"
        assert request.url.params["user_id"] == str(owner.id)
        return httpx.Response(200, json={"ok": True, "orders": [order], "total": 1})

    transport = httpx.MockTransport(payment_transport)
    sync_client, async_client = httpx.Client, httpx.AsyncClient
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "isolated-customization-contract")
    monkeypatch.setattr(
        payment_cs_internal.httpx, "Client", lambda **kw: sync_client(transport=transport, **kw)
    )
    monkeypatch.setattr(
        payment_cs_internal.httpx,
        "AsyncClient",
        lambda **kw: async_client(transport=transport, **kw),
    )
    with _as_user(owner):
        checkout = client.post(f"{ENDPOINT}/{ticket_id}/payment-checkout", json={})
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["order_id"] == "CUSTOM-ORDER"

        def read_delivery():
            listed = client.get(ENDPOINT)
            assert listed.status_code == 200, listed.text
            return next(
                row["custom_delivery"] for row in listed.json()["items"] if row["id"] == ticket_id
            )

        assert read_delivery()["stage"] == "commerce"
        start.assert_not_awaited()
        order["status"] = "paid"
        paid = read_delivery()
        assert paid["commerce_ready"]
        assert paid["stage"] == "production"
        assert read_delivery()["runs"] == paid["runs"]
    start.assert_awaited_once()
    with _as_user(owner):
        reworked = client.post(
            f"{ENDPOINT}/{ticket_id}/decision",
            json={"action": "rework", "note": "补充已付款范围的复核"},
        )
    assert reworked.status_code == 200, reworked.text
    assert reworked.json()["custom_delivery"]["runs"][-1]["attempt"] == 2
    assert start.await_count == 2
    with get_session_factory()() as db:
        assert (
            db.query(CustomerServiceAuditLog)
            .filter_by(ticket_id=ticket_id, event_type="custom_delivery_payment_verified")
            .count()
            == 1
        )


@pytest.mark.parametrize("plan_id", [row["id"] for row in LEGACY_ACCOUNT_LICENSE_PLANS])
@pytest.mark.parametrize("newest_standard", [False, True])
def test_historical_included_delivery_survives_purchase_order(
    client, customization, plan_id, newest_standard
):
    owner, start = customization
    if not newest_standard:
        _grant_permanent_purchase(owner.id, STANDARD_PLAN_ID)
    original_order = _grant_permanent_purchase(owner.id, plan_id)
    if newest_standard:
        _grant_permanent_purchase(owner.id, STANDARD_PLAN_ID)
    with _as_user(owner):
        response = client.post(ENDPOINT, json=REQUEST)
    assert response.status_code == 200, response.text
    delivery = response.json()["custom_delivery"]
    assert delivery["delivery_terms"]["plan_id"] == plan_id
    assert delivery["delivery_terms"]["source_order_id"] == original_order
    assert delivery["pricing_mode"] == "initial_included" and delivery["commerce_ready"]
    start.assert_awaited_once()
    with _as_user(owner):
        reworked = client.post(
            f"{ENDPOINT}/{response.json()['id']}/decision",
            json={"action": "rework", "note": "补充历史已购范围的复核"},
        )
    assert reworked.status_code == 200, reworked.text
    revised = reworked.json()["custom_delivery"]
    assert revised["delivery_terms"]["source_order_id"] == original_order
    assert revised["runs"][-1]["attempt"] == 2 and start.await_count == 2


@pytest.mark.parametrize("quoted", [False, True])
@pytest.mark.parametrize("source_mode", [None, "versioned_main"])
def test_unpaid_rework_preserves_ticket_and_audit(client, customization, quoted, source_mode):
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceAuditLog, CustomerServiceTicket

    owner, start = customization
    _grant_permanent_purchase(owner.id, STANDARD_PLAN_ID)
    with _as_user(owner):
        created = client.post(ENDPOINT, json=REQUEST)
    assert created.status_code == 200, created.text
    ticket_id = created.json()["id"]
    if quoted:
        with _as_user(_make_user("rework_quote_admin", admin=True)):
            quote = client.post(
                f"{ENDPOINT}/{ticket_id}/crm",
                json={
                    "section": "quote",
                    "status": "accepted",
                    "number": "QUOTE-1",
                    "amount": 4180,
                },
            )
        assert quote.status_code == 200, quote.text

    def stored_state():
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            return (
                ticket.evidence_json,
                ticket.status,
                ticket.decision_status,
                ticket.closed_at,
                ticket.updated_at,
                db.query(CustomerServiceAuditLog).filter_by(ticket_id=ticket_id).count(),
            )

    before = stored_state()
    with _as_user(owner):
        rejected = client.post(
            f"{ENDPOINT}/{ticket_id}/decision",
            json={"action": "rework", "note": "请求立即开始生产", "source_mode": source_mode},
        )
    assert rejected.status_code == 409, rejected.text
    assert "商务交付条件未完成" in rejected.json()["detail"]
    assert stored_state() == before
    start.assert_not_awaited()


@pytest.mark.parametrize("source_mode", ["generated", "versioned_main"])
def test_common_delivery_start_rejects_unpaid_production(customization, monkeypatch, source_mode):
    from modstore_server import customer_delivery_versioned
    from modstore_server.customer_delivery_workbench_start import _start_custom_delivery_run

    owner, start = customization
    versioned_start = AsyncMock(return_value={"session_id": "unpaid-versioned"})
    monkeypatch.setattr(customer_delivery_versioned, "start_versioned_main_run", versioned_start)
    evidence = {
        **REQUEST,
        "source_mode": source_mode,
        "delivery_terms": {"pricing_mode": "post_delivery_addon"},
        "crm": {
            "assignment": {"status": "assigned"},
            "quote": {"status": "accepted", "amount": 4180},
            "payment": {"status": "unpaid"},
        },
    }
    before = json.dumps(evidence, sort_keys=True)
    with pytest.raises(ValueError, match="商务交付条件未完成"):
        asyncio.run(_start_custom_delivery_run(user_id=owner.id, evidence=evidence, attempt=1))
    assert json.dumps(evidence, sort_keys=True) == before
    start.assert_not_awaited()
    versioned_start.assert_not_awaited()
