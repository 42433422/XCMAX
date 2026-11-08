"""Market transport facts the reviewed-Excel call lifecycle depends on."""

import json

import httpx
import pytest

from app.application.elt.llm_session_provider import SessionMarketProvider
from app.domain.shared_services.conversation.modstore_adapter import ModstorePlatformAdapter
from app.infrastructure.modstore_transport import MarketSSEDecoder


def _decoded(lines):
    decoder = MarketSSEDecoder(lambda text: '"delta"' in text)
    return [json.loads(out) for line in lines if (out := decoder.feed(line)) is not None]


def test_done_event_carries_finish_reason_usage_and_replay():
    out = _decoded(
        [
            "event: done",
            'data: {"finish_reason": "length", "usage": {"completion_tokens": 9, "x": "y"},'
            ' "replayed": true}',
        ]
    )
    assert out == [{"replayed": True, "finish_reason": "length", "usage": {"completion_tokens": 9}}]


def _collect(payloads, max_tokens=10):
    adapter = ModstorePlatformAdapter.__new__(ModstorePlatformAdapter)
    adapter.last_route_metadata = {}
    adapter.default_provider, adapter.default_model = "p", "m"
    pieces, ending = [], {}
    for payload in payloads:
        adapter._absorb_stream_payload(json.dumps(payload), None, pieces, ending)
    return adapter._normalize_collected(pieces, "p", "m", ending, max_tokens)


def test_collected_stream_reports_the_real_finish_reason():
    response = _collect([{"state": "accepted"}, {"delta": "ab"}, {"finish_reason": "length"}])
    assert response["choices"][0]["finish_reason"] == "length"
    assert response["choices"][0]["message"]["content"] == "ab"


def test_spent_budget_is_truncation_when_the_market_omits_finish_reason():
    response = _collect([{"delta": "ab"}, {"usage": {"completion_tokens": 10}}])
    assert response["choices"][0]["finish_reason"] == "length"
    replay = _collect([{"delta": "ab"}, {"replayed": True, "finish_reason": "stop"}])
    assert replay["replayed"] is True and replay["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, {}, {"supported": False}),
        (405, {}, {"supported": False}),
        (500, {}, None),
        (200, {"state": "bogus"}, None),
        (200, {"state": "processing"}, {"supported": True, "state": "processing"}),
        (200, {"state": "not_found"}, {"supported": True, "state": "not_found"}),
    ],
)
async def test_lookup_maps_old_markets_to_unsupported(monkeypatch, status, body, expected):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(
        "app.application.elt_login_authorization._platform_url", lambda: "https://market.invalid"
    )
    provider = SessionMarketProvider(7, "synthetic", timeout_seconds=1)
    assert await provider.lookup_call("a" * 32) == expected
    assert seen == ["/api/llm/chat/requests/" + "a" * 32]
    assert await provider.lookup_call("bad id") is None and len(seen) == 1
