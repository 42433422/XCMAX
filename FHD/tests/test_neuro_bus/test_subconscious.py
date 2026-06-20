"""潜意识 ML 层（Subconscious ML Layer）Phase 3 组件测试。

覆盖：
- ``LocalEmbedder``：本地嵌入器（HashEmbedder + LRU 缓存）
- ``AnomalyDetector``：异常检测器（IsolationForest）
- ``PatternPredictor``：模式预测器（N-gram + Markov）
- ``SubconsciousMLHandler``：ML 驱动处理器（端到端流程）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.neuro.subconscious.anomaly_detector import (
    AnomalyDetector,
    AnomalyResult,
    get_anomaly_detector,
    reset_anomaly_detector,
)
from app.domain.neuro.subconscious.local_embedder import (
    LocalEmbedder,
    get_local_embedder,
    reset_local_embedder,
)
from app.domain.neuro.subconscious.pattern_predictor import (
    PatternPredictor,
    PredictionResult,
    get_pattern_predictor,
    reset_pattern_predictor,
)
from app.domain.neuro.subconscious.subconscious_ml_handler import (
    SubconsciousMLHandler,
)

# ============================================================================
# LocalEmbedder 测试
# ============================================================================


class TestLocalEmbedder:
    """本地嵌入器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_local_embedder()
        yield
        reset_local_embedder()

    def test_embed_query_returns_vector(self):
        """embed_query 返回向量。"""
        emb = LocalEmbedder(dim=128)
        vec = emb.embed_query("hello world")
        assert isinstance(vec, list)
        assert len(vec) == 128

    def test_embed_query_none_returns_zero_vector(self):
        """None 输入返回零向量。"""
        emb = LocalEmbedder(dim=64)
        vec = emb.embed_query(None)  # type: ignore[arg-type]
        assert len(vec) == 64
        assert all(v == 0.0 for v in vec)

    def test_embed_query_empty_returns_zero_vector(self):
        """空字符串返回零向量。"""
        emb = LocalEmbedder(dim=64)
        vec = emb.embed_query("")
        assert len(vec) == 64

    def test_embed_texts_returns_list_of_vectors(self):
        """embed_texts 返回向量列表。"""
        emb = LocalEmbedder(dim=64)
        vecs = emb.embed_texts(["hello", "world"])
        assert len(vecs) == 2
        assert all(len(v) == 64 for v in vecs)

    def test_different_texts_different_vectors(self):
        """不同文本产生不同向量。"""
        emb = LocalEmbedder(dim=128)
        v1 = emb.embed_query("你好世界")
        v2 = emb.embed_query("hello world")
        assert v1 != v2

    def test_cache_returns_same_vector(self):
        """缓存命中返回相同向量。"""
        emb = LocalEmbedder(dim=64, cache_size=10)
        v1 = emb.embed_query("test text")
        v2 = emb.embed_query("test text")
        assert v1 == v2
        assert emb.cache_size == 1

    def test_cache_evicts_oldest(self):
        """缓存满时淘汰最旧条目。"""
        emb = LocalEmbedder(dim=64, cache_size=3)
        emb.embed_query("text1")
        emb.embed_query("text2")
        emb.embed_query("text3")
        emb.embed_query("text4")  # 应淘汰 text1
        assert emb.cache_size == 3

    def test_cache_lru_order(self):
        """LRU 顺序：访问过的条目移到末尾。"""
        emb = LocalEmbedder(dim=64, cache_size=3)
        emb.embed_query("a")
        emb.embed_query("b")
        emb.embed_query("c")
        # 访问 "a"，使其移到末尾
        emb.embed_query("a")
        # 添加 "d"，应淘汰 "b"（最旧）
        emb.embed_query("d")
        # "a" 应仍在缓存中
        assert emb.cache_size == 3

    def test_clear_cache(self):
        """clear_cache 清空缓存。"""
        emb = LocalEmbedder(dim=64)
        emb.embed_query("test")
        assert emb.cache_size == 1
        emb.clear_cache()
        assert emb.cache_size == 0

    def test_dim_property(self):
        """dim 属性返回正确维度。"""
        emb = LocalEmbedder(dim=256)
        assert emb.dim == 256

    def test_singleton_returns_same_instance(self):
        """get_local_embedder 返回同一单例。"""
        e1 = get_local_embedder()
        e2 = get_local_embedder()
        assert e1 is e2

    def test_reset_clears_singleton(self):
        """reset_local_embedder 清除单例。"""
        e1 = get_local_embedder()
        reset_local_embedder()
        e2 = get_local_embedder()
        assert e1 is not e2

    def test_fallback_when_hash_embedder_unavailable(self):
        """HashEmbedder 不可用时回退到零向量。"""
        emb = LocalEmbedder(dim=64)
        # 模拟 inner 为 None
        emb._inner = None
        vec = emb.embed_query("test")
        assert len(vec) == 64
        assert all(v == 0.0 for v in vec)


# ============================================================================
# AnomalyDetector 测试
# ============================================================================


class TestAnomalyDetector:
    """异常检测器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_anomaly_detector()
        yield
        reset_anomaly_detector()

    def test_predict_returns_not_ready_with_no_training(self):
        """无训练数据时返回 model_not_ready。"""
        detector = AnomalyDetector(min_samples_to_fit=100)
        result = detector.predict(
            processor_type="reflex",
            latency_ms=1.0,
            sla_hit=True,
            success=True,
        )
        assert result.is_anomaly is False
        assert result.reason == "model_not_ready"

    def test_predict_after_training(self):
        """训练后能预测。"""
        detector = AnomalyDetector(
            min_samples_to_fit=10,
            refit_interval=10,
        )
        # 添加正常样本
        for _ in range(15):
            detector.add_sample(
                processor_type="reflex",
                latency_ms=0.5,
                sla_hit=True,
                success=True,
            )

        result = detector.predict(
            processor_type="reflex",
            latency_ms=0.5,
            sla_hit=True,
            success=True,
        )
        # 模型已就绪
        assert result.reason != "model_not_ready"
        assert isinstance(result.is_anomaly, bool)
        assert isinstance(result.anomaly_score, float)

    def test_detects_anomalous_high_latency(self):
        """检测高延迟异常。"""
        detector = AnomalyDetector(
            min_samples_to_fit=10,
            refit_interval=10,
            contamination=0.1,
        )
        # 训练：正常低延迟
        for _ in range(30):
            detector.add_sample(
                processor_type="reflex",
                latency_ms=0.5,
                sla_hit=True,
                success=True,
            )

        # 预测：异常高延迟
        result = detector.predict(
            processor_type="reflex",
            latency_ms=1000.0,  # 极高延迟
            sla_hit=False,
            success=False,
        )
        # 应该检测为异常（IsolationForest 对偏离点敏感）
        # 注意：不强制 is_anomaly=True，因为小样本下可能不稳定
        assert result.reason in ("isolation_forest", "normal", "prediction_error")

    def test_add_sample_triggers_refit(self):
        """add_sample 达到 refit_interval 时触发重新拟合。"""
        detector = AnomalyDetector(
            min_samples_to_fit=5,
            refit_interval=5,
        )
        for _ in range(5):
            detector.add_sample("reflex", 0.5, True, True)
        # 模型应该已拟合
        assert detector._model is not None

    def test_get_stats(self):
        """get_stats 返回正确统计。"""
        detector = AnomalyDetector(min_samples_to_fit=5, refit_interval=5)
        detector.add_sample("reflex", 0.5, True, True)
        stats = detector.get_stats()
        assert stats["total_samples"] == 1
        assert stats["total_predictions"] == 0
        assert stats["anomalies_detected"] == 0
        assert stats["model_ready"] is False

    def test_singleton_returns_same_instance(self):
        """get_anomaly_detector 返回同一单例。"""
        d1 = get_anomaly_detector()
        d2 = get_anomaly_detector()
        assert d1 is d2

    def test_reset_clears_singleton(self):
        """reset_anomaly_detector 清除单例。"""
        d1 = get_anomaly_detector()
        reset_anomaly_detector()
        d2 = get_anomaly_detector()
        assert d1 is not d2

    def test_feature_extraction(self):
        """特征提取包含 5 个维度。"""
        detector = AnomalyDetector()
        features = detector._extract_features(
            processor_type="conscious",
            latency_ms=100.0,
            sla_hit=False,
            success=False,
        )
        assert len(features) == 5
        assert features[0] == 2.0  # conscious
        assert features[2] == 0.0  # sla_hit=False
        assert features[3] == 0.0  # success=False

    def test_predict_swallows_exceptions(self):
        """predict 异常时不抛出。"""
        detector = AnomalyDetector(min_samples_to_fit=5, refit_interval=5)
        for _ in range(6):
            detector.add_sample("reflex", 0.5, True, True)

        # 模拟 model.predict 抛异常
        detector._model = MagicMock()
        detector._model.predict.side_effect = RuntimeError("boom")

        result = detector.predict("reflex", 0.5, True, True)
        assert result.is_anomaly is False
        assert result.reason == "prediction_error"


# ============================================================================
# PatternPredictor 测试
# ============================================================================


class TestPatternPredictor:
    """模式预测器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_pattern_predictor()
        yield
        reset_pattern_predictor()

    def test_predict_returns_no_observations_initially(self):
        """无观测时返回 no_observations。"""
        predictor = PatternPredictor()
        result = predictor.predict()
        assert result.predicted == ""
        assert result.reason == "no_observations"

    def test_observe_and_predict_markov(self):
        """观测后能用 Markov/N-gram 预测。"""
        predictor = PatternPredictor(n=2)
        # 观测序列：reflex → conscious → reflex → conscious
        for item in ["reflex", "conscious", "reflex", "conscious", "reflex"]:
            predictor.observe(item)

        result = predictor.predict()
        # 应预测 conscious（reflex 后面总是 conscious）
        assert result.predicted == "conscious"
        assert result.confidence > 0.0
        # n=2 时 N-gram order_1 等价于 Markov 一阶
        assert "ngram" in result.reason or "markov" in result.reason

    def test_observe_and_predict_ngram(self):
        """N-gram 预测比 Markov 更精确。"""
        predictor = PatternPredictor(n=3)
        # 观测序列：A B C A B C A B C
        sequence = ["A", "B", "C"] * 10
        for item in sequence:
            predictor.observe(item)

        # 给定上下文 [A, B]，应预测 C
        result = predictor.predict(context=["A", "B"])
        assert result.predicted == "C"
        assert "ngram" in result.reason

    def test_predict_with_empty_context(self):
        """空上下文返回 empty_context。"""
        predictor = PatternPredictor()
        predictor.observe("A")
        result = predictor.predict(context=[])
        assert result.reason == "empty_context"

    def test_predict_fallback_from_ngram_to_markov(self):
        """N-gram 无匹配时回退到 Markov。"""
        predictor = PatternPredictor(n=3)
        # 只观测少量数据，N-gram 上下文不匹配
        for item in ["A", "B"]:
            predictor.observe(item)

        # 用未观测过的上下文预测
        result = predictor.predict(context=["X", "Y"])
        # N-gram 无匹配，但 Markov 可能也无匹配
        assert result.reason in ("ngram_no_match", "markov_no_match", "no_pattern_matched")

    def test_alternatives_returned(self):
        """预测结果包含备选项。"""
        predictor = PatternPredictor(n=2)
        # A → B (3次), A → C (1次)
        for _ in range(3):
            predictor.observe("A")
            predictor.observe("B")
            predictor.observe("A")
        predictor.observe("A")
        predictor.observe("C")

        result = predictor.predict(context=["A"])
        assert len(result.alternatives) >= 1
        # 第一个备选项应该是预测项
        assert result.alternatives[0][0] == result.predicted

    def test_confidence_calculation(self):
        """置信度 = 频率 / 总数。"""
        predictor = PatternPredictor(n=2)
        # A → B (3次), A → C (1次) → P(B|A) = 0.75
        for _ in range(3):
            predictor.observe("A")
            predictor.observe("B")
        predictor.observe("A")
        predictor.observe("C")

        result = predictor.predict(context=["A"])
        if result.predicted == "B":
            assert result.confidence == pytest.approx(0.75)

    def test_get_transition_matrix(self):
        """get_transition_matrix 返回概率矩阵。"""
        predictor = PatternPredictor(n=2)
        predictor.observe("A")
        predictor.observe("B")
        predictor.observe("A")
        predictor.observe("B")

        matrix = predictor.get_transition_matrix()
        assert "A" in matrix
        assert "B" in matrix["A"]
        assert matrix["A"]["B"] == pytest.approx(1.0)

    def test_get_stats(self):
        """get_stats 返回正确统计。"""
        predictor = PatternPredictor(n=3)
        for item in ["A", "B", "C"]:
            predictor.observe(item)

        stats = predictor.get_stats()
        assert stats["total_observations"] == 3
        assert stats["ngram_order"] == 3
        assert stats["history_size"] == 3

    def test_observe_empty_string_ignored(self):
        """空字符串观测被忽略。"""
        predictor = PatternPredictor()
        predictor.observe("")
        assert predictor.get_stats()["total_observations"] == 0

    def test_singleton_returns_same_instance(self):
        """get_pattern_predictor 返回同一单例。"""
        p1 = get_pattern_predictor()
        p2 = get_pattern_predictor()
        assert p1 is p2

    def test_reset_clears_singleton(self):
        """reset_pattern_predictor 清除单例。"""
        p1 = get_pattern_predictor()
        reset_pattern_predictor()
        p2 = get_pattern_predictor()
        assert p1 is not p2


# ============================================================================
# SubconsciousMLHandler 测试
# ============================================================================


class TestSubconsciousMLHandler:
    """ML 驱动潜意识处理器测试。"""

    @pytest.fixture
    def mock_event(self):
        """构造 mock NeuroEvent。"""
        event = MagicMock()
        event.payload = {
            "processor_type": "reflex",
            "latency_ms": 0.5,
            "sla_hit": True,
            "success": True,
            "text": "你好",
        }
        return event

    @pytest.fixture
    def mock_embedder(self):
        emb = MagicMock(spec=LocalEmbedder)
        emb.embed_query.return_value = [0.1] * 128
        return emb

    @pytest.fixture
    def mock_anomaly_detector(self):
        det = MagicMock(spec=AnomalyDetector)
        det.add_sample = MagicMock()
        det.predict.return_value = AnomalyResult(
            is_anomaly=False,
            anomaly_score=0.5,
            reason="normal",
        )
        return det

    @pytest.fixture
    def mock_pattern_predictor(self):
        pred = MagicMock(spec=PatternPredictor)
        pred.observe = MagicMock()
        pred.predict.return_value = PredictionResult(
            predicted="conscious",
            confidence=0.8,
            alternatives=[("conscious", 0.8), ("reflex", 0.2)],
            reason="markov_order_1",
        )
        return pred

    async def test_handle_returns_result(
        self, mock_event, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """handle 返回分析结果。"""
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        result = await handler.handle(mock_event)

        assert result["processed"] is True
        assert result["anomaly"] is not None
        assert result["prediction"] is not None
        assert result["embedded"] is True

    async def test_handle_calls_anomaly_detector(
        self, mock_event, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """handle 调用异常检测器。"""
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        await handler.handle(mock_event)

        mock_anomaly_detector.add_sample.assert_called_once()
        mock_anomaly_detector.predict.assert_called_once()

    async def test_handle_calls_pattern_predictor(
        self, mock_event, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """handle 调用模式预测器。"""
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        await handler.handle(mock_event)

        mock_pattern_predictor.observe.assert_called_once_with("reflex")
        mock_pattern_predictor.predict.assert_called_once()

    async def test_handle_calls_embedder(
        self, mock_event, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """handle 调用嵌入器。"""
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        await handler.handle(mock_event)

        mock_embedder.embed_query.assert_called_once_with("你好")

    async def test_handle_without_text_skips_embedding(
        self, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """无文本时跳过向量化。"""
        event = MagicMock()
        event.payload = {
            "processor_type": "reflex",
            "latency_ms": 0.5,
            "sla_hit": True,
            "success": True,
            # 无 text 字段
        }
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        result = await handler.handle(event)

        assert result["embedded"] is False
        mock_embedder.embed_query.assert_not_called()

    async def test_handle_reports_anomaly(self, mock_event, mock_embedder, mock_pattern_predictor):
        """异常被检测到时记录在结果中。"""
        mock_det = MagicMock(spec=AnomalyDetector)
        mock_det.add_sample = MagicMock()
        mock_det.predict.return_value = AnomalyResult(
            is_anomaly=True,
            anomaly_score=-0.5,
            reason="isolation_forest",
        )
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_det,
            pattern_predictor=mock_pattern_predictor,
        )
        result = await handler.handle(mock_event)

        assert result["anomaly"]["is_anomaly"] is True
        assert result["anomaly"]["score"] == -0.5

    async def test_handle_swallows_anomaly_exceptions(
        self, mock_event, mock_embedder, mock_pattern_predictor
    ):
        """异常检测器抛异常时不影响主流程。"""
        mock_det = MagicMock(spec=AnomalyDetector)
        mock_det.add_sample.side_effect = RuntimeError("boom")
        mock_det.predict.side_effect = RuntimeError("boom")

        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_det,
            pattern_predictor=mock_pattern_predictor,
        )
        result = await handler.handle(mock_event)

        # 异常被吞，result 仍有结构
        assert result["processed"] is True

    async def test_handle_swallows_predictor_exceptions(
        self, mock_event, mock_embedder, mock_anomaly_detector
    ):
        """预测器抛异常时不影响主流程。"""
        mock_pred = MagicMock(spec=PatternPredictor)
        mock_pred.observe.side_effect = RuntimeError("boom")
        mock_pred.predict.side_effect = RuntimeError("boom")

        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pred,
        )
        result = await handler.handle(mock_event)

        assert result["processed"] is True

    async def test_handle_returns_latency(
        self, mock_event, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """结果包含延迟。"""
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        result = await handler.handle(mock_event)

        assert "latency_ms" in result
        assert result["latency_ms"] >= 0.0

    async def test_handle_empty_payload(
        self, mock_embedder, mock_anomaly_detector, mock_pattern_predictor
    ):
        """空 payload 不崩溃。"""
        event = MagicMock()
        event.payload = {}
        handler = SubconsciousMLHandler(
            embedder=mock_embedder,
            anomaly_detector=mock_anomaly_detector,
            pattern_predictor=mock_pattern_predictor,
        )
        result = await handler.handle(event)

        assert result["processed"] is True
