import json

import pytest

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_audit import (
    PROCESS_BOOT,
    abandon_call,
    claim_request,
    mark_answered,
    normalize_audit,
    record_response,
    recovery_action,
    settle_call,
    transition,
    verify_request,
)


def test_claim_binds_source_version_and_exact_request_without_headers():
    state = {}
    request = {
        "messages": [{"role": "user", "content": "合成内容"}],
        "schema": {},
        "max_tokens": 4000,
    }
    digest = claim_request(
        state,
        request,
        source_sha256="source",
        version="version",
        classification_id="id",
        code_version="code",
        model="model",
        phase="classification",
    )
    request["messages"][0]["content"] = "changed"
    record = state["model_audit"][0]
    assert record["request"]["messages"][0]["content"] == "合成内容"
    assert record["state"] == "sent" and record["source_sha256"] == "source"
    verify_request(record["request"], digest)
    with pytest.raises(ReviewedExcelError, match="不一致"):
        verify_request(request, digest)
    with pytest.raises(ReviewedExcelError, match="格式"):
        claim_request(
            {},
            {**request, "headers": {}},
            source_sha256="s",
            version="v",
            classification_id="i",
            code_version="c",
            model="m",
            phase="classification",
        )


def test_transport_captures_raw_before_json_and_does_not_send_hook():
    import asyncio

    import httpx

    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    body = b'{"choices":[],"usage":{"total_tokens":3}}'
    seen = []

    class Client:
        async def post(self, url, *, headers, json):
            assert "_reviewed_excel_audit_response" not in json
            return httpx.Response(
                200,
                content=body,
                headers={"x-request-id": "req-synthetic"},
                request=httpx.Request("POST", url),
            )

    adapter = OpenAICompatibleAdapter(
        provider="xiaomi", api_key="fake-private-credential", model="mimo-v2.6-flash"
    )

    async def fake_client():
        return Client()

    adapter._get_client = fake_client
    result = asyncio.run(
        adapter.chat_completion(
            [{"role": "user", "content": "synthetic"}],
            _reviewed_excel_audit_response=lambda raw, status, rid: seen.append((raw, status, rid)),
        )
    )
    assert seen == [(body, 200, "req-synthetic")]
    assert result["usage"] == {"total_tokens": 3}


def test_response_record_rejects_duplicate_and_over_budget():
    from app.application.reviewed_excel_audit import record_response

    state = {}
    request = {"messages": [], "schema": {}, "max_tokens": 1}
    digest = claim_request(
        state,
        request,
        source_sha256="s",
        version="v",
        classification_id="i",
        code_version="c",
        model="m",
        phase="classification",
    )
    with pytest.raises(ReviewedExcelError, match="预算"):
        record_response(state, digest, b"x" * 2_000_001, 200, "req")
    assert state["model_audit"][-1]["state"] == "sent"
    record_response(state, digest, b"{}", 200, "req")
    with pytest.raises(ReviewedExcelError, match="状态"):
        record_response(state, digest, b"{}", 200, "req")


def test_unsent_audit_cannot_release_a_received_or_different_request():
    from app.application.reviewed_excel_audit import record_not_sent, record_response

    state = {"analysis_checkpoint": {"phase": "inflight", "calls_in_round": 2}}
    digest = claim_request(
        state,
        {"messages": [], "schema": {}, "max_tokens": 1},
        source_sha256="s",
        version="v",
        classification_id="i",
        code_version="c",
        model="m",
        phase="classification",
    )
    with pytest.raises(ReviewedExcelError, match="未解除"):
        record_not_sent(state, "other-request", "未发送")
    assert state["analysis_checkpoint"]["phase"] == "inflight"
    record_response(state, digest, b"{}", 200, "synthetic")
    with pytest.raises(ReviewedExcelError, match="未解除"):
        record_not_sent(state, digest, "未发送")
    assert state["model_audit"][-1]["state"] == "streaming"
    assert state["analysis_checkpoint"]["calls_in_round"] == 2


@pytest.mark.parametrize("seconds", [1, 10.5, 120, 180])
def test_template_transport_timeout_is_private_and_bounded(monkeypatch, seconds):
    import asyncio

    import httpx

    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    seen = []

    class Client:
        async def post(self, url, *, headers, json, timeout):
            assert not any(key.startswith("_reviewed_excel") for key in json)
            assert timeout.read == timeout.write == timeout.pool == seconds
            assert timeout.connect == min(10, seconds)
            seen.append(json)
            return httpx.Response(200, json={"choices": []}, request=httpx.Request("POST", url))

    async def fake_client():
        return Client()

    adapter = OpenAICompatibleAdapter(provider="xiaomi", api_key="synthetic-key")
    monkeypatch.setattr(adapter, "_get_client", fake_client)
    asyncio.run(adapter.chat_completion([], _reviewed_excel_transport_timeout=seconds))
    assert len(seen) == 1


@pytest.mark.parametrize(
    "seconds", [None, True, "120", 0, -1, 181, 10**1000, float("inf"), float("-inf"), float("nan")]
)
def test_invalid_template_transport_timeout_is_rejected_before_client(monkeypatch, seconds):
    import asyncio

    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    adapter = OpenAICompatibleAdapter(provider="xiaomi", api_key="synthetic-key")

    async def unexpected_client():
        pytest.fail("Invalid timeout must not create a client or send a request")

    monkeypatch.setattr(adapter, "_get_client", unexpected_client)
    with pytest.raises(ValueError, match="bounded template transport timeout"):
        asyncio.run(adapter.chat_completion([], _reviewed_excel_transport_timeout=seconds))


@pytest.mark.parametrize("provider", ["xiaomi", "openai", "deepseek"])
def test_ordinary_transport_preserves_default_timeout(monkeypatch, provider):
    import asyncio

    import httpx

    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    real_client = httpx.AsyncClient
    seen = []

    def capture(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"choices": []})

    def fake_client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(capture), trust_env=False)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    adapter = OpenAICompatibleAdapter(provider=provider, api_key="synthetic-key")

    async def call():
        try:
            await adapter.chat_completion([])
        finally:
            await adapter.close()

    asyncio.run(call())
    assert seen == [{"connect": 10.0, "read": 30.0, "write": 30.0, "pool": 30.0}]


def test_template_transport_timeout_preserves_exception_without_retry(monkeypatch):
    import asyncio

    import httpx

    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    calls = []
    failure = httpx.ReadTimeout("synthetic timeout")

    class Client:
        async def post(self, url, **kwargs):
            calls.append(url)
            raise failure

    async def fake_client():
        return Client()

    adapter = OpenAICompatibleAdapter(provider="xiaomi", api_key="synthetic-key")
    monkeypatch.setattr(adapter, "_get_client", fake_client)
    with pytest.raises(httpx.ReadTimeout) as caught:
        asyncio.run(adapter.chat_completion([], _reviewed_excel_transport_timeout=120))
    assert caught.value is failure
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["openai", "minimax"])
def test_template_timeout_cannot_override_other_providers(monkeypatch, provider):
    import asyncio

    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    adapter = OpenAICompatibleAdapter(provider=provider, api_key="synthetic-key")

    async def unexpected(*args, **kwargs):
        pytest.fail("Template timeout must not change other provider requests")

    monkeypatch.setattr(adapter, "_get_client", unexpected)
    monkeypatch.setattr(adapter, "_chat_minimax_token_plan", unexpected)
    with pytest.raises(ValueError, match="bounded template transport timeout"):
        asyncio.run(adapter.chat_completion([], _reviewed_excel_transport_timeout=120))


@pytest.mark.parametrize("setting, expected", [(None, 120), ("180", 180)])
def test_template_call_passes_configured_timeout_to_http(monkeypatch, setting, expected):
    import httpx

    from app.application.elt import llm_session_provider
    from app.application.reviewed_excel_template import _template_platform_complete

    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://synthetic.invalid")
    monkeypatch.delenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", raising=False)
    if setting is not None:
        monkeypatch.setenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", setting)
    seen = []

    def respond(request):
        assert request.extensions["timeout"]["read"] == expected
        assert request.headers["Authorization"] == "Bearer synthetic-session-token"
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            assert request.url.path == "/api/llm/resolve-chat-default"
            assert not request.url.params
            return httpx.Response(
                200,
                json={"ok": True, "provider": "deepseek", "model": "synthetic-model"},
            )
        assert request.url.path == "/api/llm/chat/stream"
        body = json.loads(request.content)
        assert body["provider"] == "deepseek" and body["model"] == "synthetic-model"
        assert "_reviewed_excel_transport_timeout" not in body
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"delta":"{}"}\n\ndata: [DONE]\n\n',
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**(kwargs | {"transport": httpx.MockTransport(respond)})),
    )

    def session_provider(*, timeout_seconds):
        assert timeout_seconds == expected
        return llm_session_provider.SessionMarketProvider(
            7, "synthetic-session-token", timeout_seconds=timeout_seconds
        )

    monkeypatch.setattr(llm_session_provider, "current_owner_market_provider", session_provider)
    assert _template_platform_complete([], {"type": "object"}, 100, owner_id=7).data == {}
    assert seen == [("GET", "/api/llm/resolve-chat-default"), ("POST", "/api/llm/chat/stream")]


def test_audited_stream_keeps_provider_body_and_parsed_result(monkeypatch):
    """A consumed SSE body must be archived. response.content raises ResponseNotRead."""
    import httpx

    from app.application.elt import llm_session_provider
    from app.application.reviewed_excel_audit import capture_response
    from app.application.reviewed_excel_template import _template_platform_complete

    sse = (
        b'event: meta\ndata: {"ok":true,"provider":"xiaomi","model":"mimo-v2.6-flash"}\n\n'
        b'event: status\ndata: {"state":"processing","request_id":"upstream-synthetic"}\n\n'
        b'event: delta\ndata: {"delta":"{"}\n\n'
        b'event: delta\ndata: {"delta":"}"}\n\n'
        b'event: done\ndata: {"ok":true,"content":"{}","provider":"xiaomi",'
        b'"model":"mimo-v2.6-flash"}\n\n'
        b"event: tail\ndata: after-done\n\n"
    )

    class Chunked(httpx.AsyncByteStream):
        def __init__(self, payload: bytes):
            self.payload = payload

        async def __aiter__(self):
            for index in range(0, len(self.payload), 17):
                yield self.payload[index : index + 17]

        async def aclose(self):
            return None

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == "/api/llm/resolve-chat-default":
                return httpx.Response(
                    200, json={"ok": True, "provider": "xiaomi", "model": "mimo-v2.6-flash"}
                )
            assert request.url.path == "/api/llm/chat/stream"
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/event-stream",
                    "x-request-id": "upstream-synthetic",
                },
                stream=Chunked(sse),
            )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**(kwargs | {"transport": Transport()})),
    )
    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://synthetic.invalid")

    def session_provider(*, timeout_seconds):
        return llm_session_provider.SessionMarketProvider(
            7, "synthetic-session-token", timeout_seconds=timeout_seconds
        )

    monkeypatch.setattr(llm_session_provider, "current_owner_market_provider", session_provider)
    archived = []

    def save(raw, status, request_id):
        archived.append((raw, status, request_id))

    with capture_response(save):
        result = _template_platform_complete(
            [{"role": "user", "content": "synthetic"}], {"type": "object"}, 100, owner_id=7
        )
    assert result.data == {}
    assert archived == [(sse, 200, "upstream-synthetic")]


def _claimed(state=None):
    state = state if state is not None else {"analysis_checkpoint": {"phase": "ready"}}
    digest = claim_request(
        state,
        {"messages": [{"role": "user", "content": "合成"}], "schema": {}, "max_tokens": 10},
        source_sha256="s",
        version="v",
        classification_id="i",
        code_version="c",
        model="m",
        phase="classification",
        provider="mimo",
    )
    return state, digest


def test_claim_records_call_id_owner_and_sent_state():
    state, digest = _claimed()
    record = state["model_audit"][0]
    assert record["state"] == "sent" and record["attempts"] == 1
    assert len(record["call_id"]) == 32 and record["owner"]["boot"] == PROCESS_BOOT
    assert record["request_sha256"] == digest


def test_legacy_states_load_lazily_without_rewriting_meaning():
    state = {
        "model_audit": [
            {"state": "inflight"},
            {"state": "inflight", "outcome": "unknown"},
            {"state": "unanswered"},
            {"state": "response_received", "http_status": 200},
            {"state": "response_received", "http_status": 200, "outcome": "answered_invalid"},
            {"state": "response_received", "http_status": 502},
            {"state": "rejected"},
        ]
    }
    normalize_audit(state)
    assert [r["state"] for r in state["model_audit"]] == [
        "sent",
        "unknown",
        "unknown",
        "answered_valid",
        "answered_invalid",
        "unknown",
        "rejected",
    ]
    assert state["model_audit"][0]["legacy_state"] == "inflight"


def test_an_old_unanswered_claim_is_never_released_by_age():
    old = {"state": "inflight", "request_sha256": "abc"}
    assert recovery_action(old, None) == "locked"
    assert recovery_action(old, {"supported": True, "state": "not_found"}) == "locked"


def test_recovery_needs_a_market_that_confirms_idempotency():
    record = {"call_id": "a" * 32}
    assert recovery_action(record, None) == "locked"
    assert recovery_action(record, {"supported": False}) == "locked"
    assert recovery_action(record, {"supported": True, "state": "processing"}) == "wait"
    for market_state in ("not_found", "completed", "failed"):
        assert recovery_action(record, {"supported": True, "state": market_state}) == "resend"


def test_same_key_recovery_reuses_the_record_instead_of_a_new_call():
    state, digest = _claimed()
    settle_call(state, digest, "unknown", "transport lost")
    call_id = state["model_audit"][0]["call_id"]
    state["analysis_checkpoint"]["recovery"] = {"call_id": call_id, "request_sha256": digest}
    _state, again = _claimed(state)
    assert again == digest and len(state["model_audit"]) == 1
    record = state["model_audit"][0]
    assert record["state"] == "sent" and record["attempts"] == 2 and record["call_id"] == call_id
    state["analysis_checkpoint"]["recovery"] = {"call_id": call_id, "request_sha256": "0" * 64}
    with pytest.raises(ReviewedExcelError, match="恢复请求"):
        _claimed(state)


def test_settled_states_follow_the_lifecycle():
    state, digest = _claimed()
    record_response(state, digest, b'{"choices":[]}', 200, "rid")
    assert state["model_audit"][0]["state"] == "streaming"
    settle_call(state, digest, "truncated", "length")
    assert state["model_audit"][0]["state"] == "truncated"
    with pytest.raises(ReviewedExcelError):
        transition(state["model_audit"][0], "answered_valid")
    state, digest = _claimed()
    record_response(state, digest, b'event: done\ndata: {"replayed": true}\n\n', 200, None)
    assert state["model_audit"][0]["state"] == "recovered"
    mark_answered(state, digest)
    assert state["model_audit"][0]["state"] == "answered_valid"


def test_abandon_requires_an_unknown_call_and_marks_a_possible_duplicate_charge():
    state, digest = _claimed()
    with pytest.raises(ReviewedExcelError, match="本进程"):
        abandon_call(state, digest, authorized_by="user:3", note="synthetic")
    settle_call(state, digest, "unknown", "transport lost")
    state["analysis_checkpoint"]["phase"] = "inflight"
    record = abandon_call(state, digest, authorized_by="user:3", note="synthetic")
    assert record["state"] == "abandoned" and record["possible_duplicate_charge"] is True
    assert state["analysis_checkpoint"]["phase"] == "ready"
    with pytest.raises(ReviewedExcelError):
        abandon_call(state, digest, authorized_by="user:3", note="again")
