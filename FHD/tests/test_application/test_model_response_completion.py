"""Provider normalization never promotes incomplete replies to complete output."""

from unittest.mock import AsyncMock, Mock

import pytest

from app.infrastructure.llm.response_completion import completion_is_incomplete, load_model_json


@pytest.mark.parametrize("shape", ["market", "openai"])
@pytest.mark.parametrize("finish_reason", [None, "length", "end_turn"])
def test_market_normalization_never_invents_successful_finish(monkeypatch, shape, finish_reason):
    from app.infrastructure.llm.modstore_response_normalize import normalize_market_chat_response

    text = '{"mode":"reply","reply":"你好"}'
    raw = {"content": text} if shape == "market" else {"choices": [{"message": {"content": text}}]}
    if finish_reason is not None:
        (raw if shape == "market" else raw["choices"][0])["finish_reason"] = finish_reason
    response = normalize_market_chat_response(raw, "fixture", "test")
    assert response["choices"][0]["finish_reason"] == finish_reason
    assert completion_is_incomplete(response) is (finish_reason != "end_turn")


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", [None, "end_turn", "max_tokens"])
async def test_minimax_adapter_preserves_unknown_finish(monkeypatch, finish_reason):
    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter
    from app.infrastructure.llm.response_completion import completion_is_incomplete

    adapter = OpenAICompatibleAdapter(provider="minimax", api_key="sk-cp-synthetic")
    data = {"content": [{"type": "text", "text": "你好"}]}
    if finish_reason is not None:
        data["stop_reason"] = finish_reason
    response = Mock(json=Mock(return_value=data))
    client = AsyncMock()
    client.post.return_value = response
    monkeypatch.setattr(adapter, "_get_client", AsyncMock(return_value=client))
    result = await adapter.chat_completion([{"role": "user", "content": "你好"}])
    assert result["choices"][0]["finish_reason"] == finish_reason
    assert completion_is_incomplete(result) is (finish_reason != "end_turn")


def test_model_json_repairs_json_syntax_without_a_second_model_call():
    parsed = load_model_json('{"mode":"workflow","nodes":[{"node_id":"n1",}]}')
    assert parsed["nodes"][0]["node_id"] == "n1"
