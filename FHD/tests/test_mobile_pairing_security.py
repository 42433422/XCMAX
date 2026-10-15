"""Security boundaries for local desktop pairing and cloud relay enrollment."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import mobile_api  # noqa: F401
from app.fastapi_routes import mobile_api_extensions as routes


def _request(peer: str = "127.0.0.1", host: str = "127.0.0.1"):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        url=SimpleNamespace(hostname=host),
        headers={"host": f"{host}:17500"},
        scope={"client": (peer, 50000)},
    )


def _user():
    return SimpleNamespace(id=71, username="ordinary", role="enterprise", is_active=True)


@pytest.mark.asyncio
async def test_pairing_issue_requires_local_desktop_and_confirmed_cloud(monkeypatch):
    body = routes.PairingIssueBody()
    with patch.object(routes, "issue_pairing_nonce") as issue:
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
        assert (await routes.mobile_pairing_issue(body, _request())).status_code == 401
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        assert (
            await routes.mobile_pairing_issue(body, _request(peer="192.168.1.8"))
        ).status_code == 401
        assert (
            await routes.mobile_pairing_issue(body, _request(host="external.example"))
        ).status_code == 401
        issue.assert_not_called()
        with patch.object(routes, "_register_desktop_relay_for_pairing", return_value=None):
            assert (await routes.mobile_pairing_issue(body, _request())).status_code == 503
        with patch.object(
            routes,
            "_register_desktop_relay_for_pairing",
            return_value={"relay_id": "r", "pairing_code": "invalid"},
        ):
            assert (await routes.mobile_pairing_issue(body, _request())).status_code == 503
        issue.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_and_exchange_reject_anonymous_before_disclosing_or_consuming():
    with (
        patch.object(routes, "lookup_by_shortcode") as lookup,
        patch.object(routes, "consume_by_shortcode") as consume,
    ):
        assert (
            await routes.mobile_pairing_lookup(routes.PairingLookupBody(code="123456"), user=None)
        ).status_code == 401
        assert (
            await routes.mobile_pairing_exchange(
                routes.PairingExchangeBody(code="123456"), user=None
            )
        ).status_code == 401
        lookup.assert_not_called()
        consume.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_and_exchange_reject_rate_limit_before_using_code():
    with (
        patch.object(routes, "_pairing_rate_allowed", return_value=False),
        patch.object(routes, "lookup_by_shortcode") as lookup,
        patch.object(routes, "consume_by_shortcode") as consume,
    ):
        assert (
            await routes.mobile_pairing_lookup(
                routes.PairingLookupBody(code="123456"), user=_user()
            )
        ).status_code == 429
        assert (
            await routes.mobile_pairing_exchange(
                routes.PairingExchangeBody(code="123456"), user=_user()
            )
        ).status_code == 429
        lookup.assert_not_called()
        consume.assert_not_called()


@pytest.mark.asyncio
async def test_cloud_register_and_renew_are_rate_limited():
    body = routes.RelayDesktopRegisterBody(device_id="device-1")
    renew = routes.RelayDesktopRenewBody(
        relay_id="relay-12345678", desktop_token="desktop-token-12345678"
    )
    with (
        patch.object(routes, "_pairing_rate_allowed", return_value=False),
        patch.object(routes, "MobileRelayService") as service,
    ):
        assert (await routes.mobile_relay_desktop_register(body, _request())).status_code == 429
        assert (await routes.mobile_relay_desktop_renew(renew, _request())).status_code == 429
        service.assert_not_called()


@pytest.mark.asyncio
async def test_cloud_bind_requires_active_principal_and_code_even_with_relay_id():
    body = routes.RelayMobileBindAccountBody(relay_id="relay-12345678")
    with patch.object(routes, "MobileRelayService") as service:
        assert (await routes.mobile_relay_bind_account(body, user=None)).status_code == 401
        inactive = _user()
        inactive.is_active = False
        assert (await routes.mobile_relay_bind_account(body, user=inactive)).status_code == 401
        assert (await routes.mobile_relay_bind_account(body, user=_user())).status_code == 400
        service.assert_not_called()


def test_pairing_rate_limit_fails_closed_without_required_redis(monkeypatch):
    from app.utils.resilience import rate_limiter

    monkeypatch.setattr(rate_limiter, "distributed_rate_limit_required", lambda: True)
    monkeypatch.setattr(rate_limiter, "_get_redis_client", lambda: None)
    assert not routes._pairing_rate_allowed("71", "mobile-pairing-lookup", 5, 3600)


def test_http_anonymous_exchange_does_not_consume_code():
    app = FastAPI()
    app.include_router(routes.extension_router, prefix="/api/mobile/v1")
    with patch.object(routes, "consume_by_shortcode") as consume:
        response = TestClient(app).post("/api/mobile/v1/pairing/exchange", json={"code": "123456"})
    assert response.status_code == 401
    consume.assert_not_called()


@pytest.mark.parametrize("renew_status,registers", [(405, True), (404, False)])
def test_renewal_falls_back_to_register_only_when_cloud_lacks_endpoint(
    monkeypatch, renew_status, registers
):
    import httpx

    from app.services import mobile_relay_desktop_client as client_mod
    from app.services import mobile_relay_desktop_client_part01_part01 as impl

    calls: list[str] = []
    fresh = {"relay_id": "r2", "desktop_token": "t2", "pairing_code": "123456"}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/renew"):
            return httpx.Response(renew_status, json={})
        return httpx.Response(200, json={"data": fresh})

    cfg = {"relay_id": "r1", "desktop_token": "t1", "relay_base_url": "https://relay.test/"}
    monkeypatch.setattr(client_mod, "_read_config", lambda: dict(cfg))
    monkeypatch.setattr(client_mod, "_write_config", lambda data: cfg.update(data))
    monkeypatch.setattr(client_mod, "start_desktop_relay_poller", lambda: True)
    monkeypatch.setattr(client_mod, "_relay_base_url", lambda: "https://relay.test/")
    monkeypatch.setattr(
        client_mod,
        "_relay_http_client",
        lambda timeout: httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout),
    )
    result = impl.register_desktop_relay(host="192.168.1.5", port=17500)
    assert (result is not None and result["relay_id"] == "r2") is registers
    assert any(p.endswith("/register") for p in calls) is registers
