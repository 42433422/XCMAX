"""Compose workflow scheduling, tool execution, state and model decisions."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services import get_ai_conversation_service

from .agent_loop import run_agentic_loop
from .engine_checkpoints import replay, restore, save_progress
from .engine_decisions import AgentDecisionClient
from .engine_execution import (
    NodeExecutor,
    ToolDispatcher,
    agentic_tool_allows_auto_retry,
    attempt_summary,
    elapsed_ms,
    has_non_empty_param,
    merge_runtime_fallback_params,
    node_allows_auto_retry,
    recovery_hint,
    run_clarify_node,
)
from .engine_scheduling import (
    DagScheduler,
    branch_candidates,
    condition_matches,
    evaluate_branch,
    fail_run,
    routing_state,
)
from .engine_state import (
    StateEventCallback,
    StateEvents,
    append_node_trace,
    merge_state_schema,
    record_result,
    summarize_output,
)
from .ports import CheckpointStore
from .workflow_types import NodeExecutionResult, PlanGraph, StateSchema, WorkflowNode, WorkflowRunResult

logger = logging.getLogger(__name__)

DEFAULT_STATE_SCHEMA = (
    StateSchema()
    .declare("node_outputs", type=dict, merge="set")
    .declare("workflow_status", type=dict, merge="set")
    .declare("workflow_trace", type=list, merge="append")
    .declare("message", type=str, merge="set")
    .declare("agent_history", type=list, merge="append")
)

_sync_http_client: httpx.Client | None = None


def _get_sync_http_client() -> httpx.Client:
    global _sync_http_client
    if _sync_http_client is None:
        _sync_http_client = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _sync_http_client


def close_sync_http_client() -> None:
    """Close the reusable workflow HTTP client during application shutdown."""
    global _sync_http_client
    client = _sync_http_client
    _sync_http_client = None
    if client is not None and not client.is_closed:
        client.close()


class WorkflowEngine:
    def __init__(
        self,
        tool_dispatcher: ToolDispatcher,
        state_event_callback: StateEventCallback | None = None,
    ) -> None:
        self._dispatch = tool_dispatcher
        self._default_state_schema = DEFAULT_STATE_SCHEMA
        self._state_event_callback = state_event_callback
        self._state_events = StateEvents()

    def run(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        max_retries: int = 1,
        agentic_loop: bool = False,
        tool_registry: dict[str, Any] | None = None,
        user_id: str | None = None,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
        checkpointer: CheckpointStore | None = None,
        state_event_callback: StateEventCallback | None = None,
    ) -> WorkflowRunResult:
        with self._state_events.scope(state_event_callback):
            if agentic_loop and tool_registry:
                return self._run_agentic_loop(
                    plan, runtime_context, max_retries, tool_registry, user_id, state_schema
                )
            return self._run_batch(
                plan,
                runtime_context,
                max_retries,
                state_schema,
                parallel,
                checkpointer=checkpointer,
            )

    def _run_batch(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        max_retries: int = 1,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
        checkpointer: CheckpointStore | None = None,
        resume_state: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        # Resolve hooks at invocation time for adapters and patched/subclassed engines.
        scheduler = DagScheduler(
            self._run_node, self._record_state, self._default_state_schema, self._routing_state
        )
        return scheduler.run(
            plan, runtime_context, max_retries, state_schema, parallel, checkpointer, resume_state
        )

    def resume_run(
        self,
        plan: PlanGraph,
        checkpoint_id: str,
        *,
        checkpointer: CheckpointStore | None,
        max_retries: int = 1,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
    ) -> WorkflowRunResult:
        """Restore progress and execute only unfinished nodes, using the current callback scope."""
        state = restore(plan, checkpoint_id, checkpointer)
        if isinstance(state, WorkflowRunResult):
            return state
        return self._run_batch(
            plan,
            max_retries=max_retries,
            state_schema=state_schema,
            parallel=parallel,
            checkpointer=checkpointer,
            resume_state=state,
        )

    def replay_run(
        self,
        plan_id: str,
        checkpoint_id: str | None = None,
        *,
        checkpointer: CheckpointStore | None,
    ) -> WorkflowRunResult:
        """Read recorded results without dispatching tools or publishing state events."""
        return replay(plan_id, checkpoint_id, checkpointer=checkpointer)

    def _run_node(
        self, node: WorkflowNode, runtime_context: dict[str, Any], max_retries: int = 1
    ) -> NodeExecutionResult:
        if node.tool_id == "clarify":
            return self._run_clarify_node(node, runtime_context)

        def prepare_params() -> dict[str, Any]:
            params = dict(node.params or {})
            params["_runtime_context"] = runtime_context
            self._merge_runtime_fallback_params(node, params, runtime_context)
            return params

        return NodeExecutor(self._dispatch).execute(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=node.action,
            params=node.params,
            prepare_params=prepare_params,
            max_retries=max_retries,
            retryable=self._node_allows_auto_retry(node),
        )

    def _run_single_tool(
        self,
        tool_id: str,
        action: str,
        params: dict[str, Any],
        runtime_context: dict[str, Any],
        max_retries: int,
        retryable: bool = True,
    ) -> NodeExecutionResult:
        # Agentic calls intentionally reuse merged params across retries and do not
        # apply DAG query fallback or the synthetic clarification node policy.
        merged_params = dict(params or {})
        merged_params["_runtime_context"] = runtime_context
        return NodeExecutor(self._dispatch).execute(
            node_id=f"agent_{tool_id}_{action}",
            tool_id=tool_id,
            action=action,
            params=params,
            prepare_params=lambda: merged_params,
            max_retries=max_retries,
            retryable=retryable,
        )

    def _run_agentic_loop(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None,
        max_retries: int,
        tool_registry: dict[str, Any],
        user_id: str | None,
        state_schema: StateSchema | None = None,
    ) -> WorkflowRunResult:
        return run_agentic_loop(
            self, logger, plan, runtime_context, max_retries, tool_registry, user_id, state_schema
        )

    def _llm_decide_next_step(
        self,
        user_message: str,
        tool_registry: dict[str, Any],
        runtime_context: dict[str, Any],
        agent_history: list[dict[str, Any]],
        user_id: str | None,
    ) -> dict[str, Any] | None:
        # Keep the public factories late-bound, including on already-created engines.
        return AgentDecisionClient(
            get_ai_conversation_service, _get_sync_http_client, logger
        ).decide(user_message, tool_registry, runtime_context, agent_history, user_id)

    def _record_state(
        self, result: NodeExecutionResult, runtime_context: dict[str, Any], schema: StateSchema
    ) -> None:
        record_result(
            result,
            runtime_context,
            schema,
            self._emit_state_update,
            self._append_node_trace,
            self._merge_state_schema,
        )

    def _emit_state_update(self, result: NodeExecutionResult) -> None:
        self._state_events.emit(result, self._state_event_callback, logger)

    @staticmethod
    def _routing_state(
        node: WorkflowNode,
        plan: PlanGraph,
        executed: set[str],
        blocked: set[str],
        outputs: object,
    ) -> str:
        return routing_state(
            node, plan, executed, blocked, outputs, successor=WorkflowEngine._resolve_successor
        )

    @staticmethod
    def _resolve_successor(node: WorkflowNode, output: dict[str, Any]) -> str | None:
        target = WorkflowEngine.evaluate_branch(node, output)
        return target if target is not None else node.next

    evaluate_branch = staticmethod(evaluate_branch)
    _condition_matches = staticmethod(condition_matches)
    _branch_candidates = staticmethod(branch_candidates)
    _maybe_checkpoint = staticmethod(save_progress)
    _fail_run = staticmethod(fail_run)
    _append_node_trace = staticmethod(append_node_trace)
    _merge_state_schema = staticmethod(merge_state_schema)
    _summarize_output = staticmethod(summarize_output)
    _elapsed_ms = staticmethod(elapsed_ms)
    _attempt_summary = staticmethod(attempt_summary)
    _node_allows_auto_retry = staticmethod(node_allows_auto_retry)
    _agentic_tool_allows_auto_retry = staticmethod(agentic_tool_allows_auto_retry)
    _recovery_hint = staticmethod(recovery_hint)
    _run_clarify_node = staticmethod(run_clarify_node)
    _has_non_empty_param = staticmethod(has_non_empty_param)
    _merge_runtime_fallback_params = staticmethod(merge_runtime_fallback_params)
