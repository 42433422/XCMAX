"""Analytics read-model port."""

from __future__ import annotations

from typing import Protocol

from modstore_server.domain.analytics.types import AnalyticsDashboard


class AnalyticsRepository(Protocol):
    """Read-only analytics aggregate for a user."""

    def dashboard_for_user(self, user_id: int) -> AnalyticsDashboard: ...


__all__ = ["AnalyticsRepository"]
