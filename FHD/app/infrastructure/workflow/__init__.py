"""Workflow infrastructure adapters — LangGraph runtime / checkpoint / NeuroBus event bridge.

LG-W1 系列：仅此处允许 import ``app.neuro_bus.*`` 与 vendored ``langgraph.*``（§7 门禁豁免）。

- ``XCAGILangGraphRuntime``：自包含 vendored ``StateGraph`` 执行器。
- ``assert_vendored_sources``：fail-closed 校验 LangGraph 各模块解析到 vendored packages。
- ``LanggraphCheckpointBridge``：LangGraph checkpoint 桥接适配器。
- ``LegacyEngineAdapter``：把 legacy ``WorkflowEngine`` 暴露为 ``WorkflowRuntime`` port。
"""

from __future__ import annotations

from .checkpoint_bridge import LanggraphCheckpointBridge
from .langgraph_assert import assert_vendored_sources
from .langgraph_runtime import XCAGILangGraphRuntime
from app.legacy.workflow.legacy_engine_adapter import LegacyEngineAdapter

__all__ = [
    "LanggraphCheckpointBridge",
    "XCAGILangGraphRuntime",
    "LegacyEngineAdapter",
    "assert_vendored_sources",
]
