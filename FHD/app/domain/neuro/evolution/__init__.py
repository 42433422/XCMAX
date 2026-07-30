"""自进化层（Evolution Layer）——Neuro-DDD 的运行时自进化能力。

Phase 4 组件 + 全栈补齐：
- ``KBRetriever`` / ``ReflexPatternMiner`` / ``RuntimeSelfFix`` / ``EvolutionHandler``
- ``SelfReflectionEngine``：白名单反思（critique→shadow→canary→promote）
- ``learning_feedback``：用户纠错/任务成败/SLA → 策略学习通道（不在线改分类器）
"""

from app.domain.neuro.evolution.evolution_handler import (
    EvolutionHandler,
    get_evolution_handler,
    reset_evolution_handler,
)
from app.domain.neuro.evolution.kb_retriever import (
    KBRetriever,
    KBSearchResult,
    get_kb_retriever,
    reset_kb_retriever,
)
from app.domain.neuro.evolution.learning_feedback import (
    FeedbackEvent,
    record_learning_feedback,
    record_task_outcome,
    record_user_correction,
)
from app.domain.neuro.evolution.reflex_pattern_miner import (
    MinedPattern,
    ReflexPatternMiner,
    get_reflex_pattern_miner,
    reset_reflex_pattern_miner,
)
from app.domain.neuro.evolution.runtime_self_fix import (
    FixProposal,
    RuntimeSelfFix,
    get_runtime_self_fix,
    reset_runtime_self_fix,
)
from app.domain.neuro.evolution.self_reflection import (
    REFLECT_DENYLIST,
    REFLECT_WHITELIST,
    SelfReflectionEngine,
    get_self_reflection_engine,
    reset_self_reflection_engine,
)

__all__ = [
    "KBRetriever",
    "KBSearchResult",
    "get_kb_retriever",
    "reset_kb_retriever",
    "MinedPattern",
    "ReflexPatternMiner",
    "get_reflex_pattern_miner",
    "reset_reflex_pattern_miner",
    "FixProposal",
    "RuntimeSelfFix",
    "get_runtime_self_fix",
    "reset_runtime_self_fix",
    "EvolutionHandler",
    "get_evolution_handler",
    "reset_evolution_handler",
    "SelfReflectionEngine",
    "get_self_reflection_engine",
    "reset_self_reflection_engine",
    "REFLECT_WHITELIST",
    "REFLECT_DENYLIST",
    "FeedbackEvent",
    "record_learning_feedback",
    "record_user_correction",
    "record_task_outcome",
]
