"""L2 embedding 推断器：K-means 聚类 + 参照质心标注校准，发现隐藏风格模式。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from app.domain.persona.value_objects import PersonaAxes
from app.infrastructure.persona.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingInferResult:
    """L2 embedding 推断结果。"""

    axes: PersonaAxes
    pattern_label: str
    confidence: float


# 聚类中心 → 四轴参数映射（预标注校准表）
_CLUSTER_AXES_MAP: dict[str, PersonaAxes] = {
    "warm_detailed": PersonaAxes(warmth=0.8, detail=0.7, proactivity=0.6, structure=0.5),
    "concise_formal": PersonaAxes(warmth=0.3, detail=0.3, proactivity=0.4, structure=0.7),
    "proactive_structured": PersonaAxes(warmth=0.5, detail=0.6, proactivity=0.8, structure=0.8),
    "neutral": PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5),
}

# 每个模式的参照语料（标注校准锚点）：用其 embedding 质心作为该模式在向量空间的代表。
# 用户消息簇质心 → 余弦最近的参照质心 = 该用户的风格模式。"neutral" 为无锚点兜底。
_PATTERN_REFERENCES: dict[str, list[str]] = {
    "warm_detailed": [
        "谢谢你这么耐心，能不能再详细说说每一步具体怎么操作呀～",
        "辛苦啦！我想多了解一点背景，麻烦展开讲讲细节，越细越好",
        "好的好的，感谢～可以把每个注意事项都列清楚一些吗",
    ],
    "concise_formal": [
        "请提供订单状态。",
        "确认。继续下一步。",
        "需要结论，简要回复即可。",
    ],
    "proactive_structured": [
        "帮我把这件事拆成步骤、排好优先级并安排好时间表",
        "请主动列出后续行动项，按 1/2/3 结构化推进",
        "下一步该做什么，给我一个清晰的计划和负责人分工",
    ],
}

_MIN_KMEANS_SAMPLES = 4  # 样本足够多才做 K-means 取主导簇，否则直接用整体质心


class EmbeddingInferencer:
    """L2 embedding 推断器。

    流程：
    1. 调外部 embedding API 把最近消息转向量
    2. K-means 聚类（k≤3）取**主导风格簇**质心，抗离群消息
    3. 主导质心 → 余弦最近的预标注参照质心（标注校准）→ 四轴参数

    无 ``XCAGI_EMBEDDING_API_KEY`` 时 client 返回空向量 → 优雅降级中性值。
    延迟预算：~200ms（异步，不阻塞对话）。
    """

    def __init__(self, client: EmbeddingClient):
        self._client = client
        # 参照质心懒加载缓存：{pattern: centroid_vector}
        self._ref_centroids: dict[str, np.ndarray] | None = None

    async def infer(self, user_id: str, messages: list[str]) -> EmbeddingInferResult:
        """推断四轴参数。

        Args:
            user_id: 用户 ID
            messages: 最近 N 条用户消息

        Returns:
            EmbeddingInferResult: 四轴值 + 模式标签 + 置信度
        """
        if not messages:
            return EmbeddingInferResult(axes=PersonaAxes(), pattern_label="no_data", confidence=0.0)

        try:
            raw = await self._client.embed_texts(messages)
            embeddings = _as_matrix(raw)
            if embeddings is None:
                return EmbeddingInferResult(
                    axes=PersonaAxes(), pattern_label="no_data", confidence=0.0
                )

            dominant = _dominant_centroid(embeddings)
            refs = await self._reference_centroids(embeddings.shape[1])
            pattern, confidence = _nearest_pattern(dominant, refs)
            axes = _CLUSTER_AXES_MAP.get(pattern, PersonaAxes())
            return EmbeddingInferResult(axes=axes, pattern_label=pattern, confidence=confidence)
        except Exception as e:  # noqa: BLE001  embedding API 边界：任何异常都降级为中性值
            logger.warning("L2 embedding 推断失败，返回中性值: %s", e)
            return EmbeddingInferResult(axes=PersonaAxes(), pattern_label="error", confidence=0.0)

    async def _reference_centroids(self, dim: int) -> dict[str, np.ndarray]:
        """懒加载并缓存各模式参照语料的 embedding 质心（与用户向量同源、同维）。"""
        if self._ref_centroids is not None:
            return self._ref_centroids

        centroids: dict[str, np.ndarray] = {}
        try:
            flat_texts: list[str] = []
            owners: list[str] = []
            for pattern, refs in _PATTERN_REFERENCES.items():
                for text in refs:
                    flat_texts.append(text)
                    owners.append(pattern)
            vectors = _as_matrix(await self._client.embed_texts(flat_texts))
            if vectors is not None and vectors.shape[1] == dim:
                grouped: dict[str, list[np.ndarray]] = {}
                for owner, vec in zip(owners, vectors):  # 长度不齐时 zip 取短，已防御
                    grouped.setdefault(owner, []).append(vec)
                for pattern, vecs in grouped.items():
                    centroids[pattern] = np.mean(np.stack(vecs), axis=0)
        except Exception as e:  # noqa: BLE001  参照向量失败不致命，退化为无锚点
            logger.warning("L2 参照质心加载失败，退化为中性匹配: %s", e)

        self._ref_centroids = centroids
        return centroids


def _as_matrix(raw: object) -> np.ndarray | None:
    """把 embed_texts 结果转成 (n, dim) float 矩阵；空/非法返回 None。"""
    if not raw or not isinstance(raw, list):
        return None
    try:
        arr = np.asarray(raw, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] == 0:
        return None
    return arr


def _dominant_centroid(embeddings: np.ndarray) -> np.ndarray:
    """K-means 取最大簇的质心（样本不足则用整体质心），抗离群消息。"""
    n = embeddings.shape[0]
    if n < _MIN_KMEANS_SAMPLES:
        return embeddings.mean(axis=0)
    k = min(3, n)
    labels, centers = _kmeans(embeddings, k)
    counts = np.bincount(labels, minlength=k)
    return centers[int(np.argmax(counts))]


def _kmeans(x: np.ndarray, k: int, iters: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """确定性迷你 K-means（首 k 个去重点初始化，Lloyd 迭代），无随机依赖。"""
    # 去重作为初始中心，保证确定性与可复现（测试友好）
    uniq = np.unique(x, axis=0)
    if uniq.shape[0] < k:
        k = max(1, uniq.shape[0])
    centers = uniq[:k].astype(float)
    labels = np.zeros(x.shape[0], dtype=int)
    for _ in range(iters):
        dists = np.linalg.norm(x[:, None, :] - centers[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        if np.array_equal(new_labels, labels) and _ > 0:
            break
        labels = new_labels
        for c in range(k):
            members = x[labels == c]
            if len(members):
                centers[c] = members.mean(axis=0)
    return labels, centers


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _nearest_pattern(centroid: np.ndarray, refs: dict[str, np.ndarray]) -> tuple[str, float]:
    """主导质心 → 余弦最近的参照模式 + 置信度（按与次近的间隔）。无参照返回 neutral。"""
    if not refs:
        return "neutral", 0.3
    sims = sorted(
        ((pattern, _cosine(centroid, ref)) for pattern, ref in refs.items()),
        key=lambda kv: kv[1],
        reverse=True,
    )
    best_pattern, best_sim = sims[0]
    if best_sim <= 0.0:
        return "neutral", 0.3
    margin = best_sim - (sims[1][1] if len(sims) > 1 else 0.0)
    confidence = float(np.clip(0.5 + margin * 2.0, 0.3, 0.9))
    return best_pattern, confidence
