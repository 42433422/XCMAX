"""Execute a :class:`VibeWorkflowGraph` (code-layer only).

The standalone engine runs every node through :class:`CodeSkillRuntime` —
which already provides per-node self-healing (sandbox + LLM patch + solidify).
We do not include the config-layer (``ESkillRuntime``) or ``ESkillNodeWrapper``
plumbing that exists upstream; those belong to the eskill prototype. If you
need them, use the upstream ``eskill.vibe_coding`` package instead.

P1 improvements over the initial release:

- **Conditional edges.** A non-empty ``edge.condition`` is evaluated against
  the current run context via :mod:`vibe_coding.workflow_conditions` (a
  strict expression-only sandbox). False conditions skip the downstream
  node; nodes with all incoming edges skipped are themselves skipped.
- **Per-node retries.** ``node.config["retry_count"]`` (default 0) reruns
  the node on transient failure with a small backoff.
- **Per-node timeouts.** ``node.config["timeout_s"]`` (default unlimited)
  short-circuits a hung node so the workflow as a whole stays responsive.
- **Hooks.** ``RunOptions.on_node_start`` / ``on_node_complete`` /
  ``on_node_skip`` callbacks let the caller stream progress to the UI.
- **Skip-aware reachability.** When a downstream node is unreachable
  because every path was skipped, it shows up in ``WorkflowRunResult``
  as a separate ``stage="skipped"`` outcome instead of silently being
  excluded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ._internals import TriggerPolicy
from .runtime import CodeSkillRuntime
from .workflow_conditions import ConditionError, evaluate_condition
from .workflow_models import VibeWorkflowEdge, VibeWorkflowGraph, VibeWorkflowNode


@dataclass(slots=True)
class NodeRunOutcome:
    node_id: str
    layer: str | None
    skill_id: str
    stage: str
    output: dict[str, Any]
    duration_ms: float
    error: str = ""
    patch: dict[str, Any] | None = None
    attempts: int = 1
    skipped_reason: str = ""


@dataclass(slots=True)
class WorkflowRunResult:
    workflow_id: str
    success: bool
    context: dict[str, Any] = field(default_factory=dict)
    outcomes: list[NodeRunOutcome] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0

    def output_for(self, node_id: str) -> dict[str, Any] | None:
        for o in self.outcomes:
            if o.node_id == node_id:
                return o.output
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "success": self.success,
            "context": dict(self.context),
            "outcomes": [
                {
                    "node_id": o.node_id,
                    "layer": o.layer,
                    "skill_id": o.skill_id,
                    "stage": o.stage,
                    "output": dict(o.output),
                    "duration_ms": o.duration_ms,
                    "error": o.error,
                    "patch": o.patch,
                    "attempts": o.attempts,
                    "skipped_reason": o.skipped_reason,
                }
                for o in self.outcomes
            ],
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


HookCallable = Callable[[VibeWorkflowNode, NodeRunOutcome | None, dict[str, Any]], None]


@dataclass(slots=True)
class RunOptions:
    """Optional behaviour switches for :meth:`VibeWorkflowEngine.run`.

    All hooks receive ``(node, outcome_or_none, context_snapshot)`` and may
    raise to abort the workflow (the raise propagates as an engine error).
    """

    on_node_start: HookCallable | None = None
    on_node_complete: HookCallable | None = None
    on_node_skip: HookCallable | None = None
    # Retry/timeout defaults applied when the node config doesn't override.
    default_retry_count: int = 0
    default_retry_backoff_s: float = 0.5
    default_timeout_s: float | None = None
    # When ``True`` (default) a node failure terminates the run; ``False``
    # marks the node failed but keeps executing nodes whose paths are still
    # reachable (useful for "best-effort" pipelines).
    fail_fast: bool = True


class VibeWorkflowEngine:
    """Run a :class:`VibeWorkflowGraph` produced by :class:`NLWorkflowFactory`."""

    def __init__(self, *, code_runtime: CodeSkillRuntime):
        if code_runtime is None:
            raise ValueError("code_runtime is required")
        self.code_runtime = code_runtime

    def run(
        self,
        graph: VibeWorkflowGraph,
        input_data: dict[str, Any],
        options: RunOptions | None = None,
    ) -> WorkflowRunResult:
        issues = graph.validate()
        if issues:
            return WorkflowRunResult(
                workflow_id=graph.workflow_id,
                success=False,
                error=f"graph validation failed: {issues}",
            )

        opts = options or RunOptions()
        t0 = time.perf_counter()
        context: dict[str, Any] = dict(input_data or {})
        outcomes: list[NodeRunOutcome] = []
        try:
            order = graph.topological_order()
        except ValueError as exc:
            return WorkflowRunResult(
                workflow_id=graph.workflow_id, success=False, error=str(exc)
            )

        # Track which nodes successfully executed (any outcome but skipped+error
        # counts) so condition evaluation knows which incoming edges are alive.
        executed: set[str] = set()
        skipped: set[str] = set()
        start_id = graph.start_node().node_id
        executed.add(start_id)

        run_failed_node: str | None = None
        for node in order:
            if node.node_type == "start":
                continue
            if node.node_type == "end":
                # End is informational; mark it executed if reachable.
                if self._is_node_reachable(graph, node, executed, skipped, context):
                    executed.add(node.node_id)
                continue
            reachable = self._is_node_reachable(graph, node, executed, skipped, context)
            if not reachable:
                skip_outcome = NodeRunOutcome(
                    node_id=node.node_id,
                    layer=node.layer,
                    skill_id=node.code_skill_ref or "",
                    stage="skipped",
                    output={},
                    duration_ms=0.0,
                    skipped_reason="no active incoming edge (condition false or upstream skipped)",
                )
                outcomes.append(skip_outcome)
                skipped.add(node.node_id)
                if opts.on_node_skip is not None:
                    opts.on_node_skip(node, skip_outcome, dict(context))
                continue
            if opts.on_node_start is not None:
                opts.on_node_start(node, None, dict(context))
            outcome = self._execute_with_retry(node, context, opts)
            outcomes.append(outcome)
            if opts.on_node_complete is not None:
                opts.on_node_complete(node, outcome, dict(context))
            if outcome.error:
                if opts.fail_fast:
                    return WorkflowRunResult(
                        workflow_id=graph.workflow_id,
                        success=False,
                        context=context,
                        outcomes=outcomes,
                        error=f"node {node.node_id!r} failed: {outcome.error}",
                        duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                    )
                run_failed_node = node.node_id
                skipped.add(node.node_id)
                continue
            output_var = str(node.config.get("output_var") or node.node_id)
            context[output_var] = outcome.output
            executed.add(node.node_id)

        return WorkflowRunResult(
            workflow_id=graph.workflow_id,
            success=run_failed_node is None,
            context=context,
            outcomes=outcomes,
            error=(
                f"node {run_failed_node!r} failed (continued past)"
                if run_failed_node is not None
                else ""
            ),
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )

    # ------------------------------------------------------------- traversal

    def _is_node_reachable(
        self,
        graph: VibeWorkflowGraph,
        node: VibeWorkflowNode,
        executed: set[str],
        skipped: set[str],
        context: dict[str, Any],
    ) -> bool:
        """A node is reachable if at least one incoming edge is *active*.

        An edge ``A -> B`` is active when:
        - ``A`` has been executed (not skipped, not pending), and
        - the edge condition (if any) evaluates truthy in the context.
        """
        incoming = [e for e in graph.edges if e.target_node_id == node.node_id]
        if not incoming:
            # No predecessors → only legitimate for the start node.
            return node.node_type == "start"
        for edge in incoming:
            if edge.source_node_id not in executed:
                continue
            if self._edge_active(edge, context):
                return True
        return False

    @staticmethod
    def _edge_active(edge: VibeWorkflowEdge, context: dict[str, Any]) -> bool:
        condition = (edge.condition or "").strip()
        if not condition:
            return True
        try:
            return evaluate_condition(condition, context)
        except ConditionError:
            # A bad condition silently disables the edge — surfacing it as
            # an exception would block the entire workflow on one typo.
            return False

    # ------------------------------------------------------------- retry/timeout

    def _execute_with_retry(
        self,
        node: VibeWorkflowNode,
        context: dict[str, Any],
        opts: RunOptions,
    ) -> NodeRunOutcome:
        retry_count = max(0, int(node.config.get("retry_count", opts.default_retry_count)))
        backoff = float(node.config.get("retry_backoff_s", opts.default_retry_backoff_s))
        timeout = node.config.get("timeout_s", opts.default_timeout_s)
        attempt = 0
        last_outcome: NodeRunOutcome | None = None
        while attempt <= retry_count:
            attempt += 1
            outcome = self._execute_node(node, context, timeout_s=timeout)
            outcome.attempts = attempt
            last_outcome = outcome
            if not outcome.error:
                return outcome
            if attempt > retry_count:
                break
            if backoff > 0:
                time.sleep(min(backoff * attempt, 5.0))
        assert last_outcome is not None
        return last_outcome

    def _execute_node(
        self,
        node: VibeWorkflowNode,
        context: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> NodeRunOutcome:
        if node.layer != "code":
            return NodeRunOutcome(
                node_id=node.node_id,
                layer=node.layer,
                skill_id="",
                stage="invalid",
                output={},
                duration_ms=0.0,
                error=(
                    f"unsupported node layer {node.layer!r} — standalone vibe_coding "
                    "supports layer='code' only"
                ),
            )
        skill_id = node.code_skill_ref or ""
        if not skill_id:
            return NodeRunOutcome(
                node_id=node.node_id,
                layer="code",
                skill_id="",
                stage="missing_skill",
                output={},
                duration_ms=0.0,
                error="code_skill_ref is empty",
            )
        input_data = self._build_input(node, context)
        t0 = time.perf_counter()
        try:
            cr = _call_with_timeout(
                lambda: self.code_runtime.run(
                    skill_id,
                    input_data,
                    force_dynamic=bool(node.config.get("force_dynamic", False)),
                    solidify=bool(node.config.get("solidify", True)),
                    trigger_policy=_to_trigger_policy(node.config.get("trigger_policy")),
                    quality_gate=node.config.get("quality_gate") or None,
                ),
                timeout_s=timeout_s,
            )
        except _NodeTimeout as exc:
            return NodeRunOutcome(
                node_id=node.node_id,
                layer="code",
                skill_id=skill_id,
                stage="timeout",
                output={},
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return NodeRunOutcome(
                node_id=node.node_id,
                layer="code",
                skill_id=skill_id,
                stage="exception",
                output={},
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                error=str(exc),
            )
        return NodeRunOutcome(
            node_id=node.node_id,
            layer="code",
            skill_id=skill_id,
            stage=cr.stage,
            output=dict(cr.output_data) if cr.output_data else {},
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            error=cr.error or "",
            patch=cr.patch.to_dict() if cr.patch else None,
        )

    def _build_input(self, node: VibeWorkflowNode, context: dict[str, Any]) -> dict[str, Any]:
        input_mapping = node.config.get("input_mapping")
        if isinstance(input_mapping, dict) and input_mapping:
            return {str(k): _resolve_ref(ref, context) for k, ref in input_mapping.items()}
        return dict(context)


def _resolve_ref(ref: Any, context: dict[str, Any]) -> Any:
    """Same dotted-path resolver as the upstream engine."""
    if not isinstance(ref, str):
        return ref
    if "." not in ref:
        return context[ref] if ref in context else ref
    parts = ref.split(".")
    head = parts[0]
    if head not in context:
        return ref
    cursor: Any = context[head]
    for part in parts[1:]:
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return ref
    return cursor


def _to_trigger_policy(raw: Any) -> TriggerPolicy | None:
    if raw is None:
        return None
    if isinstance(raw, TriggerPolicy):
        return raw
    if isinstance(raw, dict):
        return TriggerPolicy.from_dict(raw)
    return None


class _NodeTimeout(TimeoutError):
    """Raised internally when a node exceeds its per-node timeout."""


def _call_with_timeout(fn: Callable[[], Any], *, timeout_s: float | None) -> Any:
    """Run ``fn()`` and raise :class:`_NodeTimeout` if it exceeds ``timeout_s``.

    Implementation note: we use a ``threading.Thread`` rather than
    ``signal.alarm`` so the helper works on Windows and inside non-main
    threads (notebooks, web servers). The thread is left as daemon so it
    does not block interpreter shutdown if the inner call truly hangs.
    """
    if timeout_s is None or float(timeout_s) <= 0:
        return fn()
    import threading

    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(float(timeout_s))
    if thread.is_alive():
        raise _NodeTimeout(f"node exceeded timeout_s={timeout_s}")
    if "error" in box:
        raise box["error"]
    return box.get("result")
