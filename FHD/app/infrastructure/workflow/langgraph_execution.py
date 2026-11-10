"""Node execution, branching, results, streaming, and checkpoint mixin."""

from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING, Any

from app.application.workflow.ports import CheckpointStore, StateEventPublisher, StateUpdateEvent
from app.application.workflow.workflow_types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)
from app.domain.task_lifecycle.control import RETRYABLE_CODES
from app.domain.task_lifecycle.machine import DEFAULT_MAX_ATTEMPTS
from app.infrastructure.workflow.langgraph_runtime import (
    _now_iso,
    _ReadersWriterGate,
    _summarize_output,
    logger,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DEFERRED_RETRY_CODES = frozenset(
    {
        "tool_rate_limited",
        "tool_rate_limit_backend_unavailable",
        "tool_concurrency_limited",
        "tool_circuit_open",
    }
)


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
        # Risk level is an approval boundary, not a replay guarantee. A low-risk
        # write can still duplicate an effect after a timeout; retries require an
        # explicit server-owned idempotency contract.
        retryable = bool(node.idempotent)
        attempts_quota = min(max_retries, DEFAULT_MAX_ATTEMPTS - 1) if retryable else 0
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
            except RECOVERABLE_ERRORS as exc:
                last_error = str(exc)
                attempts.append({"error": last_error, "recoverable": True})
                retries += 1
                if not isinstance(exc, (TimeoutError, ConnectionError)):
                    retryable = False
                    break
                continue
            output = raw if isinstance(raw, dict) else {"output": raw}
            last_output = output
            if (
                output.get("retryable") is False
                or output.get("outcome") == "unknown"
                or output.get("outcome_unknown")
                or output.get("reconciliation_required")
                or output.get("requires_reconciliation")
            ):
                retryable = False
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
            code = str(output.get("error_code") or "")
            unknown_outcome = (
                output.get("outcome") == "unknown"
                or output.get("execution_outcome") == "unknown"
                or output.get("requires_reconciliation") is True
                or output.get("reconciliation_required") is True
            )
            if code in _DEFERRED_RETRY_CODES and not unknown_outcome:
                # Admission failures happen before tool dispatch. Preserve the
                # safe retry signal for a later request, but do not hammer the
                # same quota, Redis backend, exhausted capacity, or open circuit
                # in this synchronous workflow turn.
                retryable = output.get("retryable") is True
                break
            # An unknown side effect must be reconciled, never retried automatically;
            # otherwise a timeout after a successful write could duplicate it.
            if code not in RETRYABLE_CODES or unknown_outcome:
                retryable = False
            if not retryable:
                break
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
            recovery_hint=self._recovery_hint(
                node,
                retryable=retryable,
                failure_output=last_output,
            ),
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
    def _recovery_hint(
        node: WorkflowNode,
        *,
        retryable: bool | None = None,
        failure_output: dict[str, Any] | None = None,
    ) -> str:
        failure_output = failure_output or {}
        code = str(failure_output.get("error_code") or "")
        if code in _DEFERRED_RETRY_CODES:
            retry_after = failure_output.get("retry_after")
            if isinstance(retry_after, int) and retry_after > 0:
                return f"本次工具尚未执行，请等待约 {retry_after} 秒后重试。"
            return "本次工具尚未执行；限流或服务恢复后可重新提交。"
        if retryable is False and node.idempotent:
            return "本次调用可能已有副作用，系统未自动重试；请先核对业务状态后人工处理。"
        if node.risk == "high" and not node.idempotent:
            return "高风险/非幂等节点未自动重试；请先核对业务状态，再由人工决定是否重试。"
        if node.idempotent:
            return "节点具备幂等性，可在修复后重试"
        return "节点未声明幂等；请先核对业务状态后再人工重试"

    # -- result mapping ------------------------------------------------------------

    @staticmethod
    def _trace_entry(result: NodeExecutionResult) -> dict[str, Any]:
        return {
            "node_id": result.node_id,
            "tool_id": result.tool_id,
            "action": result.action,
            "success": result.success,
            "error": result.error,
            "retryable": result.retryable,
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

        executed = {str(node_id) for node_id in (state.get("executed") or [])}
        blocked = {str(node_id) for node_id in (state.get("blocked") or [])}
        node_ids = {node.node_id for node in plan.nodes}

        # A blocked prerequisite makes every dependent node unreachable. Record
        # that fact explicitly so a partially scheduled graph cannot be mistaken
        # for a successful completion.
        changed = True
        while changed:
            changed = False
            for node in plan.nodes:
                if node.node_id in executed or node.node_id in blocked:
                    continue
                if any(dependency in blocked for dependency in node.depends_on):
                    blocked.add(node.node_id)
                    changed = True
        state["executed"] = sorted(executed)
        state["blocked"] = sorted(blocked)

        outputs = state.get("node_outputs") or {}
        waiting_approval: list[str] = []
        waiting_user: list[str] = []
        if isinstance(outputs, dict):
            for node_id in executed:
                output = outputs.get(node_id)
                if not isinstance(output, dict):
                    continue
                if output.get("requires_approval"):
                    waiting_approval.append(node_id)
                elif output.get("requires_confirmation"):
                    waiting_user.append(node_id)

        if waiting_approval or waiting_user:
            status = "waiting_approval" if waiting_approval else "waiting_user"
            waiting_ids = sorted(waiting_approval or waiting_user)
            pending = sorted(node_ids - executed - blocked)
            state["workflow_status"] = {
                "state": status,
                "waiting_node_ids": waiting_ids,
                "pending_nodes": pending,
                "message": "工作流等待审批" if waiting_approval else "工作流等待用户确认",
            }
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                node_results=node_results,
                final_context=state,
                message=state["workflow_status"]["message"],
            )

        unresolved = sorted(node_ids - executed - blocked)
        if unresolved:
            message = f"工作流执行进入死端，未完成节点：{', '.join(unresolved)}"
            state["blocked"] = sorted(blocked | set(unresolved))
            state["failure"] = {
                "node_id": "__xcagi_schedule__",
                "error": message,
                "recovery_hint": "检查计划依赖与分支结果后重新规划；不要把未执行节点报告为成功。",
            }
            state["workflow_status"] = {
                "state": "blocked",
                "blocked_nodes": unresolved,
                "message": message,
                "recovery_hint": state["failure"]["recovery_hint"],
            }
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                node_results=node_results,
                final_context=state,
                message=message,
            )

        state["workflow_status"] = {
            "state": "completed",
            "executed_nodes": sorted(executed),
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
        checkpointed_nodes = set(initial.get("executed") or [])
        final = dict(initial)
        reader_ids = {n.node_id for n in plan.nodes if _ReadersWriterGate.is_reader(n)}
        batches: list[dict[str, Any]] = []
        prev_executed = set(initial.get("executed") or [])
        for chunk in graph.stream(
            dict(initial),
            config={"recursion_limit": self._recursion_limit(plan)},
            stream_mode="values",
        ):
            final = chunk
            executed = chunk.get("executed") or []
            failure = chunk.get("failure") or {}
            if len(executed) > last_saved and checkpointer is not None:
                if failure:
                    # Parallel readers may share a failed LangGraph superstep.
                    # Persist only verified successful results from that batch so
                    # resume never replays them and never treats the failed node as
                    # complete.
                    successful = [
                        dict(result)
                        for result in (chunk.get("results") or [])
                        if isinstance(result, dict) and result.get("success") is True
                    ]
                    successful_ids = {str(result.get("node_id") or "") for result in successful}
                    newly_completed = successful_ids - checkpointed_nodes
                    successful_ids.update(checkpointed_nodes)
                    if newly_completed:
                        partial = copy.deepcopy(chunk)
                        partial["executed"] = sorted(successful_ids)
                        partial["results"] = [dict(result) for result in (chunk.get("results") or [])]
                        partial["workflow_trace"] = [
                            dict(entry) for entry in (chunk.get("workflow_trace") or [])
                        ]
                        partial["node_outputs"] = {
                            node_id: value
                            for node_id, value in (chunk.get("node_outputs") or {}).items()
                            if node_id in successful_ids
                        }
                        partial["blocked"] = []
                        partial["failure"] = {}
                        partial["workflow_status"] = {"state": "running"}
                        self._save_checkpoint(checkpointer, plan, partial)
                        last_saved = len(successful_ids)
                        checkpointed_nodes = successful_ids
                else:
                    self._save_checkpoint(checkpointer, plan, chunk)
                    last_saved = len(executed)
                    checkpointed_nodes = set(executed)
            cur = set(executed)
            batch = sorted(cur - prev_executed)
            prev_executed = cur
            if parallel and len(batch) > 1 and all(nid in reader_ids for nid in batch):
                batches.append({"node_ids": batch, "mode": "parallel_read"})
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
            except RECOVERABLE_ERRORS:
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
            except RECOVERABLE_ERRORS:
                logger.exception("state publisher failed node=%s", result.node_id)
