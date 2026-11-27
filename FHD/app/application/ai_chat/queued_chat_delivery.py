"""SQL recovery for original queued chat delivery, using the existing run ledger."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_repository import AgentRunRepository


@contextmanager
def _queued_chat_source_guard(db: Session, run: AgentRun) -> Iterator[bool]:
    """Hold the original SQL source fence through the conversation commit."""
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.db.models.agent import AgentRunRecord
    from app.domain.shared_services.conversation_service import begin_conversation_write

    repository = get_agent_run_repository()
    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        yield False
        return
    with repository.transaction(read_only=True) as host_db:
        host, target = host_db.get_bind().engine, db.get_bind().engine
        shared = host is target or (
            host.url.database not in (None, "", ":memory:") and host.url == target.url
        )
        source = db if shared else host_db
        # Business writers acquire Host before Mod. Keep the same order here;
        # SQLite reserves the whole database, not merely the selected run row.
        begin_conversation_write(source)
        row = source.query(AgentRunRecord).filter_by(run_id=run.run_id).with_for_update().first()
        current = repository._record_to_run(row) if row is not None else None
        matches = current is not None and current.to_dict() == run.to_dict()
        if matches and not shared:
            begin_conversation_write(db)
        yield matches


def reconcile_pending_chat_replies(
    *,
    repository: AgentRunRepository,
    stopped: Callable[[], bool] = lambda: False,
    cursor: dict[str, str] | None = None,
    limit: int = 50,
) -> int:
    """Retry only committed reply projections in the existing dispatcher recovery cycle.

    The run ledger is the source; no model, tool, claim or business state is replayed.
    Recent receipts are checked first; a bounded keyset sweep also reaches old
    receipts without letting historical volume delay newly completed work.
    Conversation revision and original queue bindings fence every actual write.
    """
    from sqlalchemy import and_, or_

    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.ai_chat.conversation_history import reconcile_queued_chat_reply
    from app.db.models.agent import AgentRunRecord
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest

    if stopped() or not isinstance(repository, SQLAlchemyAgentRunRepository):
        return 0
    with repository.transaction(read_only=True) as db:
        query = db.query(AgentRunRecord).filter(
            AgentRunRecord.intent == "xiaox.runtime",
            AgentRunRecord.status.in_(
                (
                    "completed",
                    "failed",
                    "blocked",
                    "cancelled",
                    "unknown",
                    "waiting_user",
                    "paused",
                    "running",
                )
            ),
        )
        page_size = max(0, min(limit, 200))
        recent = [
            repository._record_to_run(row)
            for row in query.order_by(
                AgentRunRecord.updated_at.desc(), AgentRunRecord.run_id.desc()
            )
            .limit(page_size)
            .all()
        ]
        if cursor:
            query = query.filter(
                or_(
                    AgentRunRecord.updated_at > cursor["updated_at"],
                    and_(
                        AgentRunRecord.updated_at == cursor["updated_at"],
                        AgentRunRecord.run_id > cursor["run_id"],
                    ),
                )
            )
        candidates = [
            (repository._record_to_run(row), row.updated_at, row.run_id)
            for row in query.order_by(AgentRunRecord.updated_at, AgentRunRecord.run_id)
            .limit(page_size)
            .all()
        ]
    if not candidates and cursor is not None:
        cursor.clear()
    delivered = 0
    scanned: set[str] = set()
    # Recent rows do not move the historical cursor; permanently unavailable
    # messages cannot starve a recoverable receipt farther back in the ledger.
    ordered: list[tuple[AgentRun | None, str | None, str | None]] = [
        (run, None, None) for run in recent
    ]
    ordered.extend(candidates)
    for run, updated_at, candidate_id in ordered:
        if stopped():
            break
        if cursor is not None and updated_at is not None and candidate_id is not None:
            cursor.update(updated_at=updated_at, run_id=candidate_id)
        if run is None or run.metadata.get("runtime_type") != "xiaox":
            continue
        run_id = run.run_id
        if run_id in scanned:
            continue
        scanned.add(run_id)
        context = run.metadata.get("runtime_context") or {}
        if not (context.get("session_id") or context.get("conversation_id")):
            continue
        for key, receipt in (run.metadata.get("runtime_requests") or {}).items():
            if stopped():
                return delivered
            turn = receipt.get("turn_id")
            result = receipt.get("result")
            if (
                not isinstance(turn, str)
                or not turn
                or turn == (run.metadata.get("_xiaox_queued_request") or {}).get("worker_turn_id")
                or key != canonical_digest({"turn_id": turn, "owner": run.user_id})
                or receipt.get("state") != "returned"
                or not isinstance(result, dict)
                or run.status == "cancelled"
                and result.get("execution_state") != "cancelled"
            ):
                continue
            delivered += int(reconcile_queued_chat_reply(context, turn, run_id, run=run))
    return delivered
