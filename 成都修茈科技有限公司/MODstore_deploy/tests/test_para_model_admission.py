import pytest

from modstore_server.para_model_admission import platform_model_admission, select_route


def provider(name, remaining, *, visibility="exact", model_remaining=100):
    return {
        "provider": name,
        "visibility": visibility,
        "state": "healthy",
        "resources": [
            {"resource": "general", "remaining_percent": remaining},
            {"resource": "coding", "remaining_percent": model_remaining},
        ],
    }


ROUTES = {
    "para-a": {"provider": "a", "resource": "coding"},
    "para-b": {"provider": "b", "resource": "coding"},
}


def test_uses_both_model_and_provider_limits_when_allocating():
    result = select_route([provider("a", 100, model_remaining=84), provider("b", 92)], ROUTES, 80)
    assert result["model"] == "para-b"
    assert result["headroom_percent"] == 12


def test_waits_if_no_route_is_above_reserve_with_verified_quota():
    result = select_route(
        [provider("a", 80), provider("b", 100, visibility="usage_only")], ROUTES, 80
    )
    assert result["status"] == "waiting"


def test_invalid_active_policy_leaves_task_waiting(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_ROUTES", "{}")
    assert platform_model_admission()["reason"] == "invalid_platform_policy"


def test_sync_admission_uses_isolated_http_on_each_loop(monkeypatch):
    import asyncio
    import json

    import httpx

    from modstore_server import llm_key_resolver, llm_quota_monitor
    from modstore_server.infrastructure import http_clients

    loops = []
    closed = []
    original_client = httpx.AsyncClient

    def client_factory():
        async def respond(request):
            loops.append(asyncio.get_running_loop())
            return httpx.Response(
                200,
                json={
                    "model_remains": [
                        {
                            "model_name": "general",
                            "current_interval_usage_count": 2,
                            "current_interval_total_count": 100,
                        }
                    ]
                },
            )

        client = original_client(transport=httpx.MockTransport(respond))
        closed.append(client)
        return client

    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    monkeypatch.setenv(
        "MODSTORE_PARA_PLATFORM_ROUTES",
        json.dumps(
            {
                "model-a": {"provider": "minimax", "resource": "general"},
            }
        ),
    )
    monkeypatch.setattr(
        llm_key_resolver, "platform_api_key", lambda provider: "minimaxsk-cp-example"
    )
    monkeypatch.setattr(
        llm_quota_monitor, "platform_api_key", lambda provider: "minimaxsk-cp-example"
    )
    monkeypatch.setattr(
        llm_quota_monitor, "platform_base_url", lambda provider: "https://api.minimax.io"
    )
    monkeypatch.setattr(llm_quota_monitor, "_local_usage_by_provider", lambda hours: {})
    monkeypatch.setattr(
        http_clients, "get_external_client", lambda: pytest.fail("shared loop client used")
    )
    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    assert platform_model_admission()["status"] == "admitted"
    assert platform_model_admission()["status"] == "admitted"
    assert len(loops) == 2 and loops[0] is not loops[1]
    assert all(client.is_closed for client in closed)
