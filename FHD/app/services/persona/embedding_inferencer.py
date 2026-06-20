"""L2 embedding 推断器：定期聚类发现隐藏模式。"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes
from app.infrastructure.persona.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingInferResult:
    """L2 embedding 推断结果。"""

    axes: PersonaAxes
    pattern_label: str
    confidence: float


# 聚类中心 → 四轴参数映射（预标注校准表，简化版）
# 实际生产中应通过标注数据校准
_CLUSTER_AXES_MAP: dict[str, PersonaAxes] = {
    "warm_detailed": PersonaAxes(warmth=0.8, detail=0.7, proactivity=0.6, structure=0.5),
    "concise_formal": PersonaAxes(warmth=0.3, detail=0.3, proactivity=0.4, structure=0.7),
    "proactive_structured": PersonaAxes(warmth=0.5, detail=0.6, proactivity=0.8, structure=0.8),
    "neutral": PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5),
}


class EmbeddingInferencer:
    """L2 embedding 推断器。

    流程：
    1. 调外部 embedding API 生成向量
    2. K-means 聚类（k=3-5）
    3. 聚类中心映射到四轴参数空间

    延迟预算：~200ms（异步，不阻塞对话）
    作用：发现规则捕捉不到的长期风格模式
    """

    def __init__(self, client: EmbeddingClient):
        self._client = client

    async def infer(self, user_id: str, messages: list[str]) -> EmbeddingInferResult:
        """推断四轴参数。

        Args:
            user_id: 用户 ID
            messages: 最近 N 条用户消息

        Returns:
            EmbeddingInferResult: 四轴值 + 模式标签 + 置信度
        """
        if not messages:
            return EmbeddingInferResult(
                axes=PersonaAxes(),
                pattern_label="no_data",
                confidence=0.0,
            )

        try:
            embeddings = await self._client.embed_texts(messages)
            if not embeddings:
                return EmbeddingInferResult(
                    axes=PersonaAxes(),
                    pattern_label="no_data",
                    confidence=0.0,
                )

            # 简化版：用平均向量距离匹配最近的预标注模式
            # 生产环境应使用 K-means 聚类
            pattern = self._match_pattern(embeddings)
            axes = _CLUSTER_AXES_MAP.get(pattern, PersonaAxes())
            return EmbeddingInferResult(
                axes=axes,
                pattern_label=pattern,
                confidence=0.6,
            )
        except Exception as e:
            logger.warning("L2 embedding 推断失败，返回中性值: %s", e)
            return EmbeddingInferResult(
                axes=PersonaAxes(),
                pattern_label="error",
                confidence=0.0,
            )

    def _match_pattern(self, embeddings: list[list[float]]) -> str:
        """简化版模式匹配（生产环境用 K-means）。

        根据向量统计特征（方差、均值）粗略匹配模式。
        """
        if not embeddings:
            return "neutral"

        # 简化：用向量维度方差作为风格一致性指标
        # 实际生产应训练分类器或聚类
        first_vec = embeddings[0]
        avg_len = sum(len(v) for v in embeddings) / len(embeddings)

        # 占位逻辑：根据向量长度和数量粗略分类
        # 生产环境替换为 K-means + 标注校准
        if len(embeddings) >= 3 and avg_len > 100:
            return "warm_detailed"
        if len(embeddings) <= 1:
            return "concise_formal"
        return "neutral"
