"""Append-only customer value evidence records.

These rows are evidence, not mutable business state. Corrections and refunds
must be represented by a new receipt that references the previous evidence;
the original row remains available for audit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DDL, Column, DateTime, Index, Integer, String, Text, event

from modstore_server.db.base import Base


class CustomerValueReceipt(Base):
    __tablename__ = "customer_value_receipts"
    __table_args__ = (
        Index("ix_customer_value_receipts_order_no", "order_no"),
        Index("ix_customer_value_receipts_goal_id", "customer_goal_id"),
        Index("ix_customer_value_receipts_kind_status", "receipt_kind", "verification_status"),
        Index("ix_customer_value_receipts_occurred_at", "occurred_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(String(96), nullable=False, unique=True, index=True)
    receipt_kind = Column(String(32), nullable=False)
    verification_status = Column(String(32), nullable=False, default="pending_evidence")
    customer_ref = Column(String(128), nullable=False, default="")
    customer_goal_id = Column(String(128), nullable=False, default="")
    order_no = Column(String(96), nullable=False, default="")
    artifact_id = Column(String(256), nullable=False, default="")
    acceptance_id = Column(String(128), nullable=False, default="")
    amount_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="CNY")
    payment_provider = Column(String(32), nullable=False, default="")
    provider_trade_no = Column(String(128), nullable=False, default="")
    provider_verification = Column(String(64), nullable=False, default="")
    environment = Column(String(32), nullable=False, default="")
    source_event_id = Column(String(192), nullable=False, default="", index=True)
    source_employee_id = Column(String(128), nullable=False, default="")
    supersedes_receipt_id = Column(String(96), nullable=False, default="")
    evidence_json = Column(Text, nullable=False, default="{}")
    evidence_digest = Column(String(64), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


# ``Base.metadata.create_all`` is the init migration used by the self-hosted
# runtime. Attach the immutability guards to the table creation itself so a new
# database cannot be initialized without the append-only invariant.
event.listen(
    CustomerValueReceipt.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER customer_value_receipts_no_update
        BEFORE UPDATE ON customer_value_receipts
        BEGIN
          SELECT RAISE(ABORT, 'customer_value_receipts is append-only');
        END
        """
    ).execute_if(dialect="sqlite"),
)
event.listen(
    CustomerValueReceipt.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER customer_value_receipts_no_delete
        BEFORE DELETE ON customer_value_receipts
        BEGIN
          SELECT RAISE(ABORT, 'customer_value_receipts is append-only');
        END
        """
    ).execute_if(dialect="sqlite"),
)
event.listen(
    CustomerValueReceipt.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION reject_customer_value_receipt_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'customer_value_receipts is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    CustomerValueReceipt.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER customer_value_receipts_no_mutation
        BEFORE UPDATE OR DELETE ON customer_value_receipts
        FOR EACH ROW EXECUTE FUNCTION reject_customer_value_receipt_mutation()
        """
    ).execute_if(dialect="postgresql"),
)


__all__ = ["CustomerValueReceipt"]
