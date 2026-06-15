"""Project-aware coding agent on top of vibe-coding's single-skill core.

This subpackage adds the eight headline capabilities that turn ``vibe_coding``
from a "NL → single sandbox-validated function" generator into a project-aware
coding agent.

Concrete entry points are re-exported lazily so importing this subpackage
costs nothing for users who only need a subset (e.g. ``RepoIndex`` without the
sandbox driver). Use ``from vibe_coding.agent import RepoIndex`` for the
common case, or import the submodule directly for fine-grained control.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Eagerly imported because they have no extra dependencies and form the public
# surface most agent callers reach for first.
from .repo_index import (
    FileEntry,
    LanguageAdapter,
    PythonLanguageAdapter,
    Reference,
    RepoIndex,
    Symbol,
    build_index,
)

_LAZY = {
    "AgentContext": "vibe_coding.agent.context",
    "ApplyResult": "vibe_coding.agent.patch",
    "DomainViolation": "vibe_coding.agent.domain",
    "FileEdit": "vibe_coding.agent.patch",
    "Hunk": "vibe_coding.agent.patch",
    "PatchApplier": "vibe_coding.agent.patch",
    "PatchConflict": "vibe_coding.agent.patch",
    "ProjectDomainGuard": "vibe_coding.agent.domain",
    "ProjectPatch": "vibe_coding.agent.patch",
    "minimise_diff": "vibe_coding.agent.patch",
    "SandboxDriver": "vibe_coding.agent.sandbox",
    "SandboxJob": "vibe_coding.agent.sandbox",
    "SandboxPolicy": "vibe_coding.agent.sandbox",
    "SandboxResult": "vibe_coding.agent.sandbox",
    "SubprocessSandboxDriver": "vibe_coding.agent.sandbox",
    "create_default_driver": "vibe_coding.agent.sandbox",
    "MODstoreClient": "vibe_coding.agent.marketplace",
    "PublishOptions": "vibe_coding.agent.marketplace",
    "PublishResult": "vibe_coding.agent.marketplace",
    "SkillPackager": "vibe_coding.agent.marketplace",
    "SkillPublisher": "vibe_coding.agent.marketplace",
    "AgentRunResult": "vibe_coding.agent.react",
    "AgentStep": "vibe_coding.agent.react",
    "ReActAgent": "vibe_coding.agent.react",
    "Tool": "vibe_coding.agent.react",
    "ToolRegistry": "vibe_coding.agent.react",
    "ToolResult": "vibe_coding.agent.react",
    "builtin_tools": "vibe_coding.agent.react",
    "tool": "vibe_coding.agent.react",
    "GlobalKnowledgeBase": "vibe_coding.agent.memory",
    "HashingEmbedder": "vibe_coding.agent.memory",
    "OpenAIEmbedder": "vibe_coding.agent.memory",
    "AdvancedWorkflow": "vibe_coding.agent.workflow_advanced",
    "AdvancedWorkflowExecutor": "vibe_coding.agent.workflow_advanced",
    "AsyncWorkflowExecutor": "vibe_coding.agent.workflow_advanced",
    "AdvancedNode": "vibe_coding.agent.workflow_advanced",
    "ParallelGroup": "vibe_coding.agent.workflow_advanced",
    "DynamicSpawn": "vibe_coding.agent.workflow_advanced",
    "TriggerSpec": "vibe_coding.agent.workflow_advanced",
    "EventBus": "vibe_coding.agent.workflow_advanced",
    "AgentObservability": "vibe_coding.agent.observability",
    "MetricsRegistry": "vibe_coding.agent.observability",
    "StructuredLogger": "vibe_coding.agent.observability",
    "Tracer": "vibe_coding.agent.observability",
    "instrument": "vibe_coding.agent.observability",
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'vibe_coding.agent' has no attribute {name!r}")
    module = import_module(target)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(
    {
        "FileEntry",
        "LanguageAdapter",
        "PythonLanguageAdapter",
        "Reference",
        "RepoIndex",
        "Symbol",
        "build_index",
        *_LAZY.keys(),
    }
)
