from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_modstore_post_prefers_internal_key(monkeypatch):
    import app.application.modstore_local_client as client_module

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(client_module, "internal_api_key", lambda: "shared-key")
    monkeypatch.setattr(
        client_module,
        "_async_client",
        lambda *, timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    )

    result = await client_module.modstore_post("/internal", json_body={"value": 1})
    assert result == {"ok": True}
    assert len(seen) == 1
    assert seen[0].headers["x-internal-api-key"] == "shared-key"


@pytest.mark.asyncio
async def test_modstore_post_falls_back_when_internal_key_is_rejected(monkeypatch):
    import app.application.modstore_local_client as client_module

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"access_token": "admin-token"})
        if request.headers.get("x-internal-api-key"):
            return httpx.Response(401, json={"detail": "unauthorized"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(client_module, "internal_api_key", lambda: "stale-key")
    monkeypatch.setattr(
        client_module,
        "_async_client",
        lambda *, timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    )

    result = await client_module.modstore_post("/internal", json_body={})
    assert result == {"ok": True}
    assert [request.url.path for request in seen] == [
        "/internal",
        "/api/auth/login",
        "/api/auth/csrf",
        "/internal",
    ]
    assert seen[-1].headers["authorization"] == "Bearer admin-token"


@pytest.mark.asyncio
async def test_strict_internal_post_never_falls_back_to_admin_login(monkeypatch):
    import app.application.modstore_local_client as client_module

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, json={"detail": "unauthorized"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(client_module, "internal_api_key", lambda: "stale-key")
    monkeypatch.setattr(
        client_module,
        "_async_client",
        lambda *, timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client_module.modstore_post(
            "/internal",
            json_body={},
            strict_internal_auth=True,
        )
    assert [request.url.path for request in seen] == ["/internal"]
    assert seen[0].headers["x-internal-api-key"] == "stale-key"


@pytest.mark.asyncio
async def test_strict_internal_get_requires_key_without_network_or_login(monkeypatch):
    import app.application.modstore_local_client as client_module

    monkeypatch.setattr(client_module, "internal_api_key", lambda: "")
    monkeypatch.setattr(
        client_module,
        "local_modstore_admin_login",
        lambda *_args, **_kwargs: pytest.fail("admin login must not be used"),
    )
    with pytest.raises(RuntimeError, match="internal API key"):
        await client_module.modstore_get("/internal", strict_internal_auth=True)


def test_management_url_and_internal_headers_are_private_only(monkeypatch):
    import app.application.modstore_local_client as client_module

    assert client_module._is_private_service_url("http://127.0.0.1:8788") is True
    assert client_module._is_private_service_url("http://192.168.10.2:8788") is True
    assert client_module._is_private_service_url("https://xiu-ci.com") is False
    monkeypatch.setenv("MODSTORE_MANAGEMENT_WORK_BASE_URL", "https://xiu-ci.com")
    with pytest.raises(RuntimeError, match="private IP"):
        client_module.modstore_management_base_url()


def test_internal_key_uses_only_management_key_names(monkeypatch):
    import app.application.modstore_local_client as client_module
    import app.security.local_runtime_secret as secret_module

    seen = []

    def fake_secret(*keys):
        seen.extend(keys)
        return "shared-key"

    monkeypatch.setattr(secret_module, "local_runtime_secret", fake_secret)
    assert client_module.internal_api_key() == "shared-key"
    assert seen == ["MODSTORE_INTERNAL_API_KEY", "XCAGI_MARKET_INTERNAL_API_KEY"]
