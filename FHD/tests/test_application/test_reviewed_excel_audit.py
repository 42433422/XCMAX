import pytest

from app.application.etl.errors import ReviewedExcelError
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
