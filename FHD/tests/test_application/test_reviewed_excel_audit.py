import pytest

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_audit import claim_request, verify_request


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
    assert record["state"] == "inflight" and record["source_sha256"] == "source"
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
    assert state["model_audit"][-1]["state"] == "inflight"
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
    assert state["model_audit"][-1]["state"] == "response_received"
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

    from app.application.reviewed_excel_template import _template_mimo_complete
    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter

    for name, value in {
        "FHD_TEMPLATE_MIMO_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
        "FHD_TEMPLATE_MIMO_MODEL": "mimo-v2.6-flash",
        "MIMO_API_KEY": "synthetic-placeholder",
        "FHD_ETL_LLM": "on",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", raising=False)
    if setting is not None:
        monkeypatch.setenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", setting)
    seen = []

    class Client:
        async def post(self, url, *, headers, json, timeout):
            assert timeout.read == expected
            assert "_reviewed_excel_transport_timeout" not in json
            seen.append(url)
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]},
                request=httpx.Request("POST", url),
            )

    async def fake_client(self):
        return Client()

    monkeypatch.setattr(OpenAICompatibleAdapter, "_get_client", fake_client)
    assert _template_mimo_complete([], {"type": "object"}, 100).data == {}
    assert len(seen) == 1
