import pytest

from modstore_server.para_model_admission import (
    BASE_CAPABILITIES,
    platform_model_admission,
    select_route,
)


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
    "para-a": {
        "provider": "a",
        "resource": "coding",
        "capabilities": sorted(BASE_CAPABILITIES),
        "benchmark_ids": {"livebench_coding": "a-model", "deepswe": "a-config"},
    },
    "para-b": {
        "provider": "b",
        "resource": "coding",
        "capabilities": sorted(BASE_CAPABILITIES),
        "benchmark_ids": {"livebench_coding": "b-model", "deepswe": "b-config"},
    },
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


def test_capability_and_reserve_filter_before_benchmark():
    def must_not_fetch(_source):
        raise AssertionError("blocked or single candidate must not query leaderboard")

    result = select_route(
        [provider("a", 80), provider("b", 98)],
        ROUTES,
        80,
        required=frozenset({"vision"}),
        leaderboard=must_not_fetch,
    )
    assert result["reason"] == "no_capability_match"
    result = select_route(
        [provider("a", 80), provider("b", 98)],
        ROUTES,
        80,
        leaderboard=must_not_fetch,
    )
    assert result["model"] == "para-b"


def test_uses_each_comparable_board_and_records_actual_release():
    quota = [provider("a", 92), provider("b", 92)]
    snapshots = {
        "livebench_coding": ("20261106", {"a-model": 40, "b-model": 90}),
        "deepswe": ("2026-09-22", {"a-config": 12, "b-config": 24}),
    }
    decision = select_route(quota, ROUTES, 80, leaderboard=snapshots.get)
    assert decision["model"] == "para-b"
    assert decision["approved_models"] == ["para-b", "para-a"]
    assert decision["benchmarks"] == [
        {"source": "livebench_coding", "release": "20261106", "score": 90},
        {"source": "deepswe", "release": "2026-09-22", "score": 24},
    ]
    snapshots["deepswe"] = ("2026-09-22", {"a-config": 98, "b-config": 20})
    assert select_route(quota, ROUTES, 80, leaderboard=snapshots.get)["model"] == "para-a"
    snapshots.pop("deepswe")
    snapshots["livebench_coding"] = ("20261106", {"b-model": 90})
    decision = select_route(quota, ROUTES, 80, leaderboard=snapshots.get)
    assert decision["model"] == "para-a"
    assert decision["selection"] == "quota_then_config_order"


def test_exhausted_or_unverified_models_never_enter_fallbacks():
    quota = [provider("a", 79), provider("b", 98)]
    decision = select_route(quota, ROUTES, 80)
    assert decision["approved_models"] == ["para-b"]
    quota[1]["visibility"] = "usage_only"
    assert "approved_models" not in select_route(quota, ROUTES, 80)


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
                "model-a": {
                    "provider": "minimax",
                    "resource": "general",
                    "capabilities": sorted(BASE_CAPABILITIES),
                },
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

    monkeypatch.setenv("MODSTORE_PARA_ARK_PLAN_FIRST", "1")
    decision = platform_model_admission()
    assert decision["model"] == "ark-code-latest"
    assert decision["approved_models"] == ["ark-code-latest", "model-a"]
    assert decision["platform_fallback"]["reserve_percent"] == 80

    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_RESERVE_PERCENT", "99")
    decision = platform_model_admission()
    assert decision["status"] == "admitted"
    assert decision["approved_models"] == ["ark-code-latest"]
    assert decision["platform_fallback"]["status"] == "waiting"
