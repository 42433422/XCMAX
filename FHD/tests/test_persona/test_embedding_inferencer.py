"""L2 embedding 推断器测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.value_objects import PersonaAxes
from app.infrastructure.persona.embedding_client import EmbeddingClient
from app.services.persona.embedding_inferencer import EmbeddingInferencer, EmbeddingInferResult


class TestEmbeddingInferencer:
    """L2 embedding 推断器测试。"""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=EmbeddingClient)
        client.embed_texts = AsyncMock(return_value=[[0.1] * 8, [0.2] * 8, [0.3] * 8])
        return client

    @pytest.fixture
    def inferencer(self, mock_client):
        return EmbeddingInferencer(mock_client)

    @pytest.mark.asyncio
    async def test_infer_returns_result_with_axes(self, inferencer):
        messages = ["你好", "帮我查订单", "详细说说"]
        result = await inferencer.infer("user-1", messages)
        assert isinstance(result, EmbeddingInferResult)
        assert isinstance(result.axes, PersonaAxes)
        assert isinstance(result.pattern_label, str)

    @pytest.mark.asyncio
    async def test_infer_empty_messages_returns_neutral(self, inferencer):
        result = await inferencer.infer("user-1", [])
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_client_failure_returns_neutral(self, mock_client):
        mock_client.embed_texts = AsyncMock(side_effect=Exception("API down"))
        inferencer = EmbeddingInferencer(mock_client)
        result = await inferencer.infer("user-1", ["你好"])
        # 容错：返回中性值，不抛异常
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_single_message_returns_result(self, inferencer):
        result = await inferencer.infer("user-1", ["你好呀😊"])
        assert 0.0 <= result.axes.warmth <= 1.0
