"""Analytics domain DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionMetrics:
    total: int
    success: int
    failed: int
    success_rate: float
    total_tokens: int
    avg_duration_ms: float


@dataclass(frozen=True)
class CommerceMetrics:
    total_spent: float
    purchase_count: int
    refund_count: int
    wallet_transaction_count: int


@dataclass(frozen=True)
class CatalogMetrics:
    total_packages: int
    public_packages: int
    employee_packs: int


@dataclass(frozen=True)
class AnalyticsDashboard:
    execution: ExecutionMetrics
    commerce: CommerceMetrics
    catalog: CatalogMetrics
    recent_executions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution": self.execution.__dict__,
            "commerce": self.commerce.__dict__,
            "catalog": self.catalog.__dict__,
            "spending": {"total": round(float(self.commerce.total_spent), 2)},
            "recent_executions": self.recent_executions,
        }
