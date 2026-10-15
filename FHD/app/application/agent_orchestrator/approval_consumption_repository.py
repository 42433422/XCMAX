"""Atomic approval consumption; storage failures never count as permission."""

from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import utc_now_iso
from app.db.models.agent_approval import AgentApprovalConsumption


class SQLAlchemyApprovalConsumptionRepository:
    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def consume(self, *, jti: str, run_id: str, step_id: str) -> bool:
        with self._session_factory() as db:
            db.add(
                AgentApprovalConsumption(
                    jti=jti, run_id=run_id, step_id=step_id, consumed_at=utc_now_iso()
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # Only an existing matching key means replay. Other constraint
                # failures remain storage errors and must stop approval.
                if db.get(AgentApprovalConsumption, jti) is not None:
                    return False
                raise
        return True
