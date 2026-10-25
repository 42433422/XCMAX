"""Compat module path: debt19 renamed ports.py → protocols.py."""

from __future__ import annotations

from app.application.knowledge.protocols import (  # noqa: F401
    AccessResolver,
    DatasetAction,
    MemoryResponse,
    RecallMerger,
    AgentRuntime,
)

__all__ = [
    "AccessResolver",
    "DatasetAction",
    "MemoryResponse",
    "RecallMerger",
    "AgentRuntime",
]
