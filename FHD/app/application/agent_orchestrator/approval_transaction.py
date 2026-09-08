"""Commit approval consumption, run state and dispatch as one durable operation."""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    ApprovalGrantStorageError,
    validate_approval_grant,
    waiting_step,
)
from app.application.agent_orchestrator.run_models import agent_run_from_dict, utc_now_iso
from app.application.agent_orchestrator.task_background import apply_approved_step
from app.db.models.agent import AgentRunRecord
from app.db.models.agent_approval import AgentApprovalConsumption


def approve_and_enqueue(runs, queue, *, run_id, token, principal_id, runtime_context):
    import json

    jti = ""
    try:
        runs._ensure_schema()
        queue._ensure_schema()
        with runs._session_scope() as db:
            with queue._session_scope(read_only=True) as queue_db:
                if db.get_bind() is not queue_db.get_bind():
                    raise ApprovalGrantStorageError("审批和任务队列必须使用同一数据库")
            record = (
                db.query(AgentRunRecord).filter_by(run_id=run_id).with_for_update().one_or_none()
            )
            if record is None:
                raise ApprovalGrantError("审批任务不存在")
            old_payload = record.payload_json
            run = agent_run_from_dict(json.loads(old_payload))
            claims = validate_approval_grant(token, run=run, principal_id=principal_id)
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
            apply_approved_step(
                run, waiting_step(run), approved_by=principal_id, runtime_context=runtime_context
            )
            runs.save_in_session(db, run)
            queue.enqueue_in_session(db, run, requested_by=principal_id)
        return run
    except IntegrityError as exc:
        # Only an existing consumption proves replay; unrelated constraints are
        # storage failures. The enclosing scope has already rolled everything back.
        try:
            with runs._session_scope(read_only=True) as db:
                if jti and db.get(AgentApprovalConsumption, jti) is not None:
                    raise ApprovalGrantError("审批已使用") from exc
        except SQLAlchemyError as storage_exc:
            raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from storage_exc
        raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from exc
    except SQLAlchemyError as exc:
        raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from exc
