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

    @pytest.mark.asyncio
    async def test_infer_discriminates_styles_by_embedding_values(self):
        """守卫真实现：必须按 embedding 的值（参照质心余弦最近邻）区分模式，

        而非旧占位的"向量维度长度/消息条数"。给不同风格的可分向量，
        应稳定落到对应模式——占位逻辑做不到这一点。
        """

        def fake(texts):
            out = []
            for t in texts:
                if any(k in t for k in ("详细", "耐心", "展开", "注意事项")):
                    out.append([1.0, 0, 0, 0, 0, 0, 0, 0])
                elif any(k in t for k in ("简要", "确认", "结论", "订单状态")):
                    out.append([0, 1.0, 0, 0, 0, 0, 0, 0])
                elif any(k in t for k in ("步骤", "优先级", "计划", "行动")):
                    out.append([0, 0, 1.0, 0, 0, 0, 0, 0])
                else:
                    out.append([0.5, 0.5, 0, 0, 0, 0, 0, 0])
            return out

        client = MagicMock(spec=EmbeddingClient)
        client.embed_texts = AsyncMock(side_effect=lambda texts: fake(texts))

        proactive = await EmbeddingInferencer(client).infer(
            "u", ["帮我把任务拆成步骤排好优先级", "给我清晰的计划和行动项", "下一步的步骤是什么"]
        )
        assert proactive.pattern_label == "proactive_structured"
        assert proactive.confidence > 0.3

        concise = await EmbeddingInferencer(client).infer(
            "u", ["请简要回复", "确认继续", "需要结论"]
        )
        assert concise.pattern_label == "concise_formal"
