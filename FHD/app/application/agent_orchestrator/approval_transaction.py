"""Commit approval consumption, run state and dispatch as one durable operation."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.application.agent_orchestrator.approval_grant import (
    _EVIDENCE_KEY,
    ApprovalGrantError,
    ApprovalGrantStorageError,
    _params_hash,
    validate_approval_grant,
    waiting_step,
)
from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    agent_run_from_dict,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.session_renewal import renew_approval_session
from app.application.agent_orchestrator.task_background import apply_approved_step
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.models.agent import AgentRunRecord
from app.db.models.agent_approval import AgentApprovalConsumption


def _legacy_tail_metadata(run: AgentRun) -> dict[str, Any] | None:
    plan = run.metadata.get("plan") or {}
    metadata = plan.get("metadata") or {}
    return metadata if "legacy_elt_tail_recheck" in metadata else None


def _legacy_tail_matches(
    runs: SQLAlchemyAgentRunRepository,
    run: AgentRun,
    step: AgentStep,
    approved_by: str,
    context: dict[str, Any],
) -> bool:
    metadata = _legacy_tail_metadata(run)
    if metadata is None:
        return True

    from app.application.agent_orchestrator.task_context import task_context_of
    from app.application.elt.batch_continuation import (
        BatchContinuationBlocked,
        build_legacy_batch_continuation,
    )

    parent_id = metadata.get("continued_from_run_id")
    task = task_context_of(run)
    if (
        metadata.get("legacy_elt_tail_recheck") is not True
        or metadata.get("source") != "elt_batch_continuation"
        or not isinstance(parent_id, str)
        or not parent_id
        or task.get("parent_run_id") != parent_id
        or approved_by != run.user_id
    ):
        return False
    parent = runs.get(parent_id)
    if parent is None or parent.user_id != run.user_id:
        return False
    try:
        verified = build_legacy_batch_continuation(parent, context)
    except BatchContinuationBlocked:
        return False
    if verified is None:
        return False
    expected, lineage = verified
    node = expected.nodes[0]
    return (
        expected.plan_id == run.plan_id
        and (step.node_id, step.tool_id, step.action, step.params)
        == (node.node_id, node.tool_id, node.action, node.params)
        and (task.get("task_id"), task.get("root_run_id"), task.get("attempt"))
        == (lineage["task_id"], lineage["root_run_id"], lineage["task_attempt"])
    )


def enqueue_claimed_workspace_approval(
    runs: SQLAlchemyAgentRunRepository,
    queue: SQLAlchemyTaskExecutionRepository,
    *,
    run: AgentRun,
    previous: AgentRun,
    step: AgentStep,
    approved_by: str,
    runtime_context: dict[str, Any],
) -> bool:
    """Atomically publish the already claimed Approval Workspace run to the host queue."""
    from app.db.models.agent import AgentTaskExecutionRecord
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db
    from app.domain.task_lifecycle.adapters import (
        LEASED_STATES,
        execution_requeue_allowed,
    )

    receipt = run.metadata["approval_receipt"]
    if not approved_by:
        return False
    with get_db() as db:
        tenant = str(runtime_context.get("tenant_id") or "")
        if not tenant.isdigit():
            return False
        approval = (
            db.query(ApprovalRequest)
            .filter_by(request_no=receipt["approval_request_id"], tenant_id=int(tenant))
            .one_or_none()
        )
        if approval is None or str(approval.status) not in {
            "pending",
            "in_progress",
            "approved",
        }:
            return False
        try:
            body = json.loads(approval.business_data or "{}")
        except (TypeError, ValueError):
            return False
        claim = body.get("agent_execution_claim") if isinstance(body, dict) else None
        if (
            not isinstance(claim, dict)
            or claim.get("agent_run_id") != run.run_id
            or claim.get("approved_step_id") not in {step.step_id, step.node_id}
            or "workflow_execution" in body
        ):
            return False

    if not _legacy_tail_matches(runs, run, step, approved_by, runtime_context):
        return False
    receipt.update(queue_approval="workspace_claim", params_sha256=_params_hash(step))
    apply_approved_step(run, step, approved_by=approved_by, runtime_context=runtime_context)
    from app.application.agent_orchestrator.elt_checkpoint_recovery import (
        ELT_CHECKPOINT_PROTOCOL,
    )

    run.metadata["dispatch"]["elt_checkpoint_protocol"] = ELT_CHECKPOINT_PROTOCOL
    with runs.transaction() as db:
        with queue.transaction(read_only=True) as queue_db:
            if db.get_bind() is not queue_db.get_bind():
                raise ApprovalGrantStorageError("审批和任务队列必须使用同一数据库")
        current = db.get(AgentTaskExecutionRecord, run.run_id)
        if current is not None and (
            current.state in LEASED_STATES
            or not execution_requeue_allowed(current.state)
            or db.query(AgentTaskExecutionRecord)
            .filter_by(
                run_id=run.run_id,
                state=current.state,
                execution_count=current.execution_count,
            )
            .update(
                {AgentTaskExecutionRecord.updated_at: current.updated_at},
                synchronize_session=False,
            )
            != 1
        ):
            return False
        if not runs.save_if_unchanged_in_session(db, run, previous):
            return False
        queue.enqueue_in_session(db, run, requested_by=approved_by)
    return True


def approve_and_enqueue(
    runs: SQLAlchemyAgentRunRepository,
    queue: SQLAlchemyTaskExecutionRepository,
    *,
    run_id: str,
    token: str,
    principal_id: str,
    runtime_context: dict[str, Any],
    authenticated_binding: dict[str, Any] | None = None,
    authenticated_actor_binding: dict[str, Any] | None = None,
) -> AgentRun:
    jti = ""
    try:
        with runs.transaction() as db:
            with queue.transaction(read_only=True) as queue_db:
                if db.get_bind() is not queue_db.get_bind():
                    raise ApprovalGrantStorageError("审批和任务队列必须使用同一数据库")
            record = (
                db.query(AgentRunRecord).filter_by(run_id=run_id).with_for_update().one_or_none()
            )
            if record is None:
                raise ApprovalGrantError("审批任务不存在")
            from app.db.models.agent import AgentTaskExecutionRecord

            execution = db.get(AgentTaskExecutionRecord, run_id)
            if execution is not None and execution.state in {
                "rejected",
                "completed",
                "succeeded",
                "cancelled",
                "failed",
                "timed_out",
            }:
                raise ApprovalGrantError("任务已结束，不能审批通过后执行")
            from app.domain.task_lifecycle.control import (
                SessionBook,
                approval_actor_allowed,
            )

            book = SessionBook(db)
            tenant = str(execution.tenant_id or "") if execution is not None else ""
            body = book.get("agent", tenant, run_id)
            if execution is not None and execution.state in {
                "waiting_approval",
                "paused",
                "blocked",
            }:
                started = str(body.get("approval_requested_at") or execution.updated_at or "")
                if started:
                    moment = datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00"))
                    age = (
                        moment - datetime.fromisoformat(started.replace("Z", "+00:00"))
                    ).total_seconds()
                    if age >= float(getattr(queue, "_approval_timeout_seconds", 86400.0)):
                        execution.state = "rejected"
                        execution.last_error_code = "approval_timeout"
                        raise ApprovalGrantError("审批已超时")
            if not approval_actor_allowed(body, principal_id):
                raise ApprovalGrantError("无权审批该任务")
            old_payload = record.payload_json
            run = agent_run_from_dict(json.loads(old_payload))
            if _legacy_tail_metadata(run) is not None:
                raise ApprovalGrantError("原导入续接需在审批工作台重新核对附件回执")
            claims = validate_approval_grant(token, run=run, principal_id=principal_id)
            renew_approval_session(
                run,
                principal_id=principal_id,
                authenticated_binding=authenticated_binding,
                authenticated_actor_binding=authenticated_actor_binding,
            )
            jti = str(claims["jti"])
            db.add(
                AgentApprovalConsumption(
                    jti=str(claims["jti"]),
                    run_id=run_id,
                    step_id=str(claims["step_id"]),
                    consumed_at=utc_now_iso(),
                )
            )
            db.flush()
            # The payload comparison also protects SQLite, where FOR UPDATE is ignored.
            changed = (
                db.query(AgentRunRecord)
                .filter(
                    AgentRunRecord.run_id == run_id,
                    AgentRunRecord.payload_json == old_payload,
                )
                .update({AgentRunRecord.status: "queued"}, synchronize_session=False)
            )
            if changed != 1:
                raise ApprovalGrantError("审批任务已变化")
            if claims["tool_id"] == "catalog_products_v1":
                evidence = dict(run.metadata.get(_EVIDENCE_KEY) or {})
                step_id = str(claims["step_id"])
                if step_id in evidence and evidence[step_id] != token:
                    raise ApprovalGrantError("目录审批原始凭据不可替换")
                evidence[step_id] = token
                run.metadata[_EVIDENCE_KEY] = evidence
            apply_approved_step(
                run,
                waiting_step(run),
                approved_by=principal_id,
                runtime_context=runtime_context,
                approval_claims=claims,
            )
            run.metadata["approval_receipt"] = {
                **run.metadata["approval_receipt"],
                "grant_id": jti,
                "step_id": str(claims["step_id"]),
                "tool_id": str(claims["tool_id"]),
                "action": str(claims["action"]),
                "approved_by": principal_id,
                "params_sha256": str(claims["params_sha256"]),
            }
            runs.save_in_session(db, run)
            queue.enqueue_in_session(db, run, requested_by=principal_id)
        return run
    except IntegrityError as exc:
        # Only an existing consumption proves replay; unrelated constraints are
        # storage failures. The enclosing scope has already rolled everything back.
        try:
            with runs.transaction(read_only=True) as db:
                if jti and db.get(AgentApprovalConsumption, jti) is not None:
                    raise ApprovalGrantError("审批已使用") from exc
        except SQLAlchemyError as storage_exc:
            raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from storage_exc
        raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from exc
    except SQLAlchemyError as exc:
        raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from exc
