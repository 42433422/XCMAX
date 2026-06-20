"""潜意识 ML 层（Subconscious ML Layer）——Subconscious 处理器的 ML 能力升级。

Phase 3 组件：
- ``LocalEmbedder``：本地嵌入器，基于 ``HashEmbedder`` + LRU 缓存，无外部依赖。
- ``AnomalyDetector``：异常检测器，基于 ``sklearn.IsolationForest``，检测路由/延迟/错误异常。
- ``PatternPredictor``：模式预测器，基于 N-gram + Markov 链，预测下一事件/处理器。
- ``SubconsciousMLHandler``：ML 驱动的潜意识处理器，整合上述三者。

设计约束：
- SLA < 10ms：所有推理操作必须在 10ms 内完成（训练/拟合异步后台进行）。
- 无重依赖：不使用 sentence-transformers / torch（仅 numpy + scikit-learn，已在 server-api 中）。
- best-effort：任何 ML 组件不可用时降级为空结果，不阻断 Subconscious 处理。
- 增量学习：AnomalyDetector 和 PatternPredictor 支持在线增量更新。
"""

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

__all__ = [
    "LocalEmbedder",
    "get_local_embedder",
    "reset_local_embedder",
    "AnomalyDetector",
    "AnomalyResult",
    "get_anomaly_detector",
    "reset_anomaly_detector",
    "PatternPredictor",
    "PredictionResult",
    "get_pattern_predictor",
    "reset_pattern_predictor",
    "SubconsciousMLHandler",
]
