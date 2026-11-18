"""Developer webhooks must keep account data and outbound network access isolated."""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server import models
from modstore_server import openapi_connector_runtime as outbound
from modstore_server import webhook_dispatcher as dispatcher
from modstore_server import webhook_subscription_api as api


def _dns_answer(address, port=443):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]


@pytest.fixture
def portal(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(
        engine,
        tables=[
            models.User.__table__,
            models.WebhookSubscription.__table__,
            models.WebhookDelivery.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    alice = models.User(id=101, username="alice", password_hash="fixture", is_admin=False)
    bob = models.User(id=202, username="bob", password_hash="fixture", is_admin=False)
    db.add_all([alice, bob])
    db.commit()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[api._get_current_user] = lambda: alice
    client = TestClient(app)
    state = SimpleNamespace(
        db=db, client=client, alice=alice, bob=bob, requests=[], options=[], response_status=200
    )
    original_client = httpx.Client

    def respond(request):
        state.requests.append(request)
        return httpx.Response(
            state.response_status,
            text="fixture response",
            headers={"Location": "http://127.0.0.1/private"},
        )

    def outbound_client(**kwargs):
        state.options.append(kwargs)
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(dispatcher.httpx, "Client", outbound_client)
    monkeypatch.setattr(models, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        outbound.socket, "getaddrinfo", lambda host, port, **kw: _dns_answer("93.184.216.34", port)
    )
    monkeypatch.setenv("MODSTORE_WEBHOOK_RETRIES", "0")
    try:
        yield state
    finally:
        client.close()
        db.close()
        engine.dispose()


def _subscription(portal, owner, **kwargs):
    row = models.WebhookSubscription(
        user_id=owner.id, name="fixture", target_url="https://hooks.example/hook", **kwargs
    )
    portal.db.add(row)
    portal.db.commit()
    return row


def test_fanout_preserves_owner_wildcard_and_event_filters(portal):
    _subscription(portal, portal.alice, enabled_events_json='["*"]')
    owner = _subscription(portal, portal.bob, enabled_events_json='["*"]')
    _subscription(portal, portal.bob, enabled_events_json='["refund.rejected"]', is_active=False)
    _subscription(portal, portal.bob, enabled_events_json='["payment.paid"]')
    event = dispatcher.build_event("refund.rejected", "fixture-order", {"user_id": "202"})

    assert dispatcher.dispatch_event_to_subscriptions(event) == 1
    deliveries = portal.db.query(models.WebhookDelivery).all()
    assert [(row.subscription_id, row.user_id) for row in deliveries] == [(owner.id, 202)]
    assert len(portal.requests) == 1
    assert json.loads(portal.requests[0].content) == event


@pytest.mark.parametrize(
    "data",
    [
        {},
        None,
        [],
        {"user_id": None},
        {"user_id": True},
        {"user_id": 0},
        {"user_id": -1},
        {"user_id": 202.5},
        {"user_id": "invalid"},
        {"user_id": 2**100},
    ],
)
def test_fanout_fails_closed_without_valid_owner(portal, data):
    _subscription(portal, portal.alice)
    event = dispatcher.build_event("refund.rejected", "fixture-order", {})
    event["data"] = data
    assert dispatcher.dispatch_event_to_subscriptions(event) == 0
    assert portal.requests == []
    assert portal.db.query(models.WebhookDelivery).count() == 0


@pytest.mark.parametrize("owner", [202, None])
def test_legacy_delivery_cannot_be_retried_by_wrong_owner(portal, owner):
    sub = _subscription(portal, portal.alice)
    event = dispatcher.build_event("refund.rejected", "fixture-order", {"user_id": owner})
    old = models.WebhookDelivery(
        subscription_id=sub.id,
        user_id=101,
        event_id=event["id"],
        event_type=event["type"],
        request_body=json.dumps(event),
        status="failed",
    )
    portal.db.add(old)
    portal.db.commit()
    response = portal.client.post(f"/api/developer/webhooks/deliveries/{old.id}/retry")
    assert response.status_code == 403
    assert portal.requests == []
    assert portal.db.query(models.WebhookDelivery).count() == 1
    with pytest.raises(ValueError, match="owner"):
        dispatcher._deliver_event_to_subscription(portal.db, sub, event)


def test_legacy_delivery_list_only_exposes_verified_owner(portal):
    sub = _subscription(portal, portal.alice)
    payloads = [
        json.dumps(dispatcher.build_event("refund.rejected", "other", {"user_id": 202})),
        json.dumps(dispatcher.build_event("refund.rejected", "unknown", {})),
        "truncated JSON",
        json.dumps(dispatcher.build_event("refund.rejected", "own", {"user_id": 101})),
    ]
    for index, body in enumerate(payloads):
        portal.db.add(
            models.WebhookDelivery(
                subscription_id=sub.id,
                user_id=101,
                event_id=f"fixture:{index}",
                event_type="refund.rejected",
                request_body=body,
                response_body=f"private response {index}",
            )
        )
    portal.db.commit()
    response = portal.client.get(f"/api/developer/webhooks/{sub.id}/deliveries")
    assert response.status_code == 200
    assert [row["event_id"] for row in response.json()] == ["fixture:3"]
    assert response.json()[0]["response_body"] == "private response 3"
    assert portal.db.query(models.WebhookDelivery).count() == 4


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://[::1]/private",
        "http://10.0.0.1/private",
        "http://100.64.0.1/private",
        "http://169.254.169.254/private",
        "http://localhost/private",
        "https://user:password@hooks.example/hook",
    ],
)
def test_create_and_update_reject_unsafe_targets(portal, url):
    response = portal.client.post(
        "/api/developer/webhooks", json={"name": "fixture", "target_url": url}
    )
    assert response.status_code == 400
    assert portal.db.query(models.WebhookSubscription).count() == 0
    sub = _subscription(portal, portal.alice)
    response = portal.client.put(f"/api/developer/webhooks/{sub.id}", json={"target_url": url})
    assert response.status_code == 400
    portal.db.refresh(sub)
    assert sub.target_url == "https://hooks.example/hook"
    assert portal.requests == []


def test_existing_private_target_is_blocked_at_delivery(portal):
    sub = _subscription(portal, portal.alice)
    sub.target_url = "http://127.0.0.1/private"
    portal.db.commit()
    result = portal.client.post(f"/api/developer/webhooks/{sub.id}/test")
    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert portal.requests == []


def test_public_target_preserves_host_sni_and_hmac(portal, monkeypatch):
    monkeypatch.setattr(api, "fernet_configured", lambda: True)
    monkeypatch.setattr(api, "encrypt_secret", lambda secret: "encrypted")
    monkeypatch.setattr(
        "modstore_server.llm_crypto.decrypt_secret", lambda secret: "fixture-secret"
    )
    created = portal.client.post(
        "/api/developer/webhooks",
        json={
            "name": "fixture",
            "target_url": "https://hooks.example:8443/hook",
            "secret": "fixture-secret",
        },
    )
    assert created.status_code == 200
    result = portal.client.post(f"/api/developer/webhooks/{created.json()['id']}/test")
    assert result.status_code == 200
    assert result.json()["status"] == "success"
    request = portal.requests[0]
    assert str(request.url) == "https://93.184.216.34:8443/hook"
    assert request.headers["host"] == "hooks.example:8443"
    assert request.extensions["sni_hostname"] == "hooks.example"
    assert portal.options[0]["trust_env"] is False
    assert portal.options[0]["follow_redirects"] is False
    expected = dispatcher._signature(
        "fixture-secret",
        request.headers["X-Modstore-Webhook-Timestamp"],
        request.headers["X-Modstore-Webhook-Id"],
        request.content,
    )
    assert request.headers["X-Modstore-Webhook-Signature"] == f"sha256={expected}"


def test_dns_rebinding_after_creation_is_blocked(portal, monkeypatch):
    created = portal.client.post(
        "/api/developer/webhooks",
        json={"name": "fixture", "target_url": "https://hooks.example/hook"},
    )
    assert created.status_code == 200
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **kw: _dns_answer("127.0.0.1"))
    result = portal.client.post(f"/api/developer/webhooks/{created.json()['id']}/test")
    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert portal.requests == []


def test_delivery_retry_revalidates_dns(portal, monkeypatch):
    sub = _subscription(portal, portal.alice)
    addresses = iter(["93.184.216.34", "127.0.0.1"])
    monkeypatch.setattr(
        outbound.socket, "getaddrinfo", lambda *a, **kw: _dns_answer(next(addresses))
    )
    monkeypatch.setenv("MODSTORE_WEBHOOK_RETRIES", "1")
    monkeypatch.setattr(dispatcher.time, "sleep", lambda duration: None)
    portal.response_status = 503
    result = portal.client.post(f"/api/developer/webhooks/{sub.id}/test")
    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert result.json()["attempts"] == 2
    assert len(portal.requests) == 1


def test_redirect_to_private_network_is_not_followed(portal):
    sub = _subscription(portal, portal.alice)
    portal.response_status = 302
    result = portal.client.post(f"/api/developer/webhooks/{sub.id}/test")
    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert len(portal.requests) == 1
    assert portal.requests[0].url.host == "93.184.216.34"
