"""认知层（Cognition Layer）—— Conscious 处理器的 LLM + 因果/技能/软约束能力。

Phase 2 组件：
- ``LLMPort`` / ``WorkingMemory`` / ``AttentionSelector`` / ``ConsciousLLMHandler``
全栈补齐（2026-07）：
- ``CausalGraph`` + ``CounterfactualProbe``：可干预因果（非纯相关检索）
- ``SkillRouter``：开放世界技能契约（封闭意图仅 bootstrap）
- ``SoftConstraints`` + ``plan_graph_log``：阈值软约束与多步 PlanGraph 落盘
- ``CognitiveOrchestrator``：串起必要能力（惰性导出，避免启动循环导入）
"""

from __future__ import annotations

from typing import Any

from app.domain.neuro.cognition.attention_selector import AttentionResult, AttentionSelector
from app.domain.neuro.cognition.causal_graph import (
    CausalGraph,
    explain_relatedness,
    get_order_fulfillment_graph,
)
from app.domain.neuro.cognition.conscious_llm_handler import ConsciousLLMHandler
from app.domain.neuro.cognition.counterfactual import CounterfactualProbe, probe_counterfactual
from app.domain.neuro.cognition.llm_port import LLMPort, get_llm_port, reset_llm_port
from app.domain.neuro.cognition.plan_constraints import (
    SoftConstraints,
    select_processor_by_cost,
)
from app.domain.neuro.cognition.skill_contract import SkillRouter, get_skill_router
from app.domain.neuro.cognition.working_memory import (
    WorkingMemory,
    get_working_memory,
    reset_working_memory,
)

__all__ = [
    "LLMPort",
    "get_llm_port",
    "reset_llm_port",
    "WorkingMemory",
    "get_working_memory",
    "reset_working_memory",
    "AttentionSelector",
    "AttentionResult",
    "ConsciousLLMHandler",
    "CausalGraph",
    "get_order_fulfillment_graph",
    "explain_relatedness",
    "CounterfactualProbe",
    "probe_counterfactual",
    "SkillRouter",
    "get_skill_router",
    "SoftConstraints",
    "select_processor_by_cost",
    "CognitiveOrchestrator",
    "get_cognitive_orchestrator",
    "reset_cognitive_orchestrator",
]


def __getattr__(name: str) -> Any:
    # 惰性导出编排器，避免 token_estimator → cognition 包导入时拉起 evolution 环。
    if name in {
        "CognitiveOrchestrator",
        "get_cognitive_orchestrator",
        "reset_cognitive_orchestrator",
    }:
        from app.domain.neuro.cognition import cognitive_orchestrator as _orch

        return getattr(_orch, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
