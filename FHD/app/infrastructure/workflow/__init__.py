"""Workflow infrastructure adapters — LangGraph runtime / checkpoint / NeuroBus event bridge.

LG-W1 系列：仅此处允许 import ``app.neuro_bus.*`` 与 vendored ``langgraph.*``（§7 门禁豁免）。

- ``XCAGILangGraphRuntime``：自包含 vendored ``StateGraph`` 执行器。
- ``assert_vendored_sources``：fail-closed 校验 LangGraph 各模块解析到 vendored packages。
- ``LanggraphCheckpointBridge``：LangGraph checkpoint 桥接适配器。
"""

from __future__ import annotations

from .checkpoint_bridge import LanggraphCheckpointBridge
from .langgraph_assert import assert_vendored_sources
from .langgraph_runtime import XCAGILangGraphRuntime

__all__ = [
    "LanggraphCheckpointBridge",
    "XCAGILangGraphRuntime",
    "assert_vendored_sources",
]
