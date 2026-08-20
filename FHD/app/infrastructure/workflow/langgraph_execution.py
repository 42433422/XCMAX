"""Node execution, branching, results, streaming, and checkpoint mixin."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from app.application.workflow.ports.checkpoint import CheckpointStore
from app.application.workflow.ports.events import StateEventPublisher, StateUpdateEvent
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)
from app.infrastructure.workflow.langgraph_runtime import (
    _now_iso,
    _ReadersWriterGate,
    _summarize_output,
    logger,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class LangGraphExecutionMixin:
    _dispatch: Any
    _publisher: StateEventPublisher | None
    _callback: Any

    if TYPE_CHECKING:

        @staticmethod
        def _recursion_limit(plan: PlanGraph) -> int: ...

    def _execute_node(
        self, node: WorkflowNode, state: dict[str, Any], max_retries: int
    ) -> NodeExecutionResult:
        if node.tool_id == "clarify":
            return self._run_clarify(node, state)
        retryable = bool(node.idempotent) or node.risk == "low"
        attempts_quota = max_retries if retryable else 0
        attempts: list[dict[str, Any]] = []
        last_error = ""
        last_output: dict[str, Any] = {}
        retries = 0
        started = _now_iso()
        begin = time.perf_counter()
        while retries <= attempts_quota:
            params = dict(node.params or {})
            params["_runtime_context"] = state
            try:
                raw = self._dispatch(node.tool_id, node.action, params)
            except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
                last_error = str(exc)
                attempts.append({"error": last_error, "recoverable": True})
                retries += 1
                continue
            output = raw if isinstance(raw, dict) else {"output": raw}
            last_output = output
            if output.get("success", False):
                return NodeExecutionResult(
                    node_id=node.node_id,
                    success=True,
                    tool_id=node.tool_id,
                    action=node.action,
                    params=dict(node.params or {}),
                    output=output,
                    retries=retries,
                    retryable=retryable,
                    started_at=started,
                    finished_at=_now_iso(),
                    duration_ms=int((time.perf_counter() - begin) * 1000),
                    attempts=attempts,
                )
            last_error = str(output.get("message") or output.get("error") or "未知错误")
            attempts.append({"error": last_error, "recoverable": True})
            retries += 1
        return NodeExecutionResult(
            node_id=node.node_id,
            success=False,
            tool_id=node.tool_id,
            action=node.action,
            params=dict(node.params or {}),
            output=last_output,
            error=last_error,
            retries=max(0, retries - 1),
            retryable=retryable,
            recovery_hint=self._recovery_hint(node),
            started_at=started,
            finished_at=_now_iso(),
            duration_ms=int((time.perf_counter() - begin) * 1000),
            attempts=attempts,
        )

    def _run_clarify(self, node: WorkflowNode, state: dict[str, Any]) -> NodeExecutionResult:
        params = node.params or {}
        question = str(params.get("question") or "").strip()
        answer_key = str(params.get("answer_key") or "confirmed").strip() or "confirmed"
        target_node_id = str(params.get("target_node_id") or "").strip()

        answers = state.get("_clarify_answers") or {}
        if not isinstance(answers, dict):
            answers = {}
        raw_node_answers = answers.get(node.node_id)
        node_answers: dict[str, Any] = (
            dict(raw_node_answers) if isinstance(raw_node_answers, dict) else {}
        )
        has_answer = node_answers.get(answer_key) is not None
        confirmed = bool(node_answers.get(answer_key)) if has_answer else False

        if has_answer:
            output: dict[str, Any] = {
                "success": True,
                "answer_confirmed": confirmed,
                "answer_key": answer_key,
            }
        else:
            # No answer: pause and route nowhere — the target/business node stays
            # un-dispatched (branch condition answer_confirmed == True never matches).
            output = {
                "success": True,
                "requires_confirmation": True,
                "answer_key": answer_key,
                "question": question,
                "target_node_id": target_node_id,
            }
        return NodeExecutionResult(
            node_id=node.node_id,
            success=True,
            tool_id=node.tool_id,
            action=node.action,
            params=dict(node.params or {}),
            output=output,
            retryable=False,
            started_at=_now_iso(),
            finished_at=_now_iso(),
            duration_ms=0,
        )

    def _resolve_successor(self, node: WorkflowNode, output: dict[str, Any]) -> str | None:
        target = self.evaluate_branch(node, output)
        if target is not None:
            return target
        return str(node.next) if node.next is not None else None

    @staticmethod
    def evaluate_branch(node: WorkflowNode, output: dict[str, Any]) -> str | None:
        """Return the target of the first matching branch, else ``None``."""
        if not isinstance(output, dict):
            output = {}
        for branch in node.branches or []:
            if LangGraphExecutionMixin._condition_matches(branch.condition, output):
                return str(branch.target)
        return None

    @staticmethod
    def _condition_matches(condition: dict[str, Any], output: dict[str, Any]) -> bool:
        if not isinstance(condition, dict):
            return False
        key = condition.get("key")
        if key is None or not isinstance(key, str):
            return False
        expected = condition.get("equals", condition.get("value"))
        return output.get(key) == expected

    @staticmethod
    def _recovery_hint(node: WorkflowNode) -> str:
        if node.idempotent:
            return "节点具备幂等性，可在修复后重试"
        if node.risk == "low":
            return "低风险节点，可安全重试"
        return "高风险/非幂等节点，请人工介入确认后再重试"

    # -- result mapping ------------------------------------------------------------

    @staticmethod
    def _trace_entry(result: NodeExecutionResult) -> dict[str, Any]:
        return {
            "node_id": result.node_id,
            "tool_id": result.tool_id,
            "action": result.action,
            "success": result.success,
            "error": result.error,
            "recovery_hint": result.recovery_hint,
        }

    @staticmethod
    def _result_dict(result: NodeExecutionResult) -> dict[str, Any]:
        return {
            "node_id": result.node_id,
            "success": result.success,
            "tool_id": result.tool_id,
            "action": result.action,
            "params": result.params,
            "output": result.output,
            "error": result.error,
            "retries": result.retries,
            "retryable": result.retryable,
            "recovery_hint": result.recovery_hint,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_ms": result.duration_ms,
            "attempts": result.attempts,
        }

    def _to_run_result(self, plan: PlanGraph, state: dict[str, Any]) -> WorkflowRunResult:
        node_results = [NodeExecutionResult(**dict(r)) for r in (state.get("results") or [])]
        failure = state.get("failure")
        if failure:
            state["workflow_status"] = {
                "state": "failed",
                "failed_node_id": failure.get("node_id"),
                "message": failure.get("error"),
                "recovery_hint": failure.get("recovery_hint"),
            }
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                node_results=node_results,
                final_context=state,
                message=f"节点 {failure.get('node_id')} 执行失败: {failure.get('error')}",
            )
        state["workflow_status"] = {
            "state": "completed",
            "executed_nodes": sorted(state.get("executed") or []),
            "message": "工作流执行完成",
        }
        return WorkflowRunResult(
            plan_id=plan.plan_id,
            success=True,
            node_results=node_results,
            final_context=state,
            message="工作流执行完成",
        )

    # -- checkpoint / events -------------------------------------------------------

    def _stream_run(
        self,
        graph: Any,
        plan: PlanGraph,
        initial: dict[str, Any],
        checkpointer: CheckpointStore | None,
        parallel: bool = True,
    ) -> dict[str, Any]:
        """Stream ``stream_mode="values"`` and checkpoint after each successful superstep.

        A checkpoint is saved only when a superstep succeeds (no ``failure``) and the
        count of executed nodes strictly grows — a failed superstep is never persisted.
        The last yielded value is the final graph state (equivalent to ``invoke``).

        When ``parallel=True``, real same-superstep batches containing more than one
        low-risk AND idempotent node are recorded under ``parallel_batches`` in the
        final context.
        """
        last_saved = len(initial.get("executed") or [])
        final = dict(initial)
        reader_ids = {n.node_id for n in plan.nodes if _ReadersWriterGate.is_reader(n)}
        batches: list[list[str]] = []
        prev_executed = set(initial.get("executed") or [])
        for chunk in graph.stream(
            dict(initial),
            config={"recursion_limit": self._recursion_limit(plan)},
            stream_mode="values",
        ):
            final = chunk
            executed = chunk.get("executed") or []
            if not (chunk.get("failure") or {}):
                if len(executed) > last_saved:
                    if checkpointer is not None:
                        self._save_checkpoint(checkpointer, plan, chunk)
                    last_saved = len(executed)
            cur = set(executed)
            batch = sorted(cur - prev_executed)
            prev_executed = cur
            if parallel and len(batch) > 1 and all(nid in reader_ids for nid in batch):
                batches.append(batch)
        if parallel and batches:
            final["parallel_batches"] = batches
        return final

    @staticmethod
    def _save_checkpoint(
        checkpointer: CheckpointStore, plan: PlanGraph, state: dict[str, Any]
    ) -> str:
        return str(
            checkpointer.save_checkpoint(
                plan.plan_id,
                len(state.get("executed") or []),
                dict(state),
                sorted(state.get("executed") or []),
                blocked=sorted(state.get("blocked") or []),
            )
        )

    @staticmethod
    def _replay_from_trace(
        traces: list[dict[str, Any]], outputs: dict[str, Any]
    ) -> list[NodeExecutionResult]:
        results: list[NodeExecutionResult] = []
        for t in traces:
            nid = t.get("node_id", "")
            results.append(
                NodeExecutionResult(
                    node_id=nid,
                    success=bool(t.get("success")),
                    tool_id=t.get("tool_id", ""),
                    action=t.get("action", ""),
                    output=dict(outputs.get(nid) or {}),
                    error=t.get("error", ""),
                    recovery_hint=t.get("recovery_hint", ""),
                )
            )
        return results

    def _emit_state_update(self, result: NodeExecutionResult) -> None:
        status = "succeeded" if result.success else "failed"
        event = {
            "type": "state.update",
            "node_id": result.node_id,
            "status": status,
            "output_summary": _summarize_output(result.output),
        }
        if self._callback is not None:
            try:
                self._callback(event)
            except RECOVERABLE_ERRORS:  # noqa: BLE001
                logger.exception("state callback failed node=%s", result.node_id)
        if self._publisher is not None:
            try:
                self._publisher.publish_state_update(
                    StateUpdateEvent(
                        node_id=result.node_id,
                        status=status,
                        output_summary=_summarize_output(result.output),
                        runtime="xcagi-langgraph",
                        payload=event,
                    )
                )
            except RECOVERABLE_ERRORS:  # noqa: BLE001
                logger.exception("state publisher failed node=%s", result.node_id)
