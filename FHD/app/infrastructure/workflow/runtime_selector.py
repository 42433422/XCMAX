"""Runtime selector — LG-W1-T7 gray-release gate.

This infrastructure adapter composes the two ``WorkflowRuntime`` ports — the
legacy ``LegacyEngineAdapter`` and the ``XCAGILangGraphRuntime`` — and selects
between them from the ``XCAGI_LG_RUNTIME`` feature flag
(``app.contexts.flags.lg_runtime_mode``).

- ``build_runtime_pair`` injects a single set of wiring (dispatcher / state
  publisher / callback / schema / existing legacy engine) into both runtimes.
- ``resolve_runtime`` picks one from ``lg_runtime_mode``: ``legacy`` → the
  ``LegacyEngineAdapter``, ``primary`` → ``XCAGILangGraphRuntime``.

At this T7 boundary ``shadow``/``canary`` are **fail closed**: they raise a
clear ``RuntimeError`` (the ShadowCanaryRouter in T8 is required) and are never
mapped to ``primary``.

Construction is always allowed even without a dispatcher: an explicit
``_UnwiredDispatcher`` is wired so the runtimes can be built, but any attempt to
execute a tool fails loudly instead of silently no-oping.

Dependency direction (DDD): ``infrastructure → ports``. This module never
imports ``routes``, ``fastapi``, ``sqlalchemy``, ``app.neuro_bus``, or the
vendored ``langgraph`` packages directly.
"""

from __future__ import annotations

from typing import Any

from app.application.workflow.ports.events import StateEventPublisher
from app.application.workflow.ports.runtime import Callback, StateSchema, WorkflowRuntime
from app.application.workflow.ports.tools import ToolDispatcher
from app.contexts.flags import lg_runtime_mode
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime
from app.infrastructure.workflow.legacy_engine_adapter import LegacyEngineAdapter


class _UnwiredDispatcher:
    """Explicit unwired dispatcher: allows construction but fails loudly on execution.

    Wired when no ``tool_dispatcher`` is injected so both runtimes can still be
    constructed (composition-root-friendly). Any tool execution raises instead
    of silently returning a fabricated result — a misconfigured runtime must
    never look like it ran successfully.
    """

    def __call__(self, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(
            f"runtime selector: 未注入 tool_dispatcher，无法执行工具 {tool_id}.{action}"
        )


def build_runtime_pair(
    *,
    tool_dispatcher: ToolDispatcher | None = None,
    state_event_publisher: StateEventPublisher | None = None,
    state_event_callback: Callback | None = None,
    state_schema: StateSchema | None = None,
    legacy_engine: Any | None = None,
) -> tuple[LegacyEngineAdapter, XCAGILangGraphRuntime]:
    """Build the (legacy, langgraph) runtime pair from a single wiring source.

    All arguments are optional. ``tool_dispatcher`` is shared by both runtimes;
    when omitted, an explicit unwired dispatcher is used so construction always
    succeeds but execution fails loudly. ``state_event_publisher`` and
    ``state_schema`` apply to the LangGraph runtime; ``state_event_callback``
    applies to a legacy engine built from ``tool_dispatcher`` (or is ignored when
    ``legacy_engine`` is injected, matching ``LegacyEngineAdapter`` semantics).
    """
    dispatcher: ToolDispatcher = (
        tool_dispatcher if tool_dispatcher is not None else _UnwiredDispatcher()
    )
    legacy = LegacyEngineAdapter(
        engine=legacy_engine,
        tool_dispatcher=None if legacy_engine is not None else dispatcher,
        state_event_callback=state_event_callback,
    )
    langgraph = XCAGILangGraphRuntime(
        tool_dispatcher=dispatcher,
        state_event_publisher=state_event_publisher,
        state_schema=state_schema,
    )
    return legacy, langgraph


def resolve_runtime(
    runtime_pair: tuple[LegacyEngineAdapter, XCAGILangGraphRuntime] | None = None,
) -> WorkflowRuntime:
    """Select the active ``WorkflowRuntime`` from ``lg_runtime_mode``.

    ``legacy`` → ``LegacyEngineAdapter``; ``primary`` → ``XCAGILangGraphRuntime``.
    ``shadow``/``canary`` raise ``RuntimeError`` (T7 fail-closed boundary); they
    are never routed to ``primary``. When ``runtime_pair`` is omitted a default
    pair is built (with an unwired dispatcher) before selecting.
    """
    if runtime_pair is None:
        runtime_pair = build_runtime_pair()
    legacy, langgraph = runtime_pair
    mode = lg_runtime_mode()
    if mode == "legacy":
        return legacy
    if mode == "primary":
        return langgraph
    # mode is one of shadow/canary (validated by lg_runtime_mode).
    raise RuntimeError(
        f"runtime selector: 运行时模式 {mode!r} 需要 ShadowCanaryRouter（LG-W1-T8）才能启用；"
        "当前 T7 边界 fail-closed，不会回退到 primary"
    )
