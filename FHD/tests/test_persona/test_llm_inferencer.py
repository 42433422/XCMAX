"""L3 LLM 推断器测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.value_objects import PersonaAxes
from app.services.persona.llm_inferencer import LlmInferencer, LlmInferResult


class TestLlmInferencer:
    """L3 LLM 推断器测试。"""

    @pytest.fixture
    def mock_llm_client(self):
        client = MagicMock()
        client.chat_completion = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "warmth": 0.7,
                                    "detail": 0.4,
                                    "proactivity": 0.6,
                                    "structure": 0.8,
                                    "reason": "用户倾向口语化交流",
                                }
                            )
                        }
                    }
                ]
            }
        )
        return client

    @pytest.fixture
    def inferencer(self, mock_llm_client):
        return LlmInferencer(mock_llm_client)

    @pytest.mark.asyncio
    async def test_infer_returns_result_with_axes(self, inferencer):
        history = [{"role": "user", "content": "你好呀"}, {"role": "assistant", "content": "你好"}]
        result = await inferencer.infer("user-1", history, PersonaAxes())
        assert isinstance(result, LlmInferResult)
        assert isinstance(result.axes, PersonaAxes)
        assert result.axes.warmth == 0.7
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_infer_empty_history_returns_neutral(self, inferencer):
        result = await inferencer.infer("user-1", [], PersonaAxes())
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_llm_failure_returns_neutral(self, mock_llm_client):
        mock_llm_client.chat_completion = AsyncMock(side_effect=Exception("LLM down"))
        inferencer = LlmInferencer(mock_llm_client)
        result = await inferencer.infer(
            "user-1",
            [{"role": "user", "content": "你好"}],
            PersonaAxes(),
        )
        # 容错：返回中性值，不抛异常
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_invalid_json_returns_neutral(self, mock_llm_client):
        mock_llm_client.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": "not json"}}]}
        )
        inferencer = LlmInferencer(mock_llm_client)
        result = await inferencer.infer(
            "user-1",
            [{"role": "user", "content": "你好"}],
            PersonaAxes(),
        )
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0
