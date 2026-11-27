"""Adapt the existing SQL task queue to the fixed runtime's durable request ledger."""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import AgentRun, RunContextScope, utc_now_iso
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.worker_repository import lock_execution_claim
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    model_unsettled,
    withhold_runtime_output,
)
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def durable_queue(repository: SQLAlchemyAgentRunRepository) -> SQLAlchemyTaskExecutionRepository:
    queue = get_task_execution_repository()
    if not isinstance(queue, SQLAlchemyTaskExecutionRepository):
        raise XiaoxBindingError("durable_storage_required", "后台运行需要持久化任务队列")
    with repository.transaction(read_only=True) as db, queue.transaction(read_only=True) as queued:
        if db.get_bind() is not queued.get_bind():
            raise XiaoxBindingError("durable_storage_required", "任务和队列必须使用同一数据库")
    return queue


def stage_queued_request(
    run: AgentRun, request_key: str, payload: dict[str, Any]
) -> dict[str, Any]:
    XiaoxBindingStore._reject_legacy_binding(run)
    result = {
        **base_runtime_result(run.run_id),
        "execution_state": "queued",
        "exit_status": "queued",
        "resume_required": True,
        "output": "任务已受理，正在等待后台执行。",
    }
    run.status = "queued"
    run.error = ""
    run.metadata["_xiaox_queued_request"] = {
        **copy.deepcopy(payload),
        "request_key": request_key,
        "worker_turn_id": "queue_" + canonical_digest([run.run_id, request_key]),
        "generation": run.metadata["xiaox_runtime"].get("generation", 0),
        "state": "queued",
    }
    run.metadata["runtime_requests"][request_key].update(
        state="queued", result=copy.deepcopy(result)
    )
    run.final_output["xiaox_result"] = copy.deepcopy(result)
    run.add_event("runtime.queued", "原任务已进入后台执行队列")
    return result


def interrupted_queue_result(run: AgentRun, request_key: str) -> dict[str, Any] | None:
    """Use the committed result only for the interrupted worker that owned this queue turn."""
    pending = run.metadata.get("_xiaox_queued_request") or {}
    binding = run.metadata.get("xiaox_runtime") or {}
    requests = run.metadata.get("runtime_requests") or {}
    generation = pending.get("generation")
    worker_turn = pending.get("worker_turn_id")
    if (
        run.status != "blocked"
        or pending.get("request_key") != request_key
        or pending.get("state") != "queued"
        or (requests.get(request_key) or {}).get("state") != "queued"
        or type(generation) is not int
        or binding.get("generation") != generation + 1
        or binding.get("coordinator_active") is not False
        or binding.get("revoked") is not True
        or not isinstance(worker_turn, str)
        or not worker_turn
    ):
        return None
    worker_key = canonical_digest({"turn_id": worker_turn, "owner": run.user_id})
    worker = requests.get(worker_key) or {}
    result = run.final_output.get("xiaox_result")
    if (
        worker.get("state") == "interrupted"
        and worker.get("turn_id") == worker_turn
        and isinstance(result, dict)
        and result.get("run_id") == run.run_id
        and result.get("execution_state") == "unknown"
        and result.get("reconciliation_required") is True
        and result.get("ok") is False
    ):
        return copy.deepcopy(result)
    return None


def _return_queue_result(run: AgentRun, key: str, result: dict[str, Any]) -> None:
    run.metadata["_xiaox_queued_request"]["state"] = "returned"
    run.metadata["runtime_requests"][key].update(
        state="returned", result=copy.deepcopy(result), returned_at=utc_now_iso()
    )


def recover_interrupted_queue_request(
    repository: SQLAlchemyAgentRunRepository, run: AgentRun, key: str
) -> dict[str, Any] | None:
    """After owner authorization, publish only this terminal queue receipt in the host DB."""
    from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord
    from app.domain.shared_services.conversation_service import (
        ConversationRevisionError,
        lock_conversation_session,
    )

    if not isinstance(repository, SQLAlchemyAgentRunRepository) or not interrupted_queue_result(
        run, key
    ):
        return None
    context = run.metadata.get("runtime_context") or {}
    owner = run.user_id
    session = str(context.get("session_id") or context.get("conversation_id") or "")
    revision = context.get("_conversation_revision")
    if not session or type(revision) is not int or not owner.isdecimal():
        return None
    scope = RunContextScope(
        str(context.get("tenant_id")),
        str(context.get("mod_id") or context.get("active_mod_id") or ""),
        session,
        revision,
    )
    with repository.transaction() as db:
        row = db.get(AgentRunRecord, run.run_id)
        current = repository._record_to_run(row) if row is not None else None
        if current is None or current.user_id != owner or not scope.matches(current):
            return None
        receipt = (current.metadata.get("runtime_requests") or {}).get(key) or {}
        turn = receipt.get("turn_id")
        if not turn or canonical_digest({"turn_id": turn, "owner": owner}) != key:
            return None
        if receipt.get("state") == "returned":
            return copy.deepcopy(receipt.get("result"))
        result = interrupted_queue_result(current, key)
        if (
            result is None
            or current.metadata.get("non_retryable") is not True
            or (current.metadata.get("recovery") or {}).get("state")
            != "manual_reconciliation_required"
        ):
            return None
        try:
            lock_conversation_session(
                db, session_id=session, user_id=int(owner), expected_revision=revision
            )
        except (ConversationRevisionError, PermissionError):
            return None
        execution = AgentTaskExecutionRecord
        # The conditional write fences claim/requeue on SQLite as well as SQL engines with row locks.
        fenced = (
            db.query(execution)
            .filter(
                execution.run_id == current.run_id,
                execution.user_id == owner,
                execution.tenant_id == scope.tenant_id,
                execution.state == "failed",
                execution.finished_at.is_not(None),
                execution.lease_owner.is_(None),
                execution.lease_expires_at.is_(None),
            )
            .update({execution.state: "failed"}, synchronize_session=False)
        )
        if fenced != 1:
            return None
        returned = copy.deepcopy(current)
        _return_queue_result(returned, key, result)
        return result if repository.save_if_unchanged_in_session(db, returned, current) else None


def enqueue_resume(
    store: XiaoxBindingStore,
    parent: AgentRun,
    mutation: Callable[[AgentRun, dict[str, Any]], None],
) -> AgentRun:
    """Publish a continuation and its queue row in the same host transaction."""
    from app.db.models.agent import AgentTaskExecutionRecord
    from app.domain.task_lifecycle.adapters import execution_requeue_allowed
    from app.domain.task_lifecycle.control import SessionBook

    store._reject_legacy_binding(parent)
    repository = store.repository
    queue = durable_queue(repository)
    current = copy.deepcopy(parent)
    metadata = current.metadata.setdefault("xiaox_runtime", {})
    # Conversation authorization can take a write lock in the same SQLite
    # database. Check it before the queue CAS and again in the claimed worker.
    store._validate_authority(current, metadata)
    with repository.transaction() as db:
        execution = db.get(AgentTaskExecutionRecord, parent.run_id)
        if execution is not None:
            control = SessionBook(db).get("agent", str(execution.tenant_id or ""), parent.run_id)
            if (
                execution.lease_owner
                or execution.lease_expires_at
                or execution.last_error_code == "needs_verification"
                or control.get("effects")
            ):
                raise XiaoxBindingError("reconciliation_required", "原执行权或业务效果尚未核对")
            if not execution_requeue_allowed(str(execution.state), retryable=True):
                raise XiaoxBindingError("binding_conflict", "原任务仍有执行权或已经结束")
            matched = (
                db.query(AgentTaskExecutionRecord)
                .filter(
                    AgentTaskExecutionRecord.run_id == parent.run_id,
                    AgentTaskExecutionRecord.state == execution.state,
                    AgentTaskExecutionRecord.execution_count == execution.execution_count,
                )
                .update(
                    {AgentTaskExecutionRecord.updated_at: execution.updated_at},
                    synchronize_session=False,
                )
            )
            if matched != 1:
                raise XiaoxBindingError("binding_conflict", "任务执行权已变化")
        if current.status == "blocked":
            if (current.final_output.get("xiaox_result") or {}).get("retryable") is not True:
                raise XiaoxBindingError("run_inactive", "原任务尚不满足安全续跑条件")
            # Explicit new request admission and the durable queue claim share
            # this CAS. Preserve all original goals, receipts and budget use;
            # existing pause/cancel, parent controls and unknown-effect guards
            # still apply below before the transaction can commit.
            current.status = "running"
            current.error = ""
            current.add_event("run.resumed", "按用户新请求继续原 Xiaox 任务")
        store._validate_control(current)
        pending = current.metadata.get("_xiaox_queued_request") or {}
        if metadata.get("coordinator_active"):
            raise XiaoxBindingError("binding_conflict", "原任务已有待执行或活动的运行请求")
        if pending.get("state") == "queued":
            worker_key = canonical_digest(
                {"turn_id": pending.get("worker_turn_id"), "owner": current.user_id}
            )
            if (
                metadata.get("close_reason") != "paused"
                or metadata.get("generation", 0) != pending.get("generation")
                or worker_key in (current.metadata.get("runtime_requests") or {})
            ):
                raise XiaoxBindingError("binding_conflict", "原排队请求尚未安全结束")
            # A pause before worker admission has no runtime turn to reconcile.
            # Settle that request; the explicit resume receives its own identity.
            current.metadata["runtime_requests"][pending["request_key"]].update(
                state="returned",
                returned_at=utc_now_iso(),
                result={
                    **base_runtime_result(current.run_id),
                    "execution_state": "paused",
                    "exit_status": "paused",
                    "resume_required": True,
                },
            )
        if model_unsettled(metadata) or any(
            call.get("state") in {"claimed", "unknown"}
            for call in metadata.get("calls", {}).values()
        ):
            raise XiaoxBindingError("reconciliation_required", "原任务结果尚未确定，不能重放")
        mutation(current, metadata)
        if not repository.save_if_unchanged_in_session(db, current, parent):
            raise XiaoxBindingError("binding_conflict", "原任务状态已变化，请重新读取")
        queue.enqueue_in_session(db, current, requested_by=current.user_id, retryable=True)
    return current


class _ClaimedRuntimeRepository(SQLAlchemyAgentRunRepository):
    """Fence every runtime write, including CAS, with the existing queue lease."""

    def __init__(
        self, repository: SQLAlchemyAgentRunRepository, execution: AgentTaskExecution, owner: str
    ):
        super().__init__(
            session_factory=repository._session_factory,
            auto_create=repository.allows_schema_setup,
        )
        self._execution = copy.deepcopy(execution)
        self._owner = owner

    @contextmanager
    def _session_scope(self, *, read_only: bool = False) -> Iterator[Session]:
        with super()._session_scope(read_only=read_only) as db:
            if not read_only:
                lock_execution_claim(
                    db,
                    run_id=self._execution.run_id,
                    owner_id=self._owner,
                    execution_count=self._execution.execution_count,
                )
            yield db


def _execute_queued_runtime(
    repository: SQLAlchemyAgentRunRepository, execution: AgentTaskExecution, owner: str
) -> dict[str, Any]:
    """Consume one saved HTTP request; lease recovery cannot invent another turn."""
    from app.application.agent_runtime.gateway import _failure, run_runtime_task

    claimed = _ClaimedRuntimeRepository(repository, execution, owner)
    store = XiaoxBindingStore(claimed)
    binding = store.get(execution.run_id)
    run, metadata = binding.run, binding.metadata
    pending = run.metadata.get("_xiaox_queued_request")
    if not isinstance(pending, dict):
        raise XiaoxBindingError("request_missing", "原任务缺少已保存的队列请求")
    original = (run.metadata.get("runtime_requests") or {}).get(pending["request_key"], {})
    if pending.get("state") == "returned" and isinstance(original.get("result"), dict):
        return copy.deepcopy(original["result"])
    worker_key = canonical_digest({"turn_id": pending["worker_turn_id"], "owner": run.user_id})
    previous = (run.metadata.get("runtime_requests") or {}).get(worker_key)
    result: dict[str, Any]
    if previous is not None:
        stored_result = previous.get("result")
        if not isinstance(stored_result, dict):
            stored_result = interrupted_queue_result(run, pending["request_key"])
        if isinstance(stored_result, dict):
            result = copy.deepcopy(stored_result)
        else:
            result = _failure(
                "reconciliation_required", "后台请求结果尚未确定，未重放", run_id=run.run_id
            )
            result.update(execution_state="unknown", reconciliation_required=True)
    else:
        store._validate_authority(run, metadata)
        store._validate_control(run)
        if metadata.get("generation", 0) != pending["generation"] or model_unsettled(metadata):
            raise XiaoxBindingError("reconciliation_required", "原运行状态已变化，不能重放队列请求")
        context = binding.context
        context["turn_id"] = pending["worker_turn_id"]
        actions = run.metadata.get("runtime_allowed_actions")
        gate = None
        if run.metadata.get("runtime_gate_required"):
            from app.application.employee_runtime.agent import restore_xiaox_employee_gate

            restored, gate = restore_xiaox_employee_gate(
                str(context.get("employee_id") or ""),
                context,
                input_data=copy.deepcopy(run.metadata.get("_xiaox_input_data")),
            )
            if sorted(restored) != sorted(actions or []):
                raise XiaoxBindingError("owner_changed", "原员工能力范围已变化")
        try:
            result = run_runtime_task(
                run_id=run.run_id,
                task=pending["task"],
                system_prompt=run.metadata["_xiaox_system_prompt"],
                runtime_context=context,
                history=copy.deepcopy(pending.get("history")),
                input_data=copy.deepcopy(pending.get("input_data")),
                completion_mode=run.metadata["runtime_completion_mode"],
                allowed_actions=actions,
                gate=gate,
                answer_to_waiting_input=pending.get("answer_to_waiting_input", False),
                _repository=claimed,
            )
        except asyncio.CancelledError:
            interrupted = interrupted_queue_result(
                store.get(run.run_id).run, pending["request_key"]
            )
            if interrupted is None:
                raise
            result = interrupted

    def finish(parent: AgentRun, current: dict[str, Any]) -> None:
        request = parent.metadata.get("_xiaox_queued_request") or {}
        if request.get("request_key") != pending["request_key"]:
            raise XiaoxBindingError("binding_conflict", "队列请求已变化")
        if model_unsettled(current) or any(
            call.get("state") in {"claimed", "unknown"}
            for call in current.get("calls", {}).values()
        ):
            if result.get("ok") is True:
                withhold_runtime_output(
                    result, status="unknown", error="执行或模型计量结果尚未确定，请核对原任务回执"
                )
            result.update(
                ok=False,
                business_completed=False,
                verified_operations=False,
                execution_state="unknown",
                exit_status="unknown",
                reconciliation_required=True,
            )
        _return_queue_result(parent, pending["request_key"], result)
        if result.get("reconciliation_required"):
            parent.metadata.update(
                non_retryable=True, recovery={"state": "manual_reconciliation_required"}
            )
            current.update(
                revoked=True, coordinator_active=False, close_reason="reconciliation_required"
            )
        if parent.status in {"queued", "running"}:
            state = result.get("execution_state")
            if state in {"completed", "waiting_user", "running", "paused", "cancelled"}:
                parent.status = state
            elif result.get("reconciliation_required"):
                parent.status = "blocked"
            else:
                parent.status = "failed"
            parent.final_output["xiaox_result"] = copy.deepcopy(result)

    store.update(run.run_id, finish)
    return result


def execute_queued_runtime(
    repository: SQLAlchemyAgentRunRepository, execution: AgentTaskExecution, owner: str
) -> dict[str, Any]:
    from app.application.agent_runtime.gateway import _failure

    try:
        result = _execute_queued_runtime(repository, execution, owner)
    except XiaoxBindingError as exc:
        code, message = exc.code, str(exc)
        result = _failure(code, message, run_id=execution.run_id)
        if code in {"paused", "cancelled"}:
            result["execution_state"] = code
        else:
            result["execution_state"] = "blocked"
        if code == "reconciliation_required":
            result.update(execution_state="unknown", reconciliation_required=True)

        def blocked(run: AgentRun, metadata: dict[str, Any]) -> None:
            if run.status not in {"paused", "cancelled", "completed", "rejected"}:
                run.status = "blocked"
                run.error = message
                run.final_output["xiaox_result"] = copy.deepcopy(result)
            pending = run.metadata.get("_xiaox_queued_request") or {}
            if pending.get("request_key") in (run.metadata.get("runtime_requests") or {}):
                _return_queue_result(run, pending["request_key"], result)
            if result.get("reconciliation_required"):
                run.metadata.update(
                    non_retryable=True, recovery={"state": "manual_reconciliation_required"}
                )
            metadata.update(revoked=True, coordinator_active=False, close_reason=code)

        XiaoxBindingStore(_ClaimedRuntimeRepository(repository, execution, owner)).update(
            execution.run_id, blocked
        )
    # The claim-fenced run receipt has committed before touching the originating
    # conversation database. A detached chat view does not own that write.
    try:
        run = repository.get(execution.run_id)
    except RECOVERABLE_ERRORS:
        logger.warning("queued runtime receipt could not be read for chat history", exc_info=True)
        return result
    if run is not None:
        context = run.metadata.get("runtime_context") or {}
        pending = run.metadata.get("_xiaox_queued_request") or {}
        original = (run.metadata.get("runtime_requests") or {}).get(pending.get("request_key"), {})
        if context.get("session_id") or context.get("conversation_id"):
            from app.application.ai_chat.conversation_history import reconcile_queued_chat_reply

            reconcile_queued_chat_reply(
                context, str(original.get("turn_id") or ""), run.run_id, run=run
            )
    return result
