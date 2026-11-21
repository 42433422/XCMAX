from __future__ import annotations

import json

import pytest

from modstore_server import llm_quota_monitor
from modstore_server.infrastructure import http_clients


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def _payload(percent: int) -> dict:
    return {
        "model_remains": [
            {
                "model_name": "general",
                "current_interval_remaining_percent": percent,
                "current_weekly_remaining_percent": 90,
                "current_interval_usage_count": 10,
                "current_interval_total_count": 100,
                "end_time": 123,
            }
        ],
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


def test_parse_minimax_exact_quota_and_threshold(monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_QUOTA_WARNING_PERCENT", "15")

    healthy = llm_quota_monitor.parse_minimax_token_plan_remains(_payload(80))
    warning = llm_quota_monitor.parse_minimax_token_plan_remains(_payload(10))
    exhausted = llm_quota_monitor.parse_minimax_token_plan_remains(_payload(0))

    assert healthy["state"] == "healthy"
    assert healthy["remaining_percent"] == 80
    assert healthy["visibility"] == "exact"
    assert warning["state"] == "warning"
    assert exhausted["state"] == "exhausted"


def test_parse_minimax_error_response():
    result = llm_quota_monitor.parse_minimax_token_plan_remains(
        {
            "base_resp": {
                "status_code": 1004,
                "status_msg": "permission denied",
            }
        }
    )

    assert result == {
        "state": "error",
        "visibility": "exact",
        "error_code": 1004,
        "error": "permission denied",
        "resources": [],
        "remaining_percent": None,
    }


def test_parse_minimax_empty_response_is_explicitly_unknown():
    result = llm_quota_monitor.parse_minimax_token_plan_remains({})

    assert result["state"] == "unknown"
    assert result["visibility"] == "exact"
    assert result["remaining_percent"] is None
    assert result["resources"] == []
    assert result["error"] == "empty quota response"


def test_parse_minimax_derives_remaining_percent_from_count_variants():
    result = llm_quota_monitor.parse_minimax_token_plan_remains(
        {
            "base_resp": {"status_code": 0},
            "data": {
                "model_remains": [
                    {
                        "model_name": "general",
                        "current_interval_usage_count": "25",
                        "current_interval_total_count": "100",
                        "current_weekly_usage_count": 50,
                        "current_weekly_total_count": 100,
                    }
                ]
            },
        }
    )

    assert result["state"] == "healthy"
    assert result["remaining_percent"] == 50
    assert result["resources"][0]["interval_usage"] == 25


def test_parse_minimax_explicit_exhausted_status_wins_over_counts():
    result = llm_quota_monitor.parse_minimax_token_plan_remains(
        {
            "model_remains": [
                {
                    "model_name": "general",
                    "current_interval_status": "exhausted",
                    "current_interval_usage_count": 1,
                    "current_interval_total_count": 100,
                }
            ]
        }
    )

    assert result["state"] == "exhausted"
    assert result["remaining_percent"] == 0


@pytest.mark.asyncio
async def test_fetch_minimax_quota_uses_china_endpoint_and_normalized_key(monkeypatch):
    client = _Client(_payload(99))
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)

    result = await llm_quota_monitor.fetch_minimax_token_plan_quota(
        "minimaxsk-cp-example",
        base_url="https://api.minimaxi.com",
    )

    assert result["state"] == "healthy"
    url, kwargs = client.calls[0]
    assert url == "https://www.minimaxi.com/v1/token_plan/remains"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-cp-example"


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.minimaxi.com", "https://www.minimaxi.com/v1/token_plan/remains"),
        ("api.minimaxi.com/v1", "https://www.minimaxi.com/v1/token_plan/remains"),
        (
            "https://minimaxi.com.evil.example",
            "https://www.minimax.io/v1/token_plan/remains",
        ),
        ("https://evilminimaxi.com", "https://www.minimax.io/v1/token_plan/remains"),
    ],
)
def test_minimax_quota_endpoint_requires_an_exact_trusted_hostname(base_url, expected):
    assert llm_quota_monitor._minimax_remains_url(base_url) == expected


@pytest.mark.asyncio
async def test_fetch_minimax_quota_redacts_secret_from_errors(monkeypatch):
    fake_secret = "unit-test-secret-that-must-not-leak"

    class ExplodingClient:
        async def get(self, _url, **_kwargs):
            raise RuntimeError(f"upstream rejected Bearer {fake_secret}")

    monkeypatch.setattr(http_clients, "get_external_client", ExplodingClient)

    result = await llm_quota_monitor.fetch_minimax_token_plan_quota(
        fake_secret,
        base_url="https://api.minimaxi.com",
    )
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["state"] == "error"
    assert fake_secret not in serialized
    assert "error" in result


@pytest.mark.parametrize(
    ("result", "state"),
    [
        ({"ok": True}, "healthy"),
        ({"ok": False, "status": 429, "error": "quota exhausted"}, "exhausted"),
        ({"ok": False, "status": 429, "error": "rate limit"}, "warning"),
        ({"ok": False, "status": 500, "error": "upstream"}, "error"),
    ],
)
def test_probe_classification(result, state):
    assert llm_quota_monitor.classify_probe_result(result) == state


def test_xiaomi_token_plan_validates_period_and_exact_credits():
    from datetime import UTC, datetime

    from modstore_server.llm_quota_monitor import parse_xiaomi_token_plan_quota

    payload = {
        "object": "token_plan",
        "period": {"start_at": "2026-11-04 00:00:00", "end_at": "2026-12-04 00:00:00"},
        "quota": {"total_credits": 1000, "used_credits": 181, "remaining_credits": 819},
    }
    result = parse_xiaomi_token_plan_quota(payload, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert result["resources"][0]["resource"] == "general"
    assert result["remaining_percent"] == 81
    with pytest.raises(ValueError, match="period"):
        parse_xiaomi_token_plan_quota(payload, now=datetime(2026, 12, 4, tzinfo=UTC))
    payload["quota"]["remaining_credits"] = 999
    with pytest.raises(ValueError, match="inconsistent"):
        parse_xiaomi_token_plan_quota(payload, now=datetime(2026, 11, 20, tzinfo=UTC))
    payload["quota"] = {"total_credits": True, "used_credits": 0, "remaining_credits": 1}
    with pytest.raises(ValueError, match="inconsistent"):
        parse_xiaomi_token_plan_quota(payload, now=datetime(2026, 11, 20, tzinfo=UTC))


@pytest.mark.asyncio
async def test_xiaomi_quota_does_not_send_key_to_custom_platform_url(monkeypatch):
    from modstore_server import llm_quota_monitor as monitor

    monkeypatch.setattr(
        monitor,
        "llm_http_response",
        lambda *_args, **_kwargs: pytest.fail("unsupported quota host"),
    )
    result = await monitor.fetch_xiaomi_token_plan_quota(
        "tp-fixture", base_url="https://token-plan-cn.xiaomimimo.com.evil.example/v1"
    )
    assert result["visibility"] == "usage_only"
    assert result["remaining_percent"] is None


@pytest.mark.asyncio
async def test_environment_xiaomi_quota_uses_get_without_request_body(monkeypatch):
    import httpx

    from modstore_server import platform_model_transport
    from modstore_server.platform_model_config import PlatformApiKey

    captured = []
    real_client = httpx.AsyncClient

    def respond(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "object": "token_plan",
                "period": {"start_at": "2000-01-01 00:00:00", "end_at": "2100-01-01 00:00:00"},
                "quota": {"total_credits": 1000, "used_credits": 100, "remaining_credits": 900},
            },
        )

    monkeypatch.setattr(
        platform_model_transport.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    key = PlatformApiKey(
        "tp-fixture",
        {
            "provider": "xiaomi",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo",
            "display_name": "MiMo",
            "revision": 1,
            "source": "environment",
        },
    )
    result = await llm_quota_monitor.fetch_xiaomi_token_plan_quota(
        key, base_url="https://token-plan-cn.xiaomimimo.com/v1"
    )
    assert result["remaining_percent"] == 90
    assert len(captured) == 1 and captured[0].method == "GET" and captured[0].content == b""


@pytest.fixture
def litellm_budget_gateway(monkeypatch):
    """Exercise the real transport and admission without a running gateway."""
    from datetime import UTC, datetime, timedelta

    import httpx

    from modstore_server import llm_runtime_route, platform_model_transport
    from modstore_server.platform_model_config import PlatformApiKey

    key = PlatformApiKey(
        "sk-gateway-fixture-must-not-leak",
        {
            "provider": "litellm",
            "base_url": "http://127.0.0.1:14000/gateway/v1",
            "model": "xcmax-kimi-code",
            "display_name": "LiteLLM",
            "revision": 1,
            "source": "environment",
        },
    )
    state = {
        # A different reporting window: this value MUST NOT enter admission.
        "global": {"max_budget": 100.0, "spend": 999999.0},
        "user": {
            "user_id": "litellm-proxy-budget",
            "user_info": {
                "user_id": "litellm-proxy-budget",
                "max_budget": 100.0,
                "spend": 10.0,
                "budget_duration": "30d",
                "budget_reset_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "metadata": {"secret": str(key)},
            },
            "keys": [{"key": str(key)}],
        },
        "statuses": {},
        "calls": [],
        "key": key,
    }
    real_client = httpx.AsyncClient

    def respond(request):
        state["calls"].append(request)
        assert request.method == "GET" and request.content == b""
        assert request.headers["Authorization"] == f"Bearer {key}"
        assert request.url.host == "127.0.0.1" and request.url.port == 14000
        assert str(key) not in str(request.url)
        if request.url.path == "/gateway/global/spend":
            assert not request.url.query
            payload = state["global"]
        elif request.url.path == "/gateway/user/info":
            assert dict(request.url.params) == {"user_id": "litellm-proxy-budget"}
            payload = state["user"]
        else:
            pytest.fail(f"budget lookup attempted an unexpected route: {request.url.path}")
        return httpx.Response(
            state["statuses"].get(request.url.path, 200),
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Location": "https://other.test/"},
        )

    monkeypatch.setattr(
        platform_model_transport.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(llm_quota_monitor, "platform_api_key", lambda _provider: key)
    # A rotation cannot pair the captured credential with a second endpoint read.
    monkeypatch.setattr(
        llm_quota_monitor, "platform_base_url", lambda _provider: "https://other.test/v1"
    )
    monkeypatch.setattr(llm_quota_monitor, "_local_usage_by_provider", lambda *_args: {})
    monkeypatch.setattr(
        llm_runtime_route,
        "probe_runtime_route",
        lambda *_args: pytest.fail("budget admission must not consume a model probe"),
    )
    monkeypatch.setenv("MODSTORE_LLM_QUOTA_WARNING_PERCENT", "15")
    return state


async def _litellm_snapshot_and_admission():
    from modstore_server.strategic_portfolio_usage import planning_admission

    snapshot = await llm_quota_monitor.platform_quota_snapshot(
        live_probe=False,
        isolated_http=True,
        catalog={"providers": [{"provider": "litellm", "configured": True}]},
    )
    return snapshot["providers"][0], await planning_admission("litellm", "xcmax-kimi-code")


@pytest.mark.parametrize(
    ("spend", "percent", "admitted", "state"),
    [
        (0, 100, True, "healthy"),
        (80, 20, True, "healthy"),
        (80.001, 19, False, "healthy"),
        (90, 10, False, "warning"),
        (100, 0, False, "exhausted"),
        (110, 0, False, "exhausted"),
    ],
)
async def test_litellm_current_window_budget_controls_real_planning_admission(
    litellm_budget_gateway, spend, percent, admitted, state
):
    gateway = litellm_budget_gateway
    gateway["user"]["user_info"]["spend"] = spend
    row, admission = await _litellm_snapshot_and_admission()

    assert row["visibility"] == "exact" and row["state"] == state
    assert row["remaining_percent"] == percent
    assert row["source"] == "litellm_proxy_budget_api"
    resource = row["resources"][0]
    assert resource["resource"] == "general"
    assert resource["unit"] == "USD" and resource["scope"] == "gateway_budget"
    assert resource["spend"] == str(spend)
    assert (admission is not None) is admitted
    if admitted:
        assert admission["remaining_percent"] == percent
        assert admission["budget_source"] == "existing_platform_gateway_budget"
        assert admission["source"] == "litellm_proxy_budget_api"
        assert admission["max_calls"] == 1
    assert len(gateway["calls"]) == 4
    assert str(gateway["key"]) not in json.dumps([row, admission])


async def test_litellm_budget_percentage_uses_exact_decimal_floor(litellm_budget_gateway):
    gateway = litellm_budget_gateway
    gateway["global"]["max_budget"] = 0.3
    gateway["user"]["user_info"].update(max_budget=0.3, spend=0.24)
    row, admission = await _litellm_snapshot_and_admission()
    assert row["remaining_percent"] == 20 and admission is not None
    gateway["user"]["user_info"]["spend"] = 0.240000000000001
    row, admission = await _litellm_snapshot_and_admission()
    assert row["remaining_percent"] == 19 and admission is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "other-user"),
        ("max_budget", None),
        ("max_budget", 0),
        ("max_budget", -1),
        ("max_budget", 101),
        ("max_budget", True),
        ("max_budget", float("inf")),
        ("spend", None),
        ("spend", -1),
        ("spend", True),
        ("spend", "10"),
        ("spend", float("nan")),
        ("spend", float("inf")),
        ("budget_duration", None),
        ("budget_duration", "0d"),
        ("budget_reset_at", None),
        ("budget_reset_at", "2000-01-01T00:00:00+00:00"),
        ("budget_reset_at", "2100-01-01T00:00:00"),
        ("budget_reset_at", "invalid"),
    ],
)
async def test_litellm_incomplete_budget_never_becomes_exact_or_admitted(
    litellm_budget_gateway, field, value
):
    gateway = litellm_budget_gateway
    gateway["user"]["user_info"][field] = value
    row, admission = await _litellm_snapshot_and_admission()
    assert row["visibility"] == "usage_only" and row["state"] == "unknown"
    assert row["resources"] == [] and row["remaining_percent"] is None
    assert admission is None
    assert str(gateway["key"]) not in json.dumps(row)


@pytest.mark.parametrize(
    ("section", "payload"),
    [
        ("global", {}),
        ("global", {"max_budget": 0}),
        ("global", {"max_budget": float("nan")}),
        ("user", {}),
        ("user", {"user_id": "other-user"}),
        ("user", []),
    ],
)
async def test_litellm_missing_or_unlimited_live_budget_blocks(
    litellm_budget_gateway, section, payload
):
    litellm_budget_gateway[section] = payload
    row, admission = await _litellm_snapshot_and_admission()
    assert row["visibility"] == "usage_only" and admission is None


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
@pytest.mark.parametrize("endpoint", ["/gateway/global/spend", "/gateway/user/info"])
async def test_litellm_budget_read_error_or_no_database_blocks_without_redirect(
    litellm_budget_gateway, status, endpoint
):
    gateway = litellm_budget_gateway
    gateway["statuses"][endpoint] = status
    row, admission = await _litellm_snapshot_and_admission()
    assert row["visibility"] == "usage_only" and admission is None
    assert row["error"] == f"LiteLLM proxy budget http {status}"
    assert len(gateway["calls"]) == (2 if endpoint.endswith("/spend") else 4)
    assert str(gateway["key"]) not in json.dumps(row)
