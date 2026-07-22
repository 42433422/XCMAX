"""Append-only alignment evidence for autonomous runtime decisions.

The table stores only a narrow decision envelope. Raw action payloads,
free-form reasons, credentials and customer data have no columns and therefore
cannot leak into the audit trail by accident.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DDL, Column, DateTime, Index, Integer, String, Text, event

from modstore_server.db.base import Base


class AutonomyDecisionAudit(Base):
    __tablename__ = "autonomy_decision_audit"
    __table_args__ = (
        Index("ix_autonomy_decision_action_id", "action_id"),
        Index("ix_autonomy_decision_occurred_at", "occurred_at"),
        Index("ix_autonomy_decision_type_decision", "record_type", "decision"),
        Index("ix_autonomy_decision_run_id", "run_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(96), nullable=False, unique=True, index=True)
    record_type = Column(String(32), nullable=False, default="decision")
    action_id = Column(String(192), nullable=False)
    action = Column(String(128), nullable=False, default="unknown")
    decision = Column(String(16), nullable=False, default="")
    policy = Column(String(128), nullable=False, default="")
    risk_level = Column(String(16), nullable=False, default="blocked")
    actor_class = Column(String(32), nullable=False, default="unknown")
    run_id = Column(String(192), nullable=False, default="")
    prohibited_rule_hits_json = Column(Text, nullable=False, default="[]")
    posthoc_verdict = Column(String(32), nullable=False, default="")
    evidence_ref = Column(String(192), nullable=False, default="")
    source = Column(String(128), nullable=False, default="")
    occurred_at = Column(DateTime, nullable=False)
    recorded_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


event.listen(
    AutonomyDecisionAudit.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER IF NOT EXISTS autonomy_decision_audit_no_update
        BEFORE UPDATE ON autonomy_decision_audit
        BEGIN
          SELECT RAISE(ABORT, 'autonomy_decision_audit is append-only');
        END
        """
    ).execute_if(dialect="sqlite"),
)
event.listen(
    AutonomyDecisionAudit.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION reject_autonomy_decision_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'autonomy_decision_audit is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    AutonomyDecisionAudit.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER autonomy_decision_audit_no_mutation
        BEFORE UPDATE OR DELETE ON autonomy_decision_audit
        FOR EACH ROW EXECUTE FUNCTION reject_autonomy_decision_audit_mutation()
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    AutonomyDecisionAudit.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER IF NOT EXISTS autonomy_decision_audit_no_delete
        BEFORE DELETE ON autonomy_decision_audit
        BEGIN
          SELECT RAISE(ABORT, 'autonomy_decision_audit is append-only');
        END
        """
    ).execute_if(dialect="sqlite"),
)


__all__ = ["AutonomyDecisionAudit"]
