"""统一 Agent Runtime 主链路内核。

编排 / 计费 / 记忆 / RAG 各自闭环已存在；本包把它们收口到 agent 执行主链的
固定接缝上，供 agent_orchestrator 与 employee_runtime 共用（单一 SSOT）：

1. 记忆召回注入（pre-plan）：知识库 RAG（dataset）+ 用户长期记忆
2. 计量计费（every LLM call）：统一 ``record_model_usage``（不受 hooks 开关限制）
3. 记忆回写（post-run）：短期 SQL + 长期向量，与 planner 召回同一命名空间

记忆/RAG hooks 由 ``XCAGI_AGENT_RUNTIME_HOOKS`` 灰度门控（默认关，显式 on 开启）；
计费计量始终生效。全部 best-effort：任何后端不可用都降级为空结果，绝不阻断主链路。
"""

from app.application.agent_runtime.pipeline import (
    agent_runtime_hooks_enabled,
    completion_usage,
    meter_llm_call,
    recall_knowledge_context,
    remember_run_outcome,
)

__all__ = [
    "agent_runtime_hooks_enabled",
    "completion_usage",
    "meter_llm_call",
    "recall_knowledge_context",
    "remember_run_outcome",
]
