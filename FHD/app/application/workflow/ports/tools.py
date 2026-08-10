"""ToolDispatcher port — contract for business tool dispatch.

The application workflow layer must never import ``app.infrastructure``,
``app.neuro_bus``, ``langgraph``, ``sqlalchemy``, or ``fastapi`` directly.
Instead it depends on this port, which is implemented by an infrastructure
adapter (e.g. the tool dispatcher used by the legacy ``WorkflowEngine`` or the
``ToolNode``-backed dispatcher of the LangGraph runtime).

A dispatcher receives a ``tool_id`` + ``action`` pair with a params dict and
returns a result dict. ``success`` in the result drives retry/error decisions;
see ``NodeExecutionResult`` in ``app/application/workflow/types.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolCall(Protocol):
    """A single tool invocation intent (tool_id + action + params)."""

    tool_id: str
    action: str
    params: dict[str, Any]


@runtime_checkable
class ToolResult(Protocol):
    """A tool invocation result. ``success`` is the only guaranteed field."""

    success: bool
    output: dict[str, Any]


@runtime_checkable
class ToolDispatcher(Protocol):
    """Dispatcher that resolves a tool action and executes it.

    ``_runtime_context`` is injected into ``params`` by the engine so the tool
    can access the current workflow runtime context.
    """

    def __call__(self, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch ``tool_id.action`` with ``params`` and return the result dict."""
        ...