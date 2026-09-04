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
        ("https://minimaxi.com.evil.example", "https://www.minimax.io/v1/token_plan/remains"),
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
