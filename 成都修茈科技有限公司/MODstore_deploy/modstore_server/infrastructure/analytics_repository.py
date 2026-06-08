"""SQL implementation of :class:`modstore_server.domain.analytics.AnalyticsRepository`."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from modstore_server.domain.analytics import (
    AnalyticsDashboard,
    CatalogMetrics,
    CommerceMetrics,
    ExecutionMetrics,
)
from modstore_server.models import (
    CatalogItem,
    EmployeeExecutionMetric,
    Purchase,
    RefundRequest,
    Transaction,
)


class SqlAnalyticsRepository:
    """Default ORM-backed analytics read model."""

    def __init__(self, db: Session):
        self.db = db

    def dashboard_for_user(self, user_id: int) -> AnalyticsDashboard:
        total_exec = (
            self.db.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.user_id == user_id)
            .count()
        )
        success_exec = (
            self.db.query(EmployeeExecutionMetric)
            .filter(
                EmployeeExecutionMetric.user_id == user_id,
                EmployeeExecutionMetric.status == "success",
            )
            .count()
        )
        token_sum = (
            self.db.query(func.coalesce(func.sum(EmployeeExecutionMetric.llm_tokens), 0))
            .filter(EmployeeExecutionMetric.user_id == user_id)
            .scalar()
            or 0
        )
        duration_sum = (
            self.db.query(func.coalesce(func.sum(EmployeeExecutionMetric.duration_ms), 0.0))
            .filter(EmployeeExecutionMetric.user_id == user_id)
            .scalar()
            or 0.0
        )
        total_spent = (
            self.db.query(func.coalesce(func.sum(Purchase.amount), 0.0))
            .filter(Purchase.user_id == user_id)
            .scalar()
            or 0.0
        )
        purchase_count = self.db.query(Purchase).filter(Purchase.user_id == user_id).count()
        refund_count = self.db.query(RefundRequest).filter(RefundRequest.user_id == user_id).count()
        wallet_transaction_count = (
            self.db.query(Transaction).filter(Transaction.user_id == user_id).count()
        )
        total_packages = self.db.query(CatalogItem).count()
        public_packages = self.db.query(CatalogItem).filter(CatalogItem.is_public.is_(True)).count()
        employee_packs = (
            self.db.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack").count()
        )

        recent = (
            self.db.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.user_id == user_id)
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(10)
            .all()
        )
        return AnalyticsDashboard(
            execution=ExecutionMetrics(
                total=total_exec,
                success=success_exec,
                failed=max(0, total_exec - success_exec),
                success_rate=(success_exec / total_exec * 100) if total_exec > 0 else 0,
                total_tokens=int(token_sum or 0),
                avg_duration_ms=(
                    (float(duration_sum or 0.0) / total_exec) if total_exec > 0 else 0.0
                ),
            ),
            commerce=CommerceMetrics(
                total_spent=round(float(total_spent), 2),
                purchase_count=purchase_count,
                refund_count=refund_count,
                wallet_transaction_count=wallet_transaction_count,
            ),
            catalog=CatalogMetrics(
                total_packages=total_packages,
                public_packages=public_packages,
                employee_packs=employee_packs,
            ),
            recent_executions=[
                {
                    "id": r.id,
                    "employee_id": r.employee_id,
                    "task": r.task,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "llm_tokens": r.llm_tokens,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in recent
            ],
        )


__all__ = ["SqlAnalyticsRepository"]
