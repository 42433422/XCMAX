"""Standalone vibe-coding: NL → sandbox-validated, self-healing Python skills + workflows.

This package is the standalone twin of ``eskill.vibe_coding``. It carries its
own runtime / sandbox / validator / patch-generator (in :mod:`vibe_coding.runtime`)
copied from the upstream eskill prototype, plus the natural-language layer
(``code_factory``, ``workflow_factory``, ``facade``, …) so it can be installed
and used in any project without a dependency on the ``eskill`` package.

P2 add-ons (lazy-loaded under :mod:`vibe_coding.agent`):

- :mod:`vibe_coding.agent.repo_index.adapters` — TypeScript / Vue / JSX,
  decorator-aware code understanding.
- :mod:`vibe_coding.agent.tools` — eslint / tsc / vitest / prettier
  alongside ruff / mypy / pytest.
- :mod:`vibe_coding.agent.marketplace` — bundle a skill into a ``.xcmod``
  zip and publish to a MODstore catalog.
- :mod:`vibe_coding.agent.sandbox` — WebContainer + cloud (E2B / HTTP)
  drivers in addition to subprocess + Docker.
- :mod:`vibe_coding.agent.orchestration` — Planner / Coder / Reviewer
  multi-agent coordinator with sequential and best-of-N modes.
- :mod:`vibe_coding.agent.web` — FastAPI Web UI + JSON-RPC LSP-lite for
  IDE integration.

If upstream evolves, run ``python scripts/sync_from_eskill.py`` to refresh the
generated pieces (``runtime/``, ``nl/``, the factories, ``workflow_models``).
``audit.py``, ``facade.py``, ``cli.py``, ``workflow_engine.py`` and this
``__init__`` are hand-maintained because they intentionally drop the config-
layer ``ESkillRuntime`` integration that exists upstream.
"""

from __future__ import annotations

from ._version import __version__
from .audit import PatchLedger, PatchRecord
from .code_factory import NLCodeSkillFactory, VibeCodingError
from .facade import VibeCoder
from .nl.llm import LLMClient, LLMError, MockLLM, OpenAILLM
from .nl.prompts import (
    BRIEF_FIRST_CODE_PROMPT,
    BRIEF_FIRST_SPEC_PROMPT,
    CODE_DIRECT_PROMPT,
    CODE_HUNK_REPAIR_PROMPT,
    CODE_REPAIR_PROMPT,
    MULTI_FILE_EDIT_PROMPT,
    MULTI_FILE_REPAIR_PROMPT,
    WORKFLOW_PROMPT,
)
from .workflow_conditions import ConditionError, evaluate_condition
from .workflow_engine import (
    NodeRunOutcome,
    RunOptions,
    VibeWorkflowEngine,
    WorkflowRunResult,
)
from .workflow_factory import NLWorkflowFactory, WorkflowGenerationReport
from .workflow_models import VibeWorkflowEdge, VibeWorkflowGraph, VibeWorkflowNode

_LAZY_AGENT_EXPORTS = {
    # marketplace
    "MODstoreClient": "vibe_coding.agent.marketplace",
    "PublishOptions": "vibe_coding.agent.marketplace",
    "PublishResult": "vibe_coding.agent.marketplace",
    "SkillPackager": "vibe_coding.agent.marketplace",
    "SkillPublisher": "vibe_coding.agent.marketplace",
    # multi-agent
    "BestOfNOrchestrator": "vibe_coding.agent.orchestration",
    "CoderAgent": "vibe_coding.agent.orchestration",
    "MultiAgentOrchestrator": "vibe_coding.agent.orchestration",
    "PlannerAgent": "vibe_coding.agent.orchestration",
    "ResearcherAgent": "vibe_coding.agent.orchestration",
    "ReviewerAgent": "vibe_coding.agent.orchestration",
    # web / lsp
    "LSPMessage": "vibe_coding.agent.web",
    "LSPServer": "vibe_coding.agent.web",
    "create_app": "vibe_coding.agent.web",
    "run_server": "vibe_coding.agent.web",
}


def __getattr__(name: str):
    target = _LAZY_AGENT_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'vibe_coding' has no attribute {name!r}")
    from importlib import import_module

    module = import_module(target)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(
    {
        "BRIEF_FIRST_CODE_PROMPT",
        "BRIEF_FIRST_SPEC_PROMPT",
        "CODE_DIRECT_PROMPT",
        "CODE_HUNK_REPAIR_PROMPT",
        "CODE_REPAIR_PROMPT",
        "ConditionError",
        "LLMClient",
        "LLMError",
        "MULTI_FILE_EDIT_PROMPT",
        "MULTI_FILE_REPAIR_PROMPT",
        "MockLLM",
        "NLCodeSkillFactory",
        "NLWorkflowFactory",
        "NodeRunOutcome",
        "OpenAILLM",
        "PatchLedger",
        "PatchRecord",
        "RunOptions",
        "VibeCoder",
        "VibeCodingError",
        "VibeWorkflowEdge",
        "VibeWorkflowEngine",
        "VibeWorkflowGraph",
        "VibeWorkflowNode",
        "WORKFLOW_PROMPT",
        "WorkflowGenerationReport",
        "WorkflowRunResult",
        "__version__",
        "evaluate_condition",
        *_LAZY_AGENT_EXPORTS.keys(),
    }
)
