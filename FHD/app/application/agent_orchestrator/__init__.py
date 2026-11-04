"""Public orchestration records and services, loaded on demand.

A tool subprocess must not initialize the orchestration and approval runtimes
just to import its bounded executor. Concrete submodules remain the owners."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.application.agent_orchestrator.orchestrator import (
        AgentOrchestrator as AgentOrchestrator,
    )
    from app.application.agent_orchestrator.run_models import (
        AgentArtifact as AgentArtifact,
        AgentRun as AgentRun,
        AgentStep as AgentStep,
        AgentStepStatus as AgentStepStatus,
        LLMCall as LLMCall,
        LLMCallStatus as LLMCallStatus,
        MemoryReference as MemoryReference,
        MemoryReferenceStatus as MemoryReferenceStatus,
        RetrievalCall as RetrievalCall,
        RetrievalCallStatus as RetrievalCallStatus,
        RunEvent as RunEvent,
        RunStatus as RunStatus,
        ToolCall as ToolCall,
        ToolCallStatus as ToolCallStatus,
    )
    from app.application.agent_orchestrator.run_repository import (
        AgentRunRepository as AgentRunRepository,
        InMemoryAgentRunRepository as InMemoryAgentRunRepository,
        SQLAlchemyAgentRunRepository as SQLAlchemyAgentRunRepository,
        get_agent_run_repository as get_agent_run_repository,
        get_agent_run_repository_status as get_agent_run_repository_status,
        set_agent_run_repository_for_tests as set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_models import (
        AgentTask as AgentTask,
        TaskControlCommand as TaskControlCommand,
    )
    from app.application.agent_orchestrator.tool_spec import (
        ToolActionSpecV2 as ToolActionSpecV2,
        ToolValidationResult as ToolValidationResult,
        build_tool_specs_v2 as build_tool_specs_v2,
        get_tool_action_spec as get_tool_action_spec,
        validate_tool_call as validate_tool_call,
    )
_SERVICE_EXPORTS: dict[str, str] = {
    "AgentOrchestrator": "orchestrator",
    "AgentArtifact": "run_models",
    "AgentRun": "run_models",
    "AgentStep": "run_models",
    "AgentStepStatus": "run_models",
    "LLMCall": "run_models",
    "LLMCallStatus": "run_models",
    "MemoryReference": "run_models",
    "MemoryReferenceStatus": "run_models",
    "RetrievalCall": "run_models",
    "RetrievalCallStatus": "run_models",
    "RunEvent": "run_models",
    "RunStatus": "run_models",
    "ToolCall": "run_models",
    "ToolCallStatus": "run_models",
    "AgentRunRepository": "run_repository",
    "InMemoryAgentRunRepository": "run_repository",
    "SQLAlchemyAgentRunRepository": "run_repository",
    "get_agent_run_repository": "run_repository",
    "get_agent_run_repository_status": "run_repository",
    "set_agent_run_repository_for_tests": "run_repository",
    "AgentTask": "task_models",
    "TaskControlCommand": "task_models",
    "ToolActionSpecV2": "tool_spec",
    "ToolValidationResult": "tool_spec",
    "build_tool_specs_v2": "tool_spec",
    "get_tool_action_spec": "tool_spec",
    "validate_tool_call": "tool_spec",
}
_MODULE_EXPORTS = frozenset(_SERVICE_EXPORTS.values())
__all__ = [
    "AgentOrchestrator",
    "AgentArtifact",
    "AgentRun",
    "AgentRunRepository",
    "AgentTask",
    "AgentStep",
    "AgentStepStatus",
    "InMemoryAgentRunRepository",
    "LLMCall",
    "LLMCallStatus",
    "MemoryReference",
    "MemoryReferenceStatus",
    "RetrievalCall",
    "RetrievalCallStatus",
    "RunEvent",
    "RunStatus",
    "SQLAlchemyAgentRunRepository",
    "ToolActionSpecV2",
    "ToolCall",
    "ToolCallStatus",
    "TaskControlCommand",
    "ToolValidationResult",
    "build_tool_specs_v2",
    "get_agent_run_repository",
    "get_agent_run_repository_status",
    "set_agent_run_repository_for_tests",
    "get_tool_action_spec",
    "validate_tool_call",
]


def __getattr__(name: str) -> Any:
    module = _SERVICE_EXPORTS.get(name)
    if module is not None:
        return getattr(import_module(f"{__name__}.{module}"), name)
    if name in _MODULE_EXPORTS:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SERVICE_EXPORTS.keys() | _MODULE_EXPORTS)
