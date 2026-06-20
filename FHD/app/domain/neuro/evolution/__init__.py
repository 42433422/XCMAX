"""自进化层（Evolution Layer）——Neuro-DDD 的运行时自进化能力。

Phase 4 组件：
- ``KBRetriever``：知识库检索器，基于 ``LocalEmbedder`` 检索 ``kb/patterns/`` 和 ``kb/fixes/``。
- ``ReflexPatternMiner``：反射模式挖掘器，从 ``routing_decisions.jsonl`` 挖掘新反射规则。
- ``RuntimeSelfFix``：运行时自修复，错误发生时检索 KB 并应用简单修复。
- ``EvolutionHandler``：进化处理器，整合上述三者。

设计原则：
1. 运行时而非开发时——所有组件在 FHD 运行时工作，不依赖 MODstore 开发时循环。
2. 增量学习——KBRetriever 支持增量索引，ReflexPatternMiner 支持在线挖掘。
3. 安全优先——RuntimeSelfFix 只应用低风险修复（配置/参数/重试策略），不修改代码。
4. best-effort——任何组件不可用时降级，不阻断主流程。
"""

from app.domain.neuro.evolution.evolution_handler import EvolutionHandler
from app.domain.neuro.evolution.kb_retriever import (
    KBRetriever,
    KBSearchResult,
    get_kb_retriever,
    reset_kb_retriever,
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
]
