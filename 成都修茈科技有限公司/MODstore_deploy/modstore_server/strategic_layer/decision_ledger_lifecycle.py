"""Lifecycle, query, and audit operations for the strategic decision ledger."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from modstore_server.db.strategic import StrategicActionItem
from modstore_server.db.strategic import StrategicDecision as StrategicDecisionModel
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _ledger_module():
    from modstore_server.strategic_layer import decision_ledger

    return decision_ledger


class DecisionLedgerLifecycleMixin:
    """Persisted state transitions and read models shared by the ledger facade."""

    _session_factory: Any

    def review(
        self,
        decision_id: str,
        *,
        reviewer: str,
        review_notes: str,
    ) -> Any:
        """Review a completed decision exactly once."""
        ledger = _ledger_module()
        if not review_notes.strip():
            raise ValueError("review_notes required for review")
        session = self._session_factory()()
        try:
            row = session.execute(
                select(StrategicDecisionModel).where(
                    StrategicDecisionModel.decision_id == decision_id
                )
            ).scalar_one_or_none()
            if row is None:
                raise ledger.DecisionLifecycleError(f"decision not found: {decision_id}")
            if row.status != ledger.DecisionStatus.COMPLETED.value:
                raise ledger.DecisionLifecycleError(
                    f"cannot review decision in status {row.status}; must be completed"
                )
            if row.reviewed_by:
                raise ledger.DecisionLifecycleError("decision already reviewed")
            row.review_notes = review_notes.strip()
            row.reviewed_by = reviewer
            row.updated_at = datetime.now(UTC)
            session.commit()
            return ledger._model_to_record(row)
        except RECOVERABLE_ERRORS:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, decision_id: str) -> Optional[Any]:
        ledger = _ledger_module()
        session = self._session_factory()()
        try:
            row = session.execute(
                select(StrategicDecisionModel).where(
                    StrategicDecisionModel.decision_id == decision_id
                )
            ).scalar_one_or_none()
            return ledger._model_to_record(row) if row else None
        finally:
            session.close()

    def list_recent(
        self,
        *,
        status: Optional[Any] = None,
        decision_type: Optional[Any] = None,
        scope: Optional[str] = None,
        limit: int = 50,
    ) -> List[Any]:
        ledger = _ledger_module()
        session = self._session_factory()()
        try:
            statement = (
                select(StrategicDecisionModel)
                .order_by(desc(StrategicDecisionModel.proposed_at))
                .limit(max(1, min(limit, 500)))
            )
            if status is not None:
                statement = statement.where(StrategicDecisionModel.status == status.value)
            if decision_type is not None:
                statement = statement.where(
                    StrategicDecisionModel.decision_type == decision_type.value
                )
            if scope is not None:
                statement = statement.where(StrategicDecisionModel.scope == scope)
            rows = session.execute(statement).scalars().all()
            return [ledger._model_to_record(row) for row in rows]
        finally:
            session.close()

    def list_action_items(self, decision_id: str) -> List[Dict[str, Any]]:
        session = self._session_factory()()
        try:
            rows = (
                session.execute(
                    select(StrategicActionItem)
                    .where(StrategicActionItem.decision_id == decision_id)
                    .order_by(StrategicActionItem.created_at)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "action_id": row.action_id,
                    "decision_id": row.decision_id,
                    "meeting_id": row.meeting_id,
                    "description": row.description,
                    "assigned_to": row.assigned_to,
                    "status": row.status,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "block_reason": row.block_reason,
                }
                for row in rows
            ]
        finally:
            session.close()

    def _transition(
        self,
        decision_id: str,
        *,
        target_status: Any,
        decided_by: Optional[Any] = None,
        decided_by_str: str = "",
        review_notes: str = "",
        execution_plan: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        review_at: Optional[datetime] = None,
    ) -> Any:
        ledger = _ledger_module()
        session = self._session_factory()()
        try:
            row = session.execute(
                select(StrategicDecisionModel).where(
                    StrategicDecisionModel.decision_id == decision_id
                )
            ).scalar_one_or_none()
            if row is None:
                raise ledger.DecisionLifecycleError(f"decision not found: {decision_id}")
            current = ledger.DecisionStatus(row.status)
            if current == target_status:
                return ledger._model_to_record(row)
            allowed = ledger._ALLOWED_TRANSITIONS.get(current, frozenset())
            if target_status not in allowed:
                raise ledger.DecisionLifecycleError(
                    f"illegal transition {current.value} → {target_status.value} "
                    f"(decision_id={decision_id}); "
                    f"allowed: {[status.value for status in allowed] or 'terminal'}"
                )
            if current in (
                ledger.DecisionStatus.REJECTED,
                ledger.DecisionStatus.WITHDRAWN,
                ledger.DecisionStatus.COMPLETED,
            ):
                raise ledger.DecisionAlreadyDecidedError(
                    f"decision {decision_id} already in terminal status {current.value}"
                )
            now = datetime.now(UTC)
            row.status = target_status.value
            row.updated_at = now
            if decided_by is not None:
                row.decided_by = decided_by.value
                row.decided_at = now
            elif decided_by_str:
                row.decided_by = decided_by_str
                row.decided_at = now
            if review_notes:
                row.review_notes = review_notes
            if execution_plan is not None:
                row.execution_plan_json = json.dumps(execution_plan, ensure_ascii=False)
            if execution_result is not None:
                row.execution_result_json = json.dumps(execution_result, ensure_ascii=False)
            if review_at is not None:
                row.review_at = review_at
            session.commit()
            logger.info(
                "decision transitioned decision_id=%s %s → %s",
                decision_id,
                current.value,
                target_status.value,
            )
            return ledger._model_to_record(row)
        except RECOVERABLE_ERRORS:
            session.rollback()
            raise
        finally:
            session.close()
